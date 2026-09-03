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
Claude Desktop itself is authenticated.

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

A second, independent MCP server — not yet registered in Claude Desktop (see
[docs/roadmap-status.md](docs/roadmap-status.md) open issues). Once added as its own
`mcpServers` entry, it exposes one tool:

**`run_watchlist_import(user_id, raw_input, input_type)`** — turns an Excel file path,
pasted CSV text, or a freeform request into watchlist changes. `input_type` is one of
`"file_path"`, `"csv_text"`, or `"freeform"`. **Requires `ANTHROPIC_API_KEY`** — its
`resolve` step makes its own LLM call, separate from `get_top_momentum_with_commentary`'s.

> Import the watchlist at C:\Users\arjun2\Downloads\my_stocks.xlsx for user 1.

> Add AAPL, MSFT, and NVDA to my "Tech Growth" watchlist for user 1.

Internally, `agent_worker` runs its own LangGraph graph (`resolve` → `apply_loop` →
`summarize`) and talks to the `stockpeek` MCP server above as an MCP *client* — it never
imports `mcp_server` code directly. See CLAUDE.md's Architecture section for the
documented write-boundary exception this required.
