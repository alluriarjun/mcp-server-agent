# Roadmap Status — mcp-server-agent

> Update this file at the end of each Claude Code session. Keep entries short — this is a status board, not a journal. See @CLAUDE.md and @docs/design-doc.md Section 11 for the full 8-week plan this tracks against.

**Last updated:** _(fill in date)_
**Current week:** _(1–8)_

---

## Week 3–4 — MCP Server Layer

- [ ] MCP server scaffolded (official MCP SDK)
- [ ] `get_quote` tool
- [ ] `get_timeseries` tool
- [ ] `get_user_watchlists` tool
- [ ] `get_user_portfolios` tool
- [ ] `save_analysis_finding` tool (write)
- [ ] `create_alert` tool (write)
- [ ] Simple LLM client validates full loop: query → tool call → structured response

**Deviations from design doc:** _(none yet)_

## Week 5–6 — Agentic Analysis Layer

- [ ] Data Gathering Agent
- [ ] Technical Analysis Agent
- [ ] Sentiment Analysis Agent (conditional routing)
- [ ] Report Synthesis Agent
- [ ] LangGraph checkpointer / session memory
- [ ] Pydantic validation across agent boundaries

**Deviations from design doc:** _(none yet)_

## Week 7–8 — Observability, Reliability & Polish (Agent side)

- [ ] Langfuse tracing wired up
- [ ] Eval harness (accuracy + hallucination checks)
- [ ] Cost tracking dashboard
- [ ] Retries / fallback models
- [ ] Scale-testing exercise: agent concurrency + LLM rate-limit behavior

**Deviations from design doc:** _(none yet)_

---

## Open issues / blockers

_(none yet)_

## Decisions made during build (not yet reflected in design-doc.md)

_(none yet — if something changes here, update design-doc.md too so it stays canonical)_
