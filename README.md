# mcp-server-agent

MCP Server & Agent Worker for StockPeek (Python). See [CLAUDE.md](CLAUDE.md) and
[docs/design-doc.md](docs/design-doc.md) for the full system design, and
[docs/roadmap-status.md](docs/roadmap-status.md) for current build status.

## Running

```bash
python -m mcp_server
python -m agent_worker
```

## Using with Claude Desktop

Once `stockpeek` is registered as an MCP server in Claude Desktop, the tools below are
available to any chat. Claude Desktop's own chat session and the MCP server's tool calls
use separate credentials — `get_top_momentum_with_commentary` makes its own outbound call
to the Claude API and needs a real `ANTHROPIC_API_KEY` set in `.env` regardless of how
Claude Desktop itself is authenticated. **A key alone isn't enough** — the API account
also needs an actual credit balance (Billing, separate from a Claude.ai/Desktop
subscription); a valid-but-uncredited key fails with a 400 `invalid_request_error`,
not a 401, so don't mistake it for an auth problem.

`apply_watchlist_update` should be **disabled** in Claude Desktop's own per-tool toggle
(chat compose bar → tools icon → `stockpeek` → toggle off). It stays registered on the
server — the Agent Worker's MCP client reaches it directly and is unaffected by that
toggle — but leaving it enabled for chat lets Claude Desktop's own model call it straight
from a simple request, bypassing `run_watchlist_import`'s `resolve` step (and its
sanitization/validation) entirely. Confirmed in practice: see
[docs/roadmap-status.md](docs/roadmap-status.md).

### Sample queries

**`get_timeseries`** — historical OHLCV bars, no API key needed

> Get me the last 30 daily bars for IBM on NYSE from StockPeek.

> Show the historical OHLCV data for MRVL on NASDAQ, daily interval, last 10 bars.

**`get_user_watchlists`** — a user's named watchlists and tracked symbols, no API key needed

> What watchlists does StockPeek user 1 have, and what's in them?

**`get_top_momentum`** — deterministic price/volume momentum screen, no API key needed

> Using StockPeek, rank user 1's watchlist by momentum over the last 30 days, top 5.

> Show StockPeek's top momentum stocks for user 1, 60-day range, with volume surge confirmation.

**`get_top_momentum_with_commentary`** — same ranking plus an LLM headline/rationale per stock, **requires `ANTHROPIC_API_KEY`**

> Give me StockPeek's top momentum picks for user 1 with commentary on why each one is moving.

Notes:
- Sample data in dev: one user (`id=1`), one watchlist ("Arjun Tech Picks"), symbols including
  `MRVL`/`QQQM` (NASDAQ) and `IBM` (NYSE).
- `get_top_momentum` needs at least `recent_volume_days + baseline_volume_days + 2` (≈27 by
  default) daily bars per symbol to return a result — it returns fewer/no rows if the price
  sync hasn't backfilled that much history yet.
- Being explicit about "StockPeek" and the tool's intent (timeseries vs. watchlists vs.
  momentum) in your prompt helps Claude Desktop pick the right tool.

## Agent Worker (`stockpeek-agent-worker`)

A second, independent MCP server, registered as its own `mcpServers` entry in Claude
Desktop alongside `stockpeek`. Exposes one tool:

**`run_watchlist_import(user_id, raw_input, input_type)`** — turns an Excel file path,
pasted CSV text, or a freeform request into watchlist changes. `input_type` is one of
`"file_path"`, `"csv_text"`, or `"freeform"`. **Requires `ANTHROPIC_API_KEY` + billing
credits** (see above) — its `resolve` step makes its own LLM call, separate from
`get_top_momentum_with_commentary`'s. On failure it returns
`{"status": "failed", "error": "..."}` with an actionable message rather than an opaque
MCP error.

**Validated live end-to-end** (2026-09-03): "Add IONQ to my Tech Growth watchlist for
user 1 using stockpeek-agent-worker" correctly resolved and applied via `resolve` →
`apply_loop`, landing IONQ in the existing "Tech Growth" watchlist.

> Import the watchlist at C:\Users\arjun2\Downloads\my_stocks.xlsx for user 1.

> Add AAPL, MSFT, and NVDA to my "Tech Growth" watchlist for user 1, using stockpeek-agent-worker.

Internally, `agent_worker` runs its own LangGraph graph (`resolve` → `apply_loop` →
`summarize`) and talks to the `stockpeek` MCP server above as an MCP *client* — it never
imports `mcp_server` code directly. See CLAUDE.md's Architecture section for the
documented write-boundary exception this required.

### Restarting after a code or `.env` change

Both `stockpeek` and `stockpeek-agent-worker` are long-lived processes Claude Desktop
starts once and keeps running for the whole app session — they don't reread source files
or `.env` on their own. After editing code, or after adding/changing `ANTHROPIC_API_KEY`,
fully quit Claude Desktop (system tray icon → Quit, not just closing the window) and
relaunch it. The one exception is the inner `mcp_server` subprocess `agent_worker` spawns
for itself on every `run_watchlist_import` call — that one is fresh every time, but the
outer `agent_worker` process reading `.env` is not.
