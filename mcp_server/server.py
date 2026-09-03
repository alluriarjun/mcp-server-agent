"""StockPeek MCP Server (design-doc.md Section 8.1).

Minimal, working slice for Week 3-4 validation: read tools backed by the tables
that already exist in the shared database (watchlists, price_timeseries).

Not yet implemented (see docs/roadmap-status.md):
  - get_quote            — needs the Finnhub live-quote integration (Section 2.5)
  - get_user_portfolios  — portfolio schema/CRUD not built yet (core-api); get_top_momentum's
                            universe is watchlists only until then
  - save_analysis_finding / create_alert — analysis_findings / alerts tables don't exist yet

Documented exception to CLAUDE.md's write boundary: apply_watchlist_update below writes
to watchlists/watchlist_items/stocks, tables design-doc.md Section 3.3 otherwise reserves
for core-api. This was a deliberate call (see docs/roadmap-status.md) made so the
agent_worker watchlist-import agent can persist in one self-contained repo rather than
calling core-api's REST API directly, which the Agent Worker is never allowed to do.
"""

from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from agent_worker.momentum_synthesis import add_commentary
from shared.config import settings
from shared.db import get_cursor
from shared.llm_errors import describe_llm_error, missing_api_key_error

server = MCPServer(
    name="stockpeek-mcp-server",
    version="0.1.0",
    instructions=(
        "Read-only access to StockPeek watchlists and stored daily OHLCV history. "
        "Live quotes, portfolios, and write tools are not implemented yet."
    ),
)


