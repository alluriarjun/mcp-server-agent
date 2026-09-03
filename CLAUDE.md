# mcp-server-agent — MCP Server & Agent Worker (Python)

Full design doc: @docs/design-doc.md (read this first, every session — covers the whole system, not just this repo)

## What this repo is

This repo contains the **MCP Server** and **Agent Worker** from the design doc (Section 3.1). It is one of two repos in this project:

- `core-api` (sibling repo, separate git history) — Java / Spring Boot. User-facing REST backend.
- `mcp-server-agent` (this repo) — Python. MCP server + LangGraph agent worker.

**These two repos never share code.** They are independent consumers of the same PostgreSQL/TimescaleDB database. Do not suggest importing code from `core-api`, and the Agent Worker must talk **only** to the local MCP Server — never directly to the Core API's REST endpoints. See design-doc.md Section 3.3 for why this boundary matters.

## Current Phase

See @docs/roadmap-status.md for what's built, what's in progress, and what's deferred.

## Architecture (this repo's scope)

- `mcp_server/` — official MCP SDK server exposing read + write tools (design-doc.md Section 8.1):
  `get_quote`, `get_timeseries`, `get_user_watchlists`, `get_user_portfolios`, `save_analysis_finding`, `create_alert`,
  plus `apply_watchlist_update` (see write-boundary exception below)
- `agent_worker/` — its own MCP server (a second `mcpServers` entry, not code imported in-process by `mcp_server`),
  connecting to `mcp_server` as an MCP *client* for every read/write it needs. Runs LangGraph graphs:
  - `watchlist_import` (`agent_worker/watchlist_import.py`): resolve (1 LLM call, turns raw Excel/CSV/freeform
    input into a structured proposal) → apply_loop (N single-item MCP calls, no LLM) → summarize (no LLM).
    Trigger-agnostic — Claude Desktop calls `run_watchlist_import` today, but nothing in the graph assumes that.
  - The portfolio-analysis pipeline from design-doc.md Section 8.2 (Data Gathering → Technical Analysis →
    Sentiment Analysis (conditional) → Report Synthesis) is a separate, not-yet-built graph.
- This repo independently implements its own data access against the shared DB — it does NOT call into the Java `marketdata` package.
- Owns writes to `analysis_findings`, via `save_analysis_finding`.
  **Documented exception**: `apply_watchlist_update` also writes to `watchlists`/`watchlist_items`/`stocks` —
  tables otherwise reserved for `core-api` — so the watchlist-import agent can persist without the Agent
  Worker ever calling Core API's REST API directly (still prohibited). Mirrors core-api's own
  `WatchlistService.findOrCreateStock` stub-row behavior for unseen symbols. No other table is written from
  this repo.
- Agent never calls a "send notification" tool directly — its responsibility ends at `save_analysis_finding`. Delivery is a future Notification Service reacting to the DB write event (Section 8.4).

## Conventions

<!-- Fill these in as you establish them during Weeks 3-6, e.g.: -->
- Python version: 3.12
- Package manager: uv / poetry
- Run MCP server: `python -m mcp_server`
- Run agent worker: `python -m agent_worker`
- Test: `pytest`
- LLM model routing: Haiku for dev/iteration, Sonnet for production/eval runs (design-doc.md Section 6.2)

## Things to always do

- All agent outputs must validate against Pydantic schemas before being treated as final (design-doc.md Section 8.2) — no unstructured/freeform critical output.
- Sanitize any untrusted tool result (e.g., news article text) before it enters LLM context — prompt-injection defense (Section 8.3).
- Every LLM call and tool call should be traced via Langfuse — wire this up from Week 7 onward, but keep the instrumentation points in mind from Week 3.
- Don't add yfinance or unofficial scrapers as a data source — see design-doc.md Section 14.3.
- Any MCP tool that calls the Claude API directly should check for a missing `ANTHROPIC_API_KEY` up front and
  wrap the call, returning `{"status": "failed", "error": "..."}` via `shared/llm_errors.py`'s
  `missing_api_key_error()`/`describe_llm_error()` rather than letting an exception surface as MCP's opaque
  "Error executing tool" with no detail. `describe_llm_error` unwraps `BaseExceptionGroup` first — the MCP
  SDK's `ClientSession`/`stdio_client` wrap exceptions in one via `anyio` TaskGroups, sometimes nested.
- A new write tool intended only for the Agent Worker's own use is still reachable by Claude Desktop's own
  model if it's connected to the same MCP server — there's no server-side way to restrict a tool to one caller.
  If that matters (bypassing an LLM-driven resolve/validation step, e.g.), disable it in Claude Desktop's
  per-tool toggle rather than assuming only the intended caller will use it (see design-doc.md Section 8.1).
- `shared/config.py` loads `.env` via an absolute path, not cwd-relative — Claude Desktop doesn't reliably set
  `cwd` to the repo root when spawning `mcp_server`/`agent_worker`. Don't revert this to a bare `load_dotenv()`.
