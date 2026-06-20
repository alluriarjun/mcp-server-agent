# Stock Portfolio & Agentic Analysis Service — Design & Requirements Document

| | |
|---|---|
| **Document Type** | Design / Requirements Specification |
| **Target Scope (Phase 1)** | US Stock Market Only |
| **Estimated Timeline** | 8 Weeks (2 Months) |
| **Estimated Cost** | $15–35 (LLM API usage only) |
| **Status** | Draft v1.1 |
| **Repos** | `core-api` (Java/Spring Boot), `mcp-server-agent` (Python) — see [Section 3.4](#34-why-different-languages-per-service) |

> This file is the canonical design reference for this project. It is intended to be copied (or kept as a submodule) into both `core-api` and `mcp-server-agent`, and imported into each repo's `CLAUDE.md` via `@docs/design-doc.md` so Claude Code, the IntelliJ Claude Code plugin, and Cowork all read the same source of truth.

---

## Table of Contents

1. [Overview & Goals](#1-overview--goals)
2. [Functional Requirements](#2-functional-requirements)
3. [System Architecture](#3-system-architecture)
4. [Domain Model & Database Schema](#4-domain-model--database-schema)
5. [Extensibility Design](#5-extensibility-design)
6. [Technology Stack](#6-technology-stack)
7. [Data Sync Strategy](#7-data-sync-strategy)
8. [Agentic / MCP / LLM Layer](#8-agentic--mcp--llm-layer)
9. [UI Requirements](#9-ui-requirements)
10. [Cloud Hosting & Scale Testing](#10-cloud-hosting--scale-testing)
11. [8-Week Implementation Roadmap](#11-8-week-implementation-roadmap)
12. [Cost Estimate](#12-cost-estimate-phase-1-us-stocks-only)
13. [Open Questions / Future Phases](#13-open-questions--future-phases)
14. [Software Licensing & Legal Compliance](#14-software-licensing--legal-compliance)
15. [Appendix A: Design Discussion & Clarifications](#appendix-a-design-discussion--clarifications)

---

## 1. Overview & Goals

### 1.1 Purpose

This document defines the design and requirements for a stock portfolio and watchlist tracking service, layered with an agentic AI analysis system. The project serves a dual purpose: deliver a genuinely useful personal finance tool, and serve as a structured, hands-on vehicle to build production-relevant experience with agentic AI systems, the Model Context Protocol (MCP), LLM orchestration, and system observability — targeted at a backend engineer with 11 years of experience moving into AI/agentic engineering.

### 1.2 Learning Objectives

| Area | What This Project Teaches |
|---|---|
| MCP (Model Context Protocol) | Building a standalone MCP server, defining tool schemas, and connecting LLM clients to it — the emerging standard interface for agent-tool integration. |
| Agent Orchestration | Multi-agent systems with LangGraph (Python): state machines, conditional routing, memory/persistence, structured outputs. |
| LLM Engineering | Prompt design, structured output validation, cost/latency tradeoffs, model routing (cheap vs. capable models). |
| Observability for Non-Deterministic Systems | Tracing, evaluation harnesses, and cost tracking using Langfuse — concerns that don't exist in traditional deterministic backend systems. |
| Reliability Patterns | Retries, fallback models, guardrails, structured output validation, prompt injection defenses. |
| System Design at Senior Level | Service boundaries, extensibility, cloud portability, and scale-testing strategy specific to LLM-agent workloads. |

### 1.3 Functional Scope (Phase 1)

**[PHASE 1]** Phase 1 is explicitly scoped to the **US stock market only** (NYSE/NASDAQ), to minimize external integration friction and keep cost near-zero. India exchange support (NSE/BSE) is a defined future extension ([Section 13](#13-open-questions--future-phases)) enabled by the provider abstraction in [Section 5](#5-extensibility-design).

> **Design principle:** The core CRUD/data layer (auth, portfolio, watchlist, price sync) is necessary plumbing, not the primary learning target. The roadmap intentionally minimizes time spent here so the majority of the 8 weeks goes toward the MCP server, agent orchestration, and observability layers.

---

## 2. Functional Requirements

### 2.1 User Management

- Users can sign up and log in (email/password or third-party auth provider).
- Session management via JWT-based authentication.
- Each user has an isolated watchlist and portfolio.

### 2.2 Watchlist & Portfolio

- A user can create **multiple, independently named watchlists** (e.g., "Tech Growth", "Earnings This Week") and add any US-listed stock to one or more of them (observe only, no quantity).
- A user can create **multiple, independently named portfolios** (e.g., "Retirement", "Trading Account") and add holdings to a portfolio with quantity, average buy price, and buy date.
- Portfolio supports multiple transactions per holding (buy/sell history), not just a current snapshot — this enables future P&L and performance analytics.
- Users can rename or delete a watchlist/portfolio, and remove individual stocks from either.

### 2.3 Market Data & Timeseries

- For any stock in a user's watchlist or portfolio, the user can view historical price timeseries (OHLCV).
- Supported view timeframes: 1D, 1W, 1M, 3M, 1Y, 5Y (aggregated from daily-granularity stored data).
- Data sourced from US exchanges (NYSE/NASDAQ) via a pluggable data provider abstraction.

### 2.5 Real-Time Current Value (Display-Only)

- Every watchlist and portfolio view additionally shows the stock's **current/live price** alongside the stored historical data.
- This value is fetched live, on-demand, at request time from the real-time data provider ([Section 6](#6-technology-stack)) — it is **not persisted** to `price_timeseries` or any other table.
- For portfolio views, the live price is used to compute an ephemeral, in-response "current market value" and unrealized gain/loss (quantity × live price, compared to average buy price) — this calculation happens at response time and is not stored.
- This is a deliberately separate code path from the daily batch sync ([Section 7](#7-data-sync-strategy)): the daily sync writes to the database for historical charting; the live-quote path reads through to an external API on every request and returns directly to the caller.
- Short-lived caching (e.g., Redis, 10–15 second TTL) is recommended in front of the live-quote provider to avoid hitting rate limits when multiple users view the same popular symbol concurrently — the cached value is still never written to permanent storage.

### 2.6 Agentic Analysis `[PHASE 1 EXTENSION]`

- On-demand or scheduled AI-driven analysis of a stock or portfolio (technical indicators + news sentiment + synthesis).
- Structured, validated output (not freeform text) stored alongside timeseries data.
- Full traceability of every agent run (inputs, tool calls, outputs, cost, latency).

---

## 3. System Architecture

### 3.1 Service Decomposition

The system is deliberately designed as a **modular monolith with 2–3 separate deployable processes**, rather than a full microservices architecture. Full microservices decomposition (separate auth service, separate watchlist service, separate notification service, etc.) is considered premature for this scope — it adds service-discovery and inter-service-auth overhead without teaching anything new, at the cost of the 8-week timeline.

**Language/platform is chosen per service**, not fixed project-wide. Core API is the one service that's deliberately Java/Spring Boot — it's the user-facing backend, and the goal there is applying existing backend depth. The MCP Server and Agent Worker are chosen on their own merits (community support, ecosystem maturity, fit for the specific job), since that's where the new learning is concentrated and the Python AI/agent ecosystem is meaningfully more mature. See [Section 3.4](#34-why-different-languages-per-service) for the reasoning behind each choice.

| Service | Language/Platform | Repo | Responsibility |
|---|---|---|---|
| **Core API Service** | Java / Spring Boot | `core-api` | Auth, watchlist/portfolio CRUD, market data provider abstraction, REST API layer. Internally separated into clean packages: `auth`, `portfolio`, `watchlist`, `marketdata`. |
| **MCP Server** | Python (official MCP SDK) | `mcp-server-agent` | Exposes market data and portfolio data as MCP **read** tools (`get_quote`, `get_timeseries`, `get_user_watchlists`, `get_user_portfolios`) and MCP **write** tools (`save_analysis_finding`, `create_alert`) for any LLM client to consume. Must run independently — this is the architectural boundary being learned. It is the *only* path the Agent Worker uses to read or write data — the Agent Worker never calls the Core API directly. |
| **Agent Worker** | Python / LangGraph | `mcp-server-agent` | Multi-agent analysis system. Connects to the MCP Server as an MCP client for all reads and writes (e.g., persisting a momentum finding). Triggered on-demand or via scheduler. Has no direct dependency on the Core API. |
| **Background Sync Worker** | Java / Spring `@Scheduled` | `core-api` | Once-daily job to pull and store OHLCV data for all tracked symbols, written via the Core API's own database access — deliberately co-located with Core API rather than the MCP Server, since this data feeds the REST/UI layer's `price_timeseries` table directly. |

### 3.2 Architecture Diagram

```
┌─────────────────┐
│  Frontend (SPA) │
└────────┬─────────┘
         │
┌────────▼─────────┐                ┌──────────────────┐
│  Core API        │                │  Agent Worker     │
│  (Java /         │                │  (Python /        │
│   Spring Boot)   │                │   LangGraph)      │
│  - auth          │                └─────────┬─────────┘
│  - portfolios    │                          │ (MCP client — reads AND writes)
│  - watchlists    │                ┌─────────▼─────────┐
│  - marketdata    │                │   MCP Server       │
└────────┬─────────┘                │   (Python /        │
         │                          │    official MCP SDK)│
         │                          └─────────┬─────────┘
         │  (direct DB access,                │  (direct DB access,
         │   no MCP — REST layer              │   data-access layer
         │   has no LLM involved)             │   for the agent side)
         │                                    │
    ┌────▼────────────────────────────────────▼────┐
    │   PostgreSQL + TimescaleDB                    │
    │   Redis (cache + scheduler/queue support)     │
    └──────────────────────┬─────────────────────────┘
                            │ DB write event (e.g. new finding row)
                  ┌─────────▼─────────┐
                  │ Notification       │
                  │ Service (future)   │
                  │ - delivery prefs   │
                  │ - rate limiting    │
                  │ - email/Slack/push │
                  └─────────────────────┘

+ Spring @Scheduled job (price sync, runs daily) — Java, same codebase as Core API
+ Langfuse (external/cloud SDK call from Agent Worker) — observability
```

> **NOTE:** Agent Worker talks ONLY to the MCP Server — never directly to the Core API. Core API and MCP Server are independent consumers of the same database; they do not call each other. Core API (Java, repo `core-api`) and MCP Server/Agent Worker (Python, repo `mcp-server-agent`) are **separate git repositories** by design — see [Section 3.4](#34-why-different-languages-per-service).

### 3.3 Design Rationale

- **Core API** stays a monolith because auth/CRUD/data-modeling is standard backend work with no benefit from network-boundary separation at this scale.
- **MCP Server** is separated because it must genuinely act as a standalone tool-provider that any LLM client can connect to — this is the specific pattern being learned. It exposes both read and write tools, since the agent needs to persist findings (e.g., a detected momentum signal), not just fetch data.
- **Agent Worker connects only to the MCP Server, never to the Core API.** Giving the same consumer two different paths into the same data (direct REST calls and MCP tool calls) would defeat the purpose of using MCP as the standard interface boundary. The Core API and MCP Server are independent consumers of the same database — they don't call each other.
- **Agent Worker** is separated because it has different scaling and failure characteristics: long-running, externally rate-limited (LLM API), independent retry/failure semantics, distinct resource profile (LLM token cost vs. DB query cost).
- **Notification dispatch is intentionally not an agent responsibility.** The agent's job ends at writing a structured finding via an MCP write tool (e.g., `save_analysis_finding`). A separate Notification Service reacts to that write (via the event bus, [Section 5.2](#5-extensibility-design)) and owns delivery concerns — channel (email/Slack/push), per-user preferences, and rate-limiting so users aren't spammed. This keeps delivery logic in one place instead of duplicated across agent prompts/tools.

### 3.4 Why Different Languages Per Service

This is a deliberate polyglot design, not an inconsistency. Each service's language was chosen on its own merits rather than defaulting to one stack project-wide:

| Service | Choice | Why |
|---|---|---|
| Core API | Java / Spring Boot | This is the user-facing backend — auth, CRUD, REST API design. The explicit goal here is applying 11 years of existing backend depth to a familiar, production-grade framework, rather than re-learning basic CRUD patterns in a new language. |
| MCP Server | Python (official MCP SDK) | The reference MCP SDK and the overwhelming majority of MCP tooling, examples, and community debugging resources are Python-first. Since this service's entire purpose is to be a clean, standard-compliant tool-provider (not heavy business logic), the ecosystem-maturity argument dominates. |
| Agent Worker | Python / LangGraph | LangGraph is more mature than JVM alternatives specifically for complex multi-agent orchestration (conditional routing, checkpointed state, fan-out/fan-in), with a much larger body of community patterns and examples. The observability/eval tooling referenced throughout this document (Langfuse SDK, eval-harness patterns) is also Python-native, so staying in Python avoids cross-language friction in that layer. |
| Background Sync Worker | Java (co-located with Core API) | This job writes directly into the same `price_timeseries` table that the Core API's REST endpoints read from for charting. Keeping it in the same codebase/process as Core API avoids a cross-language dependency for what is fundamentally "fetch external data, write to our own table." |

> **Practical implication:** `core-api` and `mcp-server-agent` are **two separate git repositories**. They never share code directly — they only interact indirectly, as independent consumers of the same PostgreSQL database, which keeps the language boundary clean rather than smeared across a shared library.

---

## 4. Domain Model & Database Schema

PostgreSQL with the TimescaleDB extension for the timeseries table (hypertable, partitioned by time).

```sql
users (id, email, password_hash, created_at)

stocks (id, symbol, exchange, name, sector, currency, asset_type)
  -- asset_type included for future: equity, crypto, etf, etc.

watchlists (id, user_id, name, created_at)
  -- a user can have multiple named watchlists, e.g. "Tech Growth", "Dividend Picks"

watchlist_items (id, watchlist_id, stock_id, added_at)

portfolios (id, user_id, name, created_at)
  -- a user can have multiple named portfolios, e.g. "Retirement", "Trading Account"

portfolio_holdings (id, portfolio_id, stock_id, quantity, avg_price, currency, created_at)

portfolio_transactions (id, holding_id, type[buy/sell], quantity, price, date)
  -- full history retained, not just current state — enables future P&L analytics

price_timeseries (stock_id, timestamp, open, high, low, close, volume, interval)
  -- TimescaleDB hypertable, partitioned by time
  -- stored at daily granularity; weekly/monthly views computed on read

analysis_findings (id, user_id, portfolio_id NULL, watchlist_id NULL, stock_id,
                    finding_type, summary, details_json, created_at)
  -- written by the Agent Worker via an MCP write tool, e.g. save_analysis_finding
  -- triggers the notification event (Section 8.4)
```

> **Multiple watchlists/portfolios:** watchlists and portfolios are both modeled as named, user-owned collections (many-to-one with `users`), rather than a single implicit list per user. This mirrors how brokerage apps typically let users separate concerns, and requires no schema change later — it's modeled this way from Phase 1.

> **Storage strategy:** Raw OHLCV is stored only at the finest fetched granularity (daily). Weekly/monthly/yearly aggregations are computed on read or via materialized views — storage is not duplicated per timeframe.

---

## 5. Extensibility Design

Extensibility is a first-class design requirement, not an afterthought, so new exchanges, asset classes, and analysis features can be added without core rework.

### 5.1 Plugin-Style Data Provider Abstraction

```
DataProvider (interface)
├── NASDAQProvider / NYSEProvider   (Phase 1)
├── NSEProvider / BSEProvider       (future — India)
└── CryptoProvider / ForexProvider  (future)
```

Each provider implements a common interface: `get_quote()`, `get_timeseries(interval, range)`, `search_symbol()`. Adding a new exchange or asset class means adding a new provider class with no changes to core logic.

### 5.2 Event-Driven Core

An internal event bus (Redis pub/sub, or simple async task dispatch) carries events such as `price_updated` and `watchlist_item_added`. Future features (alerts, notifications, analytics) subscribe to these events rather than requiring changes to core service logic.

### 5.3 Modular Feature Boundaries

| Module | Status |
|---|---|
| `auth_service` | Phase 1 |
| `portfolio_service` | Phase 1 |
| `watchlist_service` | Phase 1 |
| `marketdata_service` | Phase 1 |
| `analytics_service` (agentic analysis) | Phase 1 extension |
| `notification_service` (alerts) | Future |

---

## 6. Technology Stack

Grouped by service/repo, reflecting the polyglot design explained in [Section 3.4](#34-why-different-languages-per-service).

### 6.1 Core API & Background Sync Worker (Java) — repo `core-api`

| Layer | Choice | Notes |
|---|---|---|
| Backend framework | Spring Boot | Spring Web (REST), Spring Data JPA for persistence, Spring Security for auth |
| Database | PostgreSQL + TimescaleDB | Relational fits user/portfolio data; Timescale extension handles timeseries efficiently. See [Section 14](#14-software-licensing--legal-compliance) for licensing. |
| Auth | Spring Security + JWT, or Clerk/Auth0 free tier | Avoid building from scratch if time-constrained |
| Caching / queue | Redis (via Spring Data Redis) | Cache layer for live-quote pass-through (Section 2.5); also backs scheduled-job locking if needed |
| Background jobs | Spring `@Scheduled` (or Quartz for more complex scheduling) | Daily price sync scheduling, co-located with Core API per Section 3.4 |
| End-of-day & historical US market data | Alpha Vantage (officially NASDAQ-licensed; free tier viable for daily EOD sync) | See Section 14 — chosen specifically because it is licensed, not scraped |
| Live/real-time quote (display-only, not persisted) | Finnhub (free-tier real-time/15-min-delayed quotes) | Used only for the on-screen "current value" shown in watchlist/portfolio views (Section 2.5); never written to `price_timeseries` |

### 6.2 MCP Server & Agent Worker (Python) — repo `mcp-server-agent`

| Layer | Choice | Notes |
|---|---|---|
| MCP server/client | Official MCP SDK (Python) | Reference implementation; deepest community support and tooling |
| Agent orchestration | LangGraph | State machines, conditional routing, checkpointed persistence — the most mature option for the multi-agent design in Section 8.2 |
| Structured output validation | Pydantic | Schema-validated agent outputs across agent boundaries (Section 8.2) |
| HTTP/async runtime | FastAPI (for the MCP server's transport layer) / async Python | Standard pairing with the MCP SDK's HTTP transport options |
| LLM | Claude API (Haiku for dev/iteration, Sonnet for production/eval) | Cost-optimized model routing |
| Observability | Langfuse (free cloud tier or self-hosted) | Python-native SDK; tracing, cost tracking, eval harness integration (Section 8.3) |

### 6.3 Frontend & Shared Infrastructure

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js/React | Calls the Core API's REST endpoints directly; language-independent of the backend split |
| Charting | TradingView Lightweight Charts (open-source) or Recharts | Purpose-built for OHLCV/stock data |
| Shared datastore | PostgreSQL + TimescaleDB, Redis | Both `core-api` and `mcp-server-agent` connect to the same database independently (Section 3.4) — no shared application code between them |

---

## 7. Data Sync Strategy

- A scheduled daily job (Spring `@Scheduled`, post-market-close) pulls the latest OHLCV bar for every **distinct** symbol across all users' watchlists/portfolios via Alpha Vantage.
- **Deduplication:** a symbol is fetched once per day regardless of how many users track it — sync iterates over distinct symbols, not per-user.
- **Backfill on first add:** when a user first adds a new stock, a one-time on-demand job pulls historical data (e.g., 5 years) so the timeseries view isn't empty. This is separate from the daily incremental sync.
- All "different timeframe" views (1D–5Y) are served from the application's own database via aggregation queries — **zero external API calls on read**, regardless of read volume.
- Intraday (minute-level) historical storage is explicitly out of scope for Phase 1 — daily granularity is sufficient and keeps usage within free-tier limits.
- Basic retry/backoff logic recommended around all external data-provider calls.
- **Live/real-time display value (not stored):** see Section 2.5 — this is a separate, on-demand call path from the daily batch sync described above.

---

## 8. Agentic / MCP / LLM Layer

### 8.1 MCP Server Design

The MCP Server is a separate Python service that independently implements its own market-data and portfolio/watchlist data access (via the official MCP SDK) against the shared database — it does not call into the Java `marketdata` package. This is the **only** interface the Agent Worker uses — it never calls the Core API directly.

| Tool | Type | Purpose |
|---|---|---|
| `get_quote(symbol)` | Read | Latest price for a symbol (sourced live, same provider as Section 2.5 — not from stored history) |
| `get_timeseries(symbol, interval, range)` | Read | Historical OHLCV data from the database |
| `get_user_watchlists(user_id)` | Read | All of a user's named watchlists and their holdings |
| `get_user_portfolios(user_id)` | Read | All of a user's named portfolios and their holdings |
| `save_analysis_finding(user_id, stock_id, finding_type, summary, details)` | Write | Persists an agent-generated finding (e.g., a momentum signal) to `analysis_findings`. This write is what triggers the notification flow (Section 8.4). |
| `create_alert(user_id, stock_id, condition)` | Write | Lets the agent (or a user-initiated flow) register a standing watch condition for future evaluation |

### 8.2 Multi-Agent Orchestration

Built with LangGraph (Python) as a directed graph of specialized agents:

| Agent | Responsibility |
|---|---|
| Data Gathering Agent | Invokes MCP tools to retrieve price/fundamentals/news |
| Technical Analysis Agent | Computes/interprets indicators (RSI, MACD, etc.) |
| Sentiment Analysis Agent | Analyzes recent news sentiment (conditionally invoked — skipped if no recent news) |
| Report Synthesis Agent | Combines outputs into a structured, validated report |

- Conditional routing (e.g., skip sentiment analysis when no relevant news exists).
- Parallel fan-out/fan-in for analyzing multiple stocks concurrently.
- Session memory/state persistence via LangGraph checkpointers (resumable analysis sessions, follow-up queries like "compare that to last week").
- All outputs validated against Pydantic schemas — no unstructured/freeform critical output.

### 8.3 Observability & Evaluation

- **Tracing:** every LLM call, tool call, and latency point traced via Langfuse from day one.
- **Eval harness:** a dataset of historical stock scenarios with expected analysis quality; automated scoring combining LLM-as-judge with rule-based numerical accuracy checks.
- **Cost tracking:** token usage and dollar cost tracked per request/agent, surfaced on a dashboard.
- **Reliability:** retries with backoff, fallback models (cheap model for simple tasks, escalate on failure), structured-output validation.
- **Security:** prompt-injection sanitization for any untrusted tool result (e.g., news article content) before it reaches the LLM context.

### 8.4 Notification Flow: Agent vs. Notification Service

When an agent detects something worth surfacing to a user — for example, momentum analysis flagging unusual strength on a watched stock — the responsibility is deliberately split:

| Step | Owner | Responsibility |
|---|---|---|
| 1. Detect & analyze | Agent Worker | Runs the analysis (e.g., momentum signal), produces a structured finding |
| 2. Persist finding | Agent Worker → MCP Server | Calls `save_analysis_finding` (Section 8.1); the agent's responsibility ends here |
| 3. React to the write | Event bus (Section 5.2) | A `finding_created` event fires off the database write |
| 4. Deliver | Notification Service `[Phase 1 extension]` | Subscribes to the event; owns delivery channel (email/Slack/push), per-user notification preferences, and rate-limiting |

> **Why not let the agent send notifications directly?** Keeping delivery logic out of the agent keeps its responsibility scoped to analysis, and avoids duplicating channel/preference/rate-limit logic across agent prompts and tools.

---

## 9. UI Requirements

UI scope is intentionally minimal for the 8-week window — visual polish is a separate effort from the system's core learning goals.

- Login / signup
- Create/rename/delete named watchlists and portfolios; add/remove stocks (with quantity for portfolio holdings)
- View timeseries charts across supported timeframes (1D–5Y)
- Each watchlist/portfolio row displays the live current value (Section 2.5) alongside the historical chart — refreshed on view, not stored
- View agent-generated analysis/reports, rendered from structured JSON

> **Recommendation:** a thin Next.js/React SPA calling the Spring Boot REST API directly.

---

## 10. Cloud Hosting & Scale Testing

### 10.1 Cloud Portability

| Component | Local (dev) | Cloud (future) |
|---|---|---|
| Core API | Docker container | Render / Railway / Fly.io / ECS / Cloud Run |
| MCP Server | Docker container | Separate container, same registry |
| Agent Worker | Docker container | Background worker (Render background worker / ECS task) |
| Postgres + TimescaleDB | Docker | Managed Postgres (RDS / Neon / Supabase) |
| Redis | Docker | Managed Redis (Upstash free tier) |
| Frontend | Local dev server | Vercel / Netlify free tier |

Key choices that preserve cloud-portability from day one: environment-variable based configuration (12-factor principles), and containerizing each service individually from the start, even while running locally via docker-compose.

### 10.2 Scale Testing Strategy

- **Core API:** stateless and horizontally scalable; load-test with k6 or Locust against realistic concurrent-user HTTP traffic.
- **Timeseries reads:** TimescaleDB handles read-heavy multi-timeframe queries well; scale-test with concurrent multi-user query patterns.
- **Agent Worker (the differentiated story):** scale testing here is about LLM API rate-limit behavior, concurrency/queueing strategy for parallel agent runs, and cost-per-user-at-scale modeling — not raw throughput.
- **MCP Server:** needs DB connection pooling and caching of frequently-requested tool results under concurrent agent load.

---

## 11. 8-Week Implementation Roadmap

### Weeks 1–2 — Foundation (minimal plumbing)
- Auth (Spring Security + JWT, or a hosted provider)
- Watchlist/portfolio schema and CRUD (multiple named lists per user)
- Alpha Vantage integration end-to-end with daily sync working
- Basic timeseries endpoint — functional over polished
- Live-quote endpoint (Finnhub, Section 2.5) — read-through, not persisted
- Containerize each service from day one (Docker)

### Weeks 3–4 — MCP Server Layer
- Build a standalone Python MCP server (official MCP SDK) implementing its own data access against the shared database, with defined tool schemas (Section 8.1)
- Build a simple LLM client (Claude API) that connects to the MCP server
- Validate full loop: natural-language query → tool call → structured response

### Weeks 5–6 — Agentic Analysis Layer
- Build the multi-agent system (Section 8.2) in LangGraph, sourcing data via the MCP server
- Add session memory/state persistence (LangGraph checkpointers)
- Structured-output validation (Pydantic) across agent boundaries

### Weeks 7–8 — Observability, Reliability & Polish
- Langfuse tracing across all agent runs
- Eval harness: accuracy and hallucination checks against expected indicator values
- Cost tracking, retries, fallback models
- Scheduled daily-digest job; scale-testing exercise (Section 10.2)
- Architecture write-up documenting decisions and tradeoffs

> **Timeline risk:** NSE/India exchange integration is notoriously inconsistent for unofficial sources and is explicitly excluded from Phase 1 to protect this timeline. Do not let exchange integration work expand beyond Weeks 1–2.

---

## 12. Cost Estimate (Phase 1: US Stocks Only)

| Component | Choice | Cost / month |
|---|---|---|
| US end-of-day & historical market data | Alpha Vantage free tier | $0 |
| US live/real-time quote (display-only, Section 2.5) | Finnhub free tier (60 req/min) | $0 |
| LLM API (Claude) | Haiku for dev iteration, Sonnet for eval/final runs | $15–35 total over 2 months |
| Observability | Langfuse free cloud tier (50k observations/mo) | $0 |
| Database / Redis | Local Docker during build phase | $0 |
| Auth | Spring Security + self-issued JWT, or Clerk free tier | $0 |
| Hosting (optional, end-of-project demo) | Render/Railway/Fly.io + Vercel free tiers | $0 |

**Total estimated cost for the full 8-week project: $15–35** (entirely LLM API usage)

> Recommendation: set a hard spend cap (e.g., $40) as a budget alert in the Anthropic console to avoid surprises during iterative agent development.

> **Future India (NSE/BSE) extension cost:** live India market data via Kite Connect (Zerodha) is approximately ₹2,000/month (~$24), requiring an active trading account. Excluded from Phase 1 scope and cost.

---

## 13. Open Questions / Future Phases

| Item | Notes |
|---|---|
| India exchange support (NSE/BSE) | Enabled via the provider abstraction (Section 5.1); requires Kite Connect or equivalent paid API (~$24/mo) |
| Intraday (minute-level) data | Different sync cadence and retention strategy; deferred past Phase 1 |
| Notification / alerting service | Subscribes to the event bus (Section 5.2); e.g., "unusual volume detected" alerts via email/Slack |
| Backtesting agent | Validates past agent predictions against actual outcomes (stretch goal) |
| Human-in-the-loop approval | Approval gate before any user-facing alert is dispatched (stretch goal) |
| Full microservices decomposition | Explicitly deferred — would be a Phase 2 refactor once core system is validated |
| Crypto / Forex asset classes | Supported by the same `DataProvider` interface (Section 5.1) when prioritized |

---

## 14. Software Licensing & Legal Compliance

### 14.1 Open-Source Frameworks & Libraries

| Component | License | Implication |
|---|---|---|
| Spring Boot, Spring Web, Spring Security, Spring Data | Apache 2.0 | Fully permissive — free for commercial use, modification, and distribution (Core API & Background Sync Worker) |
| Official MCP SDK (Python) | MIT | Fully permissive (MCP Server) |
| LangGraph / LangChain (Python) | MIT | Fully permissive (Agent Worker) |
| Pydantic, FastAPI | MIT | Fully permissive |
| PostgreSQL | PostgreSQL License (permissive, similar to MIT/BSD) | No restrictions on commercial use |
| Redis (current OSS releases) | Dual-licensed: RSALv2/SSPL or AGPL depending on version | Self-hosting/internal use unaffected; restriction only applies to offering Redis itself as a managed DB service to third parties. Re-check exact version's license at adoption time. |
| Next.js / React | MIT | Fully permissive |
| TradingView Lightweight Charts | Apache 2.0 | Fully permissive; a different, open-source product from TradingView's commercial charting library — don't conflate the two |

### 14.2 TimescaleDB Licensing (Two-Tier Model)

- **Apache 2 Edition** (core extension): fully open-source, unrestricted.
- **Community Edition** (continuous aggregates, compression, retention policies — used throughout Section 7 and Appendix A.2): Timescale License (TSL). Free for self-managed use, including commercial use; the only restriction is offering TimescaleDB itself as a hosted database service to third parties.

> **Relevance to this project:** self-hosting Community Edition is squarely permitted. Worth verifying that any future managed Postgres provider actually ships Community Edition features before relying on continuous aggregates/compression there.

### 14.3 Market Data Sources — Read Carefully

- **Yahoo Finance / `yfinance` (and unofficial ports):** intended for personal, research, and educational use only per the library's own documentation; **not recommended** for this project once it has other users.
- **Alpha Vantage** (chosen EOD/historical provider): officially licensed by NASDAQ as a US market data provider.
- **Finnhub** (chosen real-time-quote provider): officially maintained API platform with published terms.
- **Kite Connect** (future India data path): Zerodha's official, paid, terms-governed API.

> **Action item before any production/shared-user deployment:** read the current Terms of Service for whichever data provider(s) are actually used — terms can change and vary by pricing tier. This document is not legal advice.

### 14.4 LLM Provider Terms (Anthropic / Claude API)

Governed by Anthropic's standard commercial API terms, which permit building products on top of the API, subject to Anthropic's usage policies (e.g., appropriate disclaimers given this project's financial-analysis domain).

### 14.5 Copyright Note on Generated Analysis Content

Agent-generated findings and news-derived sentiment analysis should summarize/analyze in the system's own structured output rather than reproduce substantial verbatim text from third-party news articles used as input.

### 14.6 Summary

Every component in this stack (Java/Spring Boot, Python/LangGraph/MCP SDK, PostgreSQL/TimescaleDB, Alpha Vantage + Finnhub, Claude API) has a clear, permissive, or properly licensed legal basis for this project's intended use. The one deliberate choice was steering market data sourcing toward officially licensed providers over popular-but-unofficial scrapers.

---

## Appendix A: Design Discussion & Clarifications

### A.1 Would TimescaleDB hold up at 30-second granularity, 5 years, millions of users?

**Row volume is driven by symbols tracked, not user count.** Users overlap heavily on popular symbols — one timeseries per symbol regardless of watcher count.

- 30-second bars during US market hours (6.5 hrs/day) ≈ 780 bars/day ≈ 196,560 bars/year per symbol
- Over 5 years: ≈983,000 rows per symbol
- Across ≈8,000 NYSE/NASDAQ symbols: ≈7.9 billion rows total

This is within TimescaleDB's design envelope provided three practices are used: **compression** (90%+ reduction on OHLCV data), **continuous aggregates** (pre-computed rollups so timeframe queries never scan raw rows), and **chunk retention/tiering** (older raw data compressed more aggressively or tiered to cheap storage).

> **The actual bottleneck isn't storage — it's data sourcing and ingestion.** 30-second granularity across thousands of symbols requires a streaming/near-real-time feed (Polygon.io, IEX Cloud paid tiers), well beyond Alpha Vantage's free tier. Real recurring cost: often $200–$2,000+/month.

**Conclusion:** daily granularity (Phase 1 scope) is the right build target now. 30-second granularity is an achievable future extension, not a re-architecture.

### A.2 Are continuous aggregates (materialized hypertables) automatically generated?

Partially: the *definition* is a one-time manual step; the ongoing *refresh* is automatic once configured.

```sql
-- Step 1 — define the aggregate (manual, one-time per rollup level)
CREATE MATERIALIZED VIEW price_daily
WITH (timescaledb.continuous) AS
SELECT
  stock_id,
  time_bucket('1 day', timestamp) AS bucket,
  first(open, timestamp) AS open,
  max(high) AS high,
  min(low) AS low,
  last(close, timestamp) AS close,
  sum(volume) AS volume
FROM price_timeseries
GROUP BY stock_id, bucket;

-- Step 2 — attach a refresh policy (automatic from then on)
SELECT add_continuous_aggregate_policy('price_daily',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');
```

Once the policy is attached, a Timescale background worker refreshes incrementally on schedule — no manual intervention. A new rollup level (e.g., hourly) requires its own `CREATE MATERIALIZED VIEW` + policy.

### A.3 Can a single `analysis_findings` table hold different analysis types (momentum, value, sentiment, etc.)?

Yes — one table, a type discriminator column, and a JSONB payload for type-specific fields (already reflected in [Section 4](#4-domain-model--database-schema)).

```sql
CREATE INDEX idx_findings_type_stock ON analysis_findings (finding_type, stock_id, created_at DESC);
CREATE INDEX idx_findings_user_type ON analysis_findings (user_id, finding_type, created_at DESC);
```

JSONB avoids a sparse, ever-growing column set while still supporting indexed queries into specific keys (via a `GIN` index) if a query pattern later requires it. `analysis_findings` is structured event/log data, not OHLCV-style timeseries — it stays a regular PostgreSQL table, not a TimescaleDB hypertable.