@server.tool()
def get_timeseries(
    symbol: str,
    exchange: str = "NASDAQ",
    bar_interval: str = "daily",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Historical OHLCV bars for a stock from price_timeseries, most recent first."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT pt.timestamp, pt.open, pt.high, pt.low, pt.close, pt.volume
            FROM price_timeseries pt
            JOIN stocks s ON s.id = pt.stock_id
            WHERE s.symbol = %s AND s.exchange = %s AND pt.bar_interval = %s
            ORDER BY pt.timestamp DESC
            LIMIT %s
            """,
            (symbol.upper(), exchange.upper(), bar_interval, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "timestamp": row["timestamp"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": row["volume"],
        }
        for row in rows
    ]


@server.tool()
def get_user_watchlists(user_id: int) -> list[dict[str, Any]]:
    """All named watchlists for a user, each with the symbols it tracks."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT w.id AS watchlist_id, w.name, w.created_at,
                   s.symbol, s.exchange, s.name AS stock_name
            FROM watchlists w
            LEFT JOIN watchlist_items wi ON wi.watchlist_id = w.id
            LEFT JOIN stocks s ON s.id = wi.stock_id
            WHERE w.user_id = %s
            ORDER BY w.created_at, s.symbol
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    watchlists: dict[int, dict[str, Any]] = {}
    for row in rows:
        entry = watchlists.setdefault(
            row["watchlist_id"],
            {
                "watchlist_id": row["watchlist_id"],
                "name": row["name"],
                "created_at": row["created_at"].isoformat(),
                "symbols": [],
            },
        )
        if row["symbol"]:
            entry["symbols"].append(
                {"symbol": row["symbol"], "exchange": row["exchange"], "name": row["stock_name"]}
            )
    return list(watchlists.values())


@server.tool()
def apply_watchlist_update(
    user_id: int,
    watchlist_name: str,
    action: str,
    symbol: str | None = None,
    exchange: str = "NASDAQ",
) -> dict[str, Any]:
    """Apply one watchlist operation: add/remove a symbol, or create an empty watchlist.

    Single-item, idempotent write tool for the agent_worker watchlist-import agent
    (docs/design-doc.md discussion, Week 5-6). Called once per resolved operation —
    there is no batch/list form. action is one of "add", "remove", "create_watchlist".

    "add" finds-or-creates the named watchlist, finds-or-creates the stock (a minimal
    symbol+exchange stub if unseen, mirroring core-api's WatchlistService.findOrCreateStock
    so a later core-api sync backfills it normally), then finds-or-creates the
    watchlist_item — safe to call repeatedly for the same symbol.

    "remove" deletes the watchlist_item if present; a missing watchlist or stock is a
    no-op, not an error. "create_watchlist" creates an empty named watchlist if it
    doesn't already exist.

    Every lookup is scoped to (user_id, watchlist_name), which is also the enforcement
    point for ownership — a watchlist belonging to a different user is simply not found,
    never mutated.
    """
    if action not in ("add", "remove", "create_watchlist"):
        return {"status": "error", "reason": f"unknown action '{action}'"}
    if action in ("add", "remove") and not symbol:
        return {"status": "error", "reason": f"symbol is required for action '{action}'"}

    with get_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cur.fetchone() is None:
            return {"status": "error", "reason": f"user {user_id} not found"}

        cur.execute(
            "SELECT id FROM watchlists WHERE user_id = %s AND name = %s",
            (user_id, watchlist_name),
        )
        row = cur.fetchone()
        watchlist_id = row["id"] if row else None

        if action == "create_watchlist":
            if watchlist_id is not None:
                return {"status": "already_exists", "watchlist_id": watchlist_id}
            cur.execute(
                "INSERT INTO watchlists (user_id, name) VALUES (%s, %s) RETURNING id",
                (user_id, watchlist_name),
            )
            return {"status": "created", "watchlist_id": cur.fetchone()["id"]}

        if action == "remove":
            if watchlist_id is None:
                return {"status": "noop", "reason": "watchlist not found"}
            cur.execute(
                "SELECT id FROM stocks WHERE symbol = %s AND exchange = %s",
                (symbol.upper(), exchange.upper()),
            )
            stock_row = cur.fetchone()
            if stock_row is None:
                return {"status": "noop", "reason": "stock not found"}
            cur.execute(
                "DELETE FROM watchlist_items WHERE watchlist_id = %s AND stock_id = %s",
                (watchlist_id, stock_row["id"]),
            )
            removed = cur.rowcount > 0
            return {
                "status": "removed" if removed else "noop",
                "watchlist_id": watchlist_id,
                "symbol": symbol.upper(),
            }

        # action == "add"
        watchlist_created = watchlist_id is None
        if watchlist_created:
            cur.execute(
                "INSERT INTO watchlists (user_id, name) VALUES (%s, %s) RETURNING id",
                (user_id, watchlist_name),
            )
            watchlist_id = cur.fetchone()["id"]

        symbol = symbol.upper()
        exchange = exchange.upper()
        cur.execute(
            "SELECT id FROM stocks WHERE symbol = %s AND exchange = %s",
            (symbol, exchange),
        )
        stock_row = cur.fetchone()
        stock_created = stock_row is None
        if stock_created:
            # Minimal stub, mirroring core-api's WatchlistService.findOrCreateStock —
            # name/sector left null, currency/asset_type fall back to their DDL defaults.
            # A future core-api sync backfills real metadata and price history for it.
            cur.execute(
                "INSERT INTO stocks (symbol, exchange) VALUES (%s, %s) RETURNING id",
                (symbol, exchange),
            )
            stock_id = cur.fetchone()["id"]
        else:
            stock_id = stock_row["id"]

        cur.execute(
            "SELECT 1 FROM watchlist_items WHERE watchlist_id = %s AND stock_id = %s",
            (watchlist_id, stock_id),
        )
        already_present = cur.fetchone() is not None
        if not already_present:
            cur.execute(
                "INSERT INTO watchlist_items (watchlist_id, stock_id) VALUES (%s, %s)",
                (watchlist_id, stock_id),
            )

        return {
            "status": "already_present" if already_present else "added",
            "watchlist_id": watchlist_id,
            "watchlist_created": watchlist_created,
            "stock_id": stock_id,
            "stock_created": stock_created,
            "symbol": symbol,
            "exchange": exchange,
        }


@server.tool()
def get_top_momentum(
    user_id: int,
    range_days: int = 30,
    limit: int = 10,
    recent_volume_days: int = 5,
    baseline_volume_days: int = 20,
    volume_confirm_ratio: float = 1.2,
) -> list[dict[str, Any]]:
    """Rank symbols in a user's watchlists by price momentum, with a volume-surge signal.

    Universe is every distinct symbol across the user's watchlists (not portfolios —
    that schema doesn't exist yet, see docs/roadmap-status.md). This is a pure numeric
    screen over stored daily OHLCV, no LLM/agent involvement — the deterministic
    ranking step that a momentum-interpretation agent would run on top of, not a
    replacement for it (design-doc.md Section 8.2).

    return_pct: close on the most recent bar vs close on the oldest bar within the
    last `range_days`.
    volume_ratio: average volume over the most recent `recent_volume_days` bars
    divided by average volume over the `baseline_volume_days` bars immediately
    before that. volume_confirmed is True when volume_ratio >= volume_confirm_ratio
    (default: recent volume at least 20% above its own recent baseline).
    """
    lookback_days = range_days + recent_volume_days + baseline_volume_days

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.id AS stock_id, s.symbol, s.exchange
            FROM watchlists w
            JOIN watchlist_items wi ON wi.watchlist_id = w.id
            JOIN stocks s ON s.id = wi.stock_id
            WHERE w.user_id = %s
            """,
            (user_id,),
        )
        universe = cur.fetchall()

        if not universe:
            return []

        stock_ids = [row["stock_id"] for row in universe]
        cur.execute(
            """
            SELECT stock_id, timestamp, close, volume
            FROM price_timeseries
            WHERE stock_id = ANY(%s) AND bar_interval = 'daily'
              AND timestamp >= NOW() - (%s || ' days')::interval
            ORDER BY stock_id, timestamp ASC
            """,
            (stock_ids, lookback_days),
        )
        bars = cur.fetchall()

    symbols_by_id = {row["stock_id"]: row for row in universe}

    bars_by_stock: dict[int, list[dict[str, Any]]] = {}
    for bar in bars:
        bars_by_stock.setdefault(bar["stock_id"], []).append(bar)

    min_bars_needed = recent_volume_days + baseline_volume_days + 2
    results = []
    for stock_id, rows in bars_by_stock.items():
        if len(rows) < min_bars_needed:
            continue

        cutoff = rows[-1]["timestamp"] - timedelta(days=range_days)
        window_rows = [r for r in rows if r["timestamp"] >= cutoff]
        if len(window_rows) < 2:
            continue

        start_close = float(window_rows[0]["close"])
        end_close = float(window_rows[-1]["close"])
        return_pct = (end_close - start_close) / start_close * 100

        recent = rows[-recent_volume_days:]
        baseline = rows[-(recent_volume_days + baseline_volume_days) : -recent_volume_days]
        recent_avg_volume = sum(r["volume"] for r in recent) / len(recent)
        baseline_avg_volume = sum(r["volume"] for r in baseline) / len(baseline)
        volume_ratio = recent_avg_volume / baseline_avg_volume if baseline_avg_volume else None

        stock = symbols_by_id[stock_id]
        results.append(
            {
                "symbol": stock["symbol"],
                "exchange": stock["exchange"],
                "return_pct": round(return_pct, 2),
                "start_price": start_close,
                "end_price": end_close,
                "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
                "volume_confirmed": volume_ratio is not None and volume_ratio >= volume_confirm_ratio,
            }
        )

    results.sort(key=lambda r: r["return_pct"], reverse=True)
    return results[:limit]


@server.tool()
def get_top_momentum_with_commentary(
    user_id: int,
    range_days: int = 30,
    limit: int = 10,
    recent_volume_days: int = 5,
    baseline_volume_days: int = 20,
    volume_confirm_ratio: float = 1.2,
) -> list[dict[str, Any]]:
    """get_top_momentum's ranking plus a per-stock LLM headline/rationale.

    Tier 2 of the design in docs/roadmap-status.md: get_top_momentum does the
    deterministic ranking/filtering; this only adds narrative interpretation on
    top of that already-small, already-decided result set (agent_worker.momentum_synthesis)
    — the LLM never re-ranks or filters.

    On failure, returns a single-item list with {"status": "failed", "error": ...}
    instead of raising — an unhandled exception here would otherwise surface to the
    caller as MCP's generic "Error executing tool" with no detail at all.
    """
    ranked = get_top_momentum(
        user_id=user_id,
        range_days=range_days,
        limit=limit,
        recent_volume_days=recent_volume_days,
        baseline_volume_days=baseline_volume_days,
        volume_confirm_ratio=volume_confirm_ratio,
    )
    if not settings.anthropic_api_key:
        return [{"status": "failed", "error": missing_api_key_error()}]
    try:
        return add_commentary(ranked)
    except Exception as exc:
        return [{"status": "failed", "error": describe_llm_error(exc)}]


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
