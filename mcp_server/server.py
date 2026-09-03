"""StockPeek MCP Server (design-doc.md Section 8.1).

Minimal, working slice for Week 3-4 validation: read tools backed by the tables
that already exist in the shared database (watchlists, price_timeseries).

Not yet implemented (see docs/roadmap-status.md):
  - get_quote            — needs the Finnhub live-quote integration (Section 2.5)
  - get_user_portfolios  — portfolio schema/CRUD not built yet (core-api); get_top_momentum's
                            universe is watchlists only until then
  - save_analysis_finding / create_alert — analysis_findings / alerts tables don't exist yet
"""

from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from agent_worker.momentum_synthesis import add_commentary
from shared.db import get_cursor

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
    """
    ranked = get_top_momentum(
        user_id=user_id,
        range_days=range_days,
        limit=limit,
        recent_volume_days=recent_volume_days,
        baseline_volume_days=baseline_volume_days,
        volume_confirm_ratio=volume_confirm_ratio,
    )
    return add_commentary(ranked)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
