"""agent_worker's MCP *client* connection to the StockPeek MCP server.

This is the piece that makes agent_worker a real, independent process rather than
code imported in-process by mcp_server (which is what momentum_synthesis.py still
does today — see docs/roadmap-status.md). Every read/write agent_worker needs goes
through here as an actual MCP tool call, never a direct import of mcp_server code or
a direct DB connection — design-doc.md Section 3.3's "Agent Worker connects only to
the MCP Server" boundary, made real.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def stockpeek_session():
    """Spawn `python -m mcp_server` as a subprocess and yield a live ClientSession.

    One session is meant to be reused across an entire graph run (e.g. every
    resolve + apply_loop call in a single watchlist-import run) rather than
    reopened per tool call — cheaper, and it's how a real MCP client is meant
    to be used.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    """Call an MCP tool and return its structured result, raising on tool-side errors."""
    result = await session.call_tool(name, arguments)
    if result.is_error:
        raise RuntimeError(f"MCP tool '{name}' failed: {result.content}")
    return result.structured_content
