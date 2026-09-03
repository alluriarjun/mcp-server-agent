# Roadmap Status — core-api

> Update this file at the end of each Claude Code session. Keep entries short — this is a status board, not a journal. See @CLAUDE.md and @docs/design-doc.md Section 11 for the full 8-week plan this tracks against.

**Last updated:** 2026-09-03
**Current week:** 5

---

## Week 1–2 — Foundation

- [x] Project skeleton: Spring Boot 3.4.1 / Java 21 target, pom.xml, Maven wrapper, package structure (`auth`, `portfolio`, `watchlist`, `marketdata`), `application.yml`, health endpoint, SecurityConfig stub, contextLoads test passing
- [ ] Auth (Spring Security + JWT)
- [x] Watchlist schema + CRUD (multiple named lists)
- [ ] Portfolio schema + CRUD (multiple named lists) — deferred, not blocking MCP phase
- [x] `price_timeseries` schema (TimescaleDB hypertable, `V2__price_timeseries.sql`) + `DataProvider`/`AlphaVantageProvider` + `PriceSyncService`, triggered on-demand via `POST /api/marketdata/sync?full={bool}` (backfill vs. incremental). Sources distinct symbols from watchlists only — portfolio holdings folded in once portfolio CRUD exists.
- [ ] `@Scheduled` daily post-market-close job calling `PriceSyncService` automatically (currently API-triggered only)
- [ ] Basic timeseries endpoint (1D–5Y aggregation) — read side of `price_timeseries`, not built yet
- [ ] Live-quote endpoint (Finnhub, read-through, not persisted)
- [x] Dockerized (docker-compose with TimescaleDB, Redis, pgAdmin, RedisInsight)

**Deviations from design doc:** none

## Week 3–4 — MCP Server Layer (mcp-server-agent repo)

