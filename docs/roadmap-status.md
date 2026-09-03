# Roadmap Status — core-api

> Update this file at the end of each Claude Code session. Keep entries short — this is a status board, not a journal. See @CLAUDE.md and @docs/design-doc.md Section 11 for the full 8-week plan this tracks against.

**Last updated:** 2026-08-27
**Current week:** 3

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
- [x] `get_top_momentum_with_commentary` (`mcp_server/server.py`, backed by `agent_worker/momentum_synthesis.py`): tier-2 slice on top of `get_top_momentum` — a single structured Claude API call (`client.messages.parse`, Pydantic `MomentumCommentaryBatch` output, per CLAUDE.md's "validate all agent outputs against Pydantic schemas") that adds a headline + 1-2 sentence rationale per already-ranked stock. Deliberately does NOT re-rank or filter — that stays in the deterministic `get_top_momentum` tier. Uses `settings.llm_model_dev` (Haiku) per the design doc's dev/prod model routing. Validated the code path (ranking → prompt construction → API call) end-to-end; the actual LLM call itself is untested live since `ANTHROPIC_API_KEY` in `.env` is still empty — set a real key to validate that last piece.
- [ ] Simple LLM client (Claude API) connecting to MCP server
- [x] Full loop validated: MCP client → tool call → structured response (validated directly; natural-language-driven client not yet built)

## Week 5–6 — Agentic Analysis Layer (mcp-server-agent repo)

- [ ] Multi-agent system in LangGraph: Momentum, Value, Sentiment, Synthesis agents
- [ ] Session memory via LangGraph checkpointers
- [ ] Pydantic-validated structured outputs across agent boundaries

## Week 7–8 — Observability, Reliability & Polish (Core API's slice)

- [ ] Scale-testing exercise: Core API load test (k6/Locust)
- [ ] Final review against design-doc.md for drift

**Deviations from design doc:** _(none yet)_

---

## Open issues / blockers

_(none yet)_

## Decisions made during build (not yet reflected in design-doc.md)

- `price_timeseries.interval` renamed to `bar_interval` in the actual schema — `INTERVAL` is a reserved word in H2 (used for `ddl-auto: validate`/schema generation under the `test` profile) and the unquoted DDL fails there. Reflected in design-doc.md Section 4.
- Sync is currently exposed only as `POST /api/marketdata/sync?full={bool}` (manual/API trigger); the `@Scheduled` daily job from design-doc.md Section 7 is deferred to a follow-up session.
- `mcp-server-agent` scaffold uses Python 3.14 (only version present on the dev machine) instead of the 3.12 pinned in CLAUDE.md — installs were clean (mcp, psycopg2-binary, anthropic, pydantic, langgraph all had 3.14 wheels), so no blocker yet, but worth pinning down to 3.12 via pyenv/similar if a 3.12-only dependency shows up later.
- Scaffold uses stdlib `venv` + `pip`/`requirements.txt` instead of `uv`/`poetry` (CLAUDE.md's stated convention) — neither tool was installed on the dev machine. Switch is easy later (`uv pip install -r requirements.txt` or `poetry init` off the existing lock) if desired.
