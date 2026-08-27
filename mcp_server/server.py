"""StockPeek MCP Server (design-doc.md Section 8.1).

Minimal, working slice for Week 3-4 validation: two read tools backed by the
tables that already exist in the shared database (watchlists, price_timeseries).

Not yet implemented (see docs/roadmap-status.md):
  - get_quote            — needs the Finnhub live-quote integration (Section 2.5)
  - get_user_portfolios  — portfolio schema/CRUD not built yet (core-api)
  - save_analysis_finding / create_alert — analysis_findings / alerts tables don't exist yet
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

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


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
