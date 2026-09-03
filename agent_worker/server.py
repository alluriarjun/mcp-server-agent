"""StockPeek Agent Worker MCP Server.

Agent Worker's own front door — a second, independent MCP server, registered as its
own entry in Claude Desktop's mcpServers config alongside the stockpeek entry. Claude
Desktop is just today's caller: since this is reached over the MCP protocol like any
other tool, a scheduler or script could call run_watchlist_import instead tomorrow
without any change below.

Internally this process is an MCP *client* of the stockpeek MCP server for every read
and write it needs (agent_worker/mcp_client.py) — it never imports mcp_server code or
opens its own DB connection.
"""

from mcp.server.mcpserver import MCPServer

from agent_worker.watchlist_import import run_watchlist_import as _run_watchlist_import
from shared.config import settings
from shared.llm_errors import describe_llm_error, missing_api_key_error

server = MCPServer(
    name="stockpeek-agent-worker",
    version="0.1.0",
    instructions=(
        "Runs StockPeek's agentic workflows. run_watchlist_import turns an Excel file, "
        "pasted CSV, or a freeform request into watchlist changes, applied one stock "
        "at a time via the stockpeek MCP server."
    ),
)


@server.tool()
async def run_watchlist_import(
    user_id: int, raw_input: str, input_type: str = "freeform"
) -> dict:
    """Resolve raw watchlist input and apply it, one stock at a time.

    input_type: "file_path" (a local path to an .xlsx/.xlsm/.csv/.txt file),
    "csv_text" (pasted CSV content), or "freeform" (a plain natural-language request).
    Returns a structured summary: the resolved proposal, the per-stock apply results,
    and a short summary_text. On failure, returns {"status": "failed", "error": ...}
    with an actionable message instead of raising — an unhandled exception here would
    otherwise surface to the caller as MCP's generic "Error executing tool" with no
    detail at all.
    """
    if not settings.anthropic_api_key:
        return {"status": "failed", "error": missing_api_key_error()}
    try:
        summary = await _run_watchlist_import(user_id, raw_input, input_type)
        return summary.model_dump()
    except FileNotFoundError as exc:
        return {"status": "failed", "error": f"Input file not found: {exc}"}
    except Exception as exc:
        return {"status": "failed", "error": describe_llm_error(exc)}


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