- [x] Project scaffold: `.venv`, folder structure (`mcp_server/`, `agent_worker/`, `shared/`, `tests/`), `requirements.txt` (mcp, psycopg2-binary, anthropic, pydantic, python-dotenv, langgraph) + `requirements-lock.txt`, `shared/config.py` + `shared/db.py` (env-based settings, psycopg2 connection helper), `.env.example`, stub `__main__.py` for both `python -m mcp_server` and `python -m agent_worker`
- [x] Standalone Python MCP server (`mcp_server/server.py`, official SDK's `MCPServer`, mcp==2.1.1 — note: 2.x renamed `FastMCP` to `MCPServer`, imported from `mcp.server.mcpserver`) with three working read tools against the real shared DB: `get_timeseries` (price_timeseries, joined on stocks), `get_user_watchlists` (watchlists + watchlist_items + stocks), and `get_top_momentum` (deterministic momentum screen — % return over a window + a volume-surge confirmation signal — across the distinct symbols in a user's watchlists; no LLM/agent involved, this is the ranking step a future momentum-interpretation agent would consume, not a replacement for it). All three validated end-to-end over stdio with a real `ClientSession` (list_tools + call_tool against the live `core-api-db-1` container) — confirmed correct structured output.
- [x] Wired into Claude Desktop for manual chat-based validation: added an `mcpServers.stockpeek` entry (pointing at the venv's `python.exe` with `PYTHONPATH` set, since Claude Desktop doesn't reliably support a `cwd` field) to the packaged app's actual config path — `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`, **not** the plain `%APPDATA%\Claude\` path, since this is the MSIX-packaged build. Merged in, didn't overwrite existing `cowork`/`epitaxy` prefs already in that file.
- [ ] `get_quote` (needs Finnhub live-quote integration, Section 2.5), `get_user_portfolios` (blocked on portfolio schema/CRUD in core-api), `save_analysis_finding`/`create_alert` (blocked on `analysis_findings`/alerts tables, which don't exist in the DB yet — only V1/V2 migrations exist so far)
- [x] `get_top_momentum_with_commentary` (`mcp_server/server.py`, backed by `agent_worker/momentum_synthesis.py`): tier-2 slice on top of `get_top_momentum` — a single structured Claude API call (`client.messages.parse`, Pydantic `MomentumCommentaryBatch` output, per CLAUDE.md's "validate all agent outputs against Pydantic schemas") that adds a headline + 1-2 sentence rationale per already-ranked stock. Deliberately does NOT re-rank or filter — that stays in the deterministic `get_top_momentum` tier. Uses `settings.llm_model_dev` (Haiku) per the design doc's dev/prod model routing. Code path validated end-to-end; the live LLM call itself wasn't re-confirmed after the key was set (2026-09-03), but `resolve` in `agent_worker/watchlist_import.py` uses the identical `client.messages.parse` pattern and *is* confirmed live (see Week 5-6), so the same call shape is known working.
- [ ] Simple LLM client (Claude API) connecting to MCP server
- [x] Full loop validated: MCP client → tool call → structured response (validated directly; natural-language-driven client not yet built)

## Week 5–6 — Agentic Analysis Layer (mcp-server-agent repo)

- [ ] Multi-agent system in LangGraph: Momentum, Value, Sentiment, Synthesis agents
- [ ] Session memory via LangGraph checkpointers
- [x] Pydantic-validated structured outputs across agent boundaries (`agent_worker/schemas.py`: `WatchlistOperation`, `WatchlistUpdateProposal`, `AppliedOperation`, `WatchlistImportSummary`)
- [x] **Watchlist-import agent** — first real LangGraph graph, and the first time `agent_worker` runs as its own process rather than being imported in-process by `mcp_server`:
  - `agent_worker/server.py` — a second, independent MCP server (`stockpeek-agent-worker`), registered as its own `mcpServers` entry in Claude Desktop's config alongside `stockpeek`. Exposes one tool, `run_watchlist_import(user_id, raw_input, input_type)`.
  - `agent_worker/mcp_client.py` — `stockpeek_session()` spawns `python -m mcp_server` as a subprocess and opens a real `ClientSession` over stdio; every read/write agent_worker needs goes through `call_tool()` on that session, never a direct DB connection or a Python import of `mcp_server` code.
  - `agent_worker/watchlist_import.py` — the graph: `resolve` (1 LLM call via `client.messages.parse`, reads `get_user_watchlists` for context, turns raw Excel/`.xlsx`/CSV/freeform input into a `WatchlistUpdateProposal`) → `apply_loop` (no LLM, one `apply_watchlist_update` MCP call per resolved operation) → `summarize` (no LLM, packages the result). Resolve's system prompt treats raw input as untrusted data per CLAUDE.md's sanitization rule.
  - `mcp_server/server.py`'s new `apply_watchlist_update` tool — single-item, idempotent (find-or-create at every level: watchlist → stock → item), stub-creates unseen stocks exactly like core-api's `WatchlistService.findOrCreateStock` (symbol+exchange only). **Documented exception** to the write-boundary rule — see CLAUDE.md and design-doc.md Section 8.1.
  - **Validated live end-to-end from Claude Desktop, twice** (2026-09-03): the first "add AAPL" run actually went through the `apply_watchlist_update` direct-call bypass below, not `resolve` — a follow-up "add IONQ ... using stockpeek-agent-worker" run is the one that genuinely exercised `resolve`'s live Claude API call, after fixing the `ANTHROPIC_API_KEY`/billing chain below. IONQ landed in the same "Tech Growth" watchlist alongside AAPL, confirmed via direct DB read.
  - **Claude Desktop can bypass the agent**: `apply_watchlist_update` being directly callable from `stockpeek` means Claude Desktop's own model can call it straight from chat for a simple, fully-specified request, skipping `resolve` entirely (no sanitization, no confidence scoring, no untrusted-input handling). Mitigated by disabling `apply_watchlist_update` in Claude Desktop's own per-tool toggle (chat compose bar → tools icon → `stockpeek` → toggle off) while leaving it registered on the server — `agent_worker`'s MCP client connects directly to `mcp_server` as its own subprocess, entirely outside Claude Desktop's tool-choice/toggle logic, so `run_watchlist_import` is unaffected. Confirmed working: a direct-call attempt after toggling off came back "user has chosen to disallow the tool call".

## Week 7–8 — Observability, Reliability & Polish (Core API's slice)

- [ ] Scale-testing exercise: Core API load test (k6/Locust)
- [ ] Final review against design-doc.md for drift

**Deviations from design doc:** _(none yet)_

---

## Open issues / blockers

- `feature 2` (periodic per-watchlist commentary agent, scheduler-triggered) is designed at a conceptual level only — no graph, tool, or migration built yet. Blocked on `analysis_findings` not existing (needs a new `core-api` Flyway migration) and on `save_analysis_finding` not being implemented.
- `get_top_momentum_with_commentary`'s live LLM call is still unconfirmed after the key/billing fix below — `resolve`'s identical call shape is confirmed live instead (see Week 5-6), so it's low-risk, but worth a direct re-check next session.

## Decisions made during build (not yet reflected in design-doc.md)

- `price_timeseries.interval` renamed to `bar_interval` in the actual schema — `INTERVAL` is a reserved word in H2 (used for `ddl-auto: validate`/schema generation under the `test` profile) and the unquoted DDL fails there. Reflected in design-doc.md Section 4.
- Sync is currently exposed only as `POST /api/marketdata/sync?full={bool}` (manual/API trigger); the `@Scheduled` daily job from design-doc.md Section 7 is deferred to a follow-up session.
- `mcp-server-agent` scaffold uses Python 3.14 (only version present on the dev machine) instead of the 3.12 pinned in CLAUDE.md — installs were clean (mcp, psycopg2-binary, anthropic, pydantic, langgraph all had 3.14 wheels), so no blocker yet, but worth pinning down to 3.12 via pyenv/similar if a 3.12-only dependency shows up later.
- Scaffold uses stdlib `venv` + `pip`/`requirements.txt` instead of `uv`/`poetry` (CLAUDE.md's stated convention) — neither tool was installed on the dev machine. Switch is easy later (`uv pip install -r requirements.txt` or `poetry init` off the existing lock) if desired.
- `shared/config.py`'s `load_dotenv()` was cwd-relative (the default), which silently found nothing when Claude Desktop spawned `mcp_server`/`agent_worker` (it doesn't reliably set `cwd` to the repo root — same quirk noted in Week 3-4's entry above for `PYTHONPATH`). Reproduced directly (spawned with `cwd` outside the repo — `ANTHROPIC_API_KEY` came back empty while DB settings looked fine only because their hardcoded defaults happen to match real dev values) and fixed by resolving `.env` via an absolute path next to `shared/`, independent of the caller's working directory.
- `agent_worker/server.py`'s `run_watchlist_import` and `mcp_server/server.py`'s `get_top_momentum_with_commentary` both now check for a missing `ANTHROPIC_API_KEY` up front and catch Claude API failures (`shared/llm_errors.py`), returning `{"status": "failed", "error": "..."}` instead of letting an exception surface to the MCP caller as a bare "Error executing tool" with no detail. Verified directly with the key still empty — both return the actionable message rather than raising.
- `shared/llm_errors.py`'s `describe_llm_error` needed a `_unwrap()` step — the MCP SDK's `ClientSession`/`stdio_client` use `anyio` TaskGroups internally, which wrap any exception raised inside them in a `BaseExceptionGroup` (sometimes nested), so a plain `isinstance(exc, anthropic.XError)` check never matched anything and always fell through to a useless `"ExceptionGroup: unhandled errors..."` string. Fixed by walking `.exceptions` down to the real leaf exception before classifying it; reproduced and confirmed both before and after the fix via a direct `run_watchlist_import` call.
- A valid `ANTHROPIC_API_KEY` alone wasn't enough — the account had no credit balance, which the Claude API reports as a 400 `invalid_request_error`, not a 401. Distinct from every other failure mode handled in `shared/llm_errors.py`; fixed by adding billing at console.anthropic.com, not a code change. `resolve`'s live call (`agent_worker/watchlist_import.py`) is now confirmed genuinely working end-to-end — see Week 5-6.
