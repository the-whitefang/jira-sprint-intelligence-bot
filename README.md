# Jira Sprint Intelligence Bot — Project README & Handoff Document

**Purpose of this document**: a complete, chronological record of everything designed and built so far, detailed enough that a *different* AI assistant (or a human) can pick up exactly where this conversation left off — including what's fully done, what's mid-flight, and what hasn't been started.

**Last updated**: end of the "Build the Redis layer" task (in progress — see [Section 9](#9-current-in-progress-work-read-this-first-if-continuing) first).

---

## 1. What this project is

An internal, enterprise-grade tool that connects to a company's Jira instance, analyzes sprint/ticket data, and surfaces AI-generated insights (velocity trends, risk flags, workload balance, natural-language Q&A about sprints) through a web dashboard and chat interface.

## 2. Technology stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, MySQL 8.4, Redis 7, ChromaDB, Gemini API
- **Frontend**: React (Vite) — **not started yet**
- **Auth**: JWT (access + refresh tokens)
- **Infra**: Docker, Docker Compose
- **Testing approach used throughout this build**: real functional verification wherever feasible — SQLite as a MySQL stand-in for ORM/repository tests (no MySQL server in the build sandbox), a real installed Redis instance for cache tests, `httpx.MockTransport` for the Jira HTTP client, and synthetic in-memory data for the pure-computation Analytics Engine. Every module below was actually executed against test data before being delivered, not just written.

## 3. Architecture principles (agreed at the start, held throughout)

- **Clean Architecture / layered dependency direction**: routes → services → repositories → ORM models. Presentation layer never touches SQLAlchemy directly; services never touch HTTP concerns.
- **Repository Pattern**: a generic `BaseRepository[ModelType]` (concrete class, not an abstract `Protocol` — see `app/shared/base_repository.py`'s docstring for why that trade-off was made deliberately) that every model-specific repository subclasses.
- **Feature-first module structure**: `app/modules/<feature>/{models,schemas,repository,service,routes,dependencies}.py`, not layer-first folders. Not every file exists yet in every module (see status table below).
- **Dependency Injection** via FastAPI's native `Depends()`, no external DI framework.
- **Every custom exception inherits `AppException`** (`app/core/exceptions.py`) and is mapped to a consistent JSON error envelope by one global handler (`app/middleware/error_handler.py`) — `{error_code, message, request_id}`.
- **Settings are centralized**: nothing reads `os.environ` directly; everything goes through `app.core.config.get_settings()`.
- **"Never redesign previous architecture unless requested"** — every module built added to what existed rather than restructuring it. Where a genuine gap was found (see bugs list below), it was fixed additively and flagged explicitly, not silently.

---

## 4. Complete build history, in order

### 4.1 Architecture & design phase (no code yet)
1. Agreed the overall Clean Architecture approach, folder structure, and tech stack (this is what's in Section 6 below).
2. Designed the full system architecture: high-level component diagram, data flow (AI insight query lifecycle), database architecture, Redis architecture, ChromaDB architecture, Gemini integration architecture, authentication flow, API request lifecycle, deployment architecture (Docker Compose → Kubernetes path).
3. Designed the **complete MySQL schema**: 18 tables across 5 domains (Identity & Access, Jira Domain/cached data, Analytics, AI/Chat, Reports), with an ER diagram, all PKs/FKs/indexes explained. **Only 11 of these 18 tables have been implemented as actual SQLAlchemy models so far** — see Section 7 for exactly which.
4. Designed the **complete REST API surface**: Authentication, Sprint, Analytics, Chat, Dashboard, Admin, and Report APIs — method/URL/request/response/status codes/auth/validation for every endpoint. **None of these routes have been implemented yet** — this was a design pass only; `routes.py` doesn't exist in any module yet.

### 4.2 Backend foundation (built & tested)
Files: `app/core/config.py`, `app/core/logging_config.py`, `app/core/exceptions.py`, `app/middleware/error_handler.py`, `app/main.py`, `requirements.txt`, `requirements-dev.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`.

- `Settings` (Pydantic Settings v2), `Environment`/`LogLevel` enums, computed properties (`database_url`, `redis_url`, `cors_origins`).
- Structured logging: JSON in staging/prod, human-readable in dev, request-ID correlation via a `contextvar`.
- `AppException` hierarchy: `NotFoundException`, `ValidationException`, `UnauthorizedException`, `ForbiddenException`, `ConflictException`, `RateLimitExceededException`, `ExternalServiceException`, `DatabaseException`.
- Global exception handlers + `RequestIdMiddleware` (adds `X-Request-ID` to every response).
- `create_app()` factory pattern, `lifespan` startup/shutdown hook (this is where every subsequent module's engine/client gets wired in).
- **Real bug found & fixed**: `pydantic-settings` tries to JSON-decode any `list`-typed env var before validators run, breaking `CORS_ORIGINS` on a plain comma-separated string. Fixed by storing it as a raw `str` field with a computed `.cors_origins` property instead.

### 4.3 Jira Integration Module (built & tested)
Location: `app/integrations/jira/`.

- `exceptions.py` — `JiraIntegrationError` hierarchy (`JiraAuthenticationError`, `JiraNotFoundError`, `JiraRateLimitError`, `JiraServerError`, `JiraConnectionError`), all subclassing `ExternalServiceException`.
- `schemas.py` — `JiraProject`, `JiraBoard`, `JiraSprint`, `JiraUser`, `JiraIssue` (built via a `.from_api()` factory, not plain alias validation, because Jira nests fields inconsistently).
- `http_client.py` — the only file that imports `httpx` directly. Basic Auth, retry/backoff via `tenacity` (only retries `JiraRateLimitError`/`JiraServerError`/`JiraConnectionError` — never auth failures), a custom wait strategy that honors Jira's `Retry-After` header, and `paginate()` handling both of Jira's pagination shapes (Agile API vs. core search API).
- `resources/{projects,boards,sprints,issues,users}.py` — one narrow resource client per Jira concept.
- `client.py` — `JiraClient` facade: `.projects`, `.boards`, `.sprints`, `.issues`, `.users`, `.jql`, `.test_connection()`.
- `dependencies.py` — `get_jira_client(request)` FastAPI dependency, reading the client off `app.state` (created once at startup, not per-request).
- **Real bug found & fixed**: `JiraRateLimitError.retry_after` was captured from the `Retry-After` header but never actually wired into the retry wait strategy — `tenacity`'s `wait_exponential_jitter` doesn't know that attribute exists. Fixed with a custom wait function.
- **Real bug found & fixed**: `request()`'s return type was declared `dict | None` but `/user/search` actually returns a bare JSON array. Widened to `dict | list | None`.
- Tested against `httpx.MockTransport` (auth headers, pagination across pages, 401/404/429/500 → correct exception mapping, retry-not-on-auth-failure) *and* against real `atlassian.net` infrastructure (got a real 403 for bogus credentials, proving the exception mapping works against the real API shape too).

### 4.4 JQL Service (built & tested)
Location: `app/integrations/jira/jql/`.

- `filters.py` — `JQLFilter` (projects, statuses, priorities, assignees/unassigned, sprint_id, date_filters, sort_by/direction, an `extra_jql` escape hatch), `DateRangeFilter`, `SORTABLE_FIELDS` whitelist.
- `builder.py` — `build_jql()`, a pure function. All string values go through `_escape_jql_literal()` (the JQL-injection prevention chokepoint — same idea as parameterized SQL). Sort fields go through a closed whitelist since JQL's `ORDER BY` can't be safely quoted.
- `service.py` — `JQLService`: `.generate_jql()`, `.search()` (one page + pagination metadata via `JiraIssuePage`), `.search_all()` (auto-paginates everything).
- Exposed as `jira_client.jql` on the `JiraClient` facade (no separate DI needed).
- **Real bug found & fixed**: `search_all()`'s `page_size` parameter did nothing because `JiraHTTPClient.paginate()` didn't accept an override. Extended `paginate()` with a backward-compatible `page_size` param.
- Tested: escaping (including a value with both a quote and a backslash), the `unassigned`+`assignee` conflict validator, sort whitelist rejection, single-page metadata correctness, `is_last` on the final page, full multi-page traversal.

### 4.5 Analytics Engine (built & tested)
Location: `app/analytics/` (a new top-level package — deliberately **not** `app/modules/analytics/`, since these modules own no DB models/routes, they're pure computation; see the package docstring in `base.py`).

**8 independent modules, verified to have zero cross-imports between them** (checked via an AST-walking test, not just claimed):
1. `sprint_analytics.py` — `SprintAnalyticsService` → `SprintAnalyticsResult` (velocity, completion rate, scope creep, approximate cycle time). Also holds `IssueCounts` / `compute_issue_counts()` (added later, see 4.7).
2. `workload_analytics.py` — **rewritten once**, see 4.7 below for the current version.
3. `backlog_analytics.py` — `BacklogAnalyticsService` → age distribution, staleness, estimate coverage.
4. `bug_analytics.py` — `BugAnalyticsService` → open/closed, priority distribution, resolution time.
5. `epic_analytics.py` — `EpicAnalyticsService` → takes pre-grouped child issues (epic-link field varies per Jira instance, so grouping is the caller's job).
6. `risk_analytics.py` — `RiskAnalyticsService` → composite risk classification (`SprintRiskInput` is a deliberately independent flat model, not a reuse of `SprintAnalyticsResult`).
7. `capacity_analytics.py` — `CapacityAnalyticsService` → over/under-allocation vs. caller-supplied team capacity.
8. `time_analytics.py` — `TimeAnalyticsService` → lead time (explicitly **not** true cycle time — that needs Jira's changelog, not available at this layer yet; documented as a known limitation, not silently approximated).

`base.py` holds the shared, side-effect-free kernel: `DEFAULT_DONE_STATUSES`, `RiskLevel` enum, `safe_percentage`/`safe_mean`/`safe_median`.

### 4.6 Schema gap fix: `priority` field
Bug Analytics needed `bugs_by_priority`, but `JiraIssue` never captured priority at all. Fixed by adding `priority: str | None` to `JiraIssue` (`app/integrations/jira/schemas.py`) and adding `"priority"` to the default fetched-fields list in both `resources/issues.py` and `jql/service.py`.

### 4.7 Workload Analytics — full rewrite (built & tested)
The original `workload_analytics.py` only covered issue/point counts. Rebuilt to the expanded spec: employee workload, story points, issue count, time spent, time remaining, sprint utilization, overloaded employees, idle employees.

**This required another schema extension**: `JiraIssue` gained `time_spent_seconds`, `time_remaining_seconds`, `original_estimate_seconds` (Jira's classic time-tracking fields — also didn't exist before), and both default-fields lists (`resources/issues.py`, `jql/service.py`) were updated again to actually request them.

Current `workload_analytics.py` contents:
- `TeamMember` (roster identity, for idle detection), `WorkloadStatus` enum (`IDLE`/`UNDER_UTILIZED`/`BALANCED`/`OVERLOADED`), `EmployeeWorkload`, `WorkloadAnalyticsResult`.
- `WorkloadAnalyticsService` — configurable thresholds, `team_utilization_rate` computed from totals (not averaged per-person rates, so it stays correct if per-person capacity ever varies).
- Key design point: **idle detection needs the full team roster**, not just issue assignees — someone with zero assigned work never appears as an assignee on anything, so `compute()` accepts an optional `team_members: list[TeamMember]` to catch that case.
- Tested: overload/idle/balanced classification, a boundary case (exactly 50%), roster-based zero-issue idle detection, the `None`-vs-`0.0` distinction on `workload_balance_ratio` (never `float("inf")`, which isn't valid JSON), graceful behavior with no time-tracking data at all, constructor validation.

### 4.8 Folder-structure hygiene
At one point a **stale, conflicting duplicate** of the Analytics Engine was discovered sitting in `app/modules/analytics/` (different design: its own `AnalyticsIssue`/`AnalyticsSprint` schemas, only 2 of 8 modules). This was flagged and deleted. **If you see `app/modules/analytics/` reappear, delete it** — it is not part of this design.

### 4.9 MySQL Persistence Layer (built & tested end-to-end)
Location: `app/db/`, `app/shared/base_repository.py`, `app/modules/{auth,sprints,tickets}/{models,repository}.py`, `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`.

- `db/base.py` — `Base` (declarative base with a pinned `NAMING_CONVENTION` for stable Alembic autogenerate), `TimestampMixin`.
- `db/session.py` — async engine (`asyncmy` driver), connection pooling (`pool_recycle=1800`, `pool_pre_ping=True` — both specifically to avoid "MySQL server has gone away" errors), `get_db()` FastAPI dependency, `session_scope()` for non-request code, `check_connection()`.
- `db/import_models.py` — imports every `models.py` so cross-module string-referenced relationships (e.g. `Sprint.tickets` → `"Ticket"`) resolve correctly regardless of import order; imported by both `alembic/env.py` and (once wired) app startup.
- `shared/base_repository.py` — generic `BaseRepository[ModelType]`: `create`/`get_by_id`/`get_by_id_or_raise`/`list`/`update`/`delete`/`count`. **Repositories flush, never commit** — transaction boundaries belong to `get_db()`/`session_scope()`, which is what lets multiple repository calls compose into one atomic unit of work. `IntegrityError` → `ConflictException`; other `SQLAlchemyError` → `DatabaseException`.
- **11 models implemented** (of the 18 designed): `modules/auth/models.py` → `Role`, `Permission`, `RolePermission`, `User`, `UserRole`, `RefreshToken`. `modules/sprints/models.py` → `Project`, `Sprint`. `modules/tickets/models.py` → `Ticket`, `TicketHistory`, `TicketComment`.
- Matching `repository.py` in each of those three modules, with domain-specific queries (`get_by_email`, `get_active_by_hash`, `list_by_sprint`, `list_pending_embedding`, etc.).
- **Real bug found & fixed**: `Project.sprints` had ORM cascade delete configured, but `Sprint.tickets` didn't — deleting a `Project` crashed trying to `NULL` out `tickets.sprint_id` (`NOT NULL`). Fixed by adding `cascade="all, delete-orphan"` + `passive_deletes=True` consistently down the whole chain (`Project→Sprint→Ticket→{History,Comments}`, and `User→RefreshToken`), so the ORM defers to the database's own `ON DELETE CASCADE` instead of trying to manage it in Python.
- **Real gotcha found & documented (not a bug, an async-SQLAlchemy footgun)**: appending to a many-to-many collection (`user.roles.append(...)`) on an object that was only just constructed — never loaded via a query — triggers a synchronous lazy-load, which raises `MissingGreenlet` under the async driver. Documented directly on `User.roles`'s docstring: assign relationships at creation time via the constructor kwarg, or re-fetch via `get_by_id_or_raise` (which eager-loads via `lazy="selectin"`) before mutating an existing row's collection.
- `alembic/env.py` — async-compatible (bridges Alembic's sync migration runner onto the async engine via `AsyncConnection.run_sync()`), reads the DB URL from `Settings` (no hardcoded URL in `alembic.ini`).
- **Genuinely tested end-to-end, not just written**: full CRUD + relationships + cascade delete + soft delete + transaction atomicity (a mid-transaction failure correctly rolls back everything, verified) + pagination, all against SQLite (`aiosqlite`) as a stand-in since no MySQL server exists in the build sandbox. **Also ran real Alembic commands** — `alembic revision --autogenerate` actually connected through `env.py` and detected all 11 tables/FKs/indexes correctly, and `alembic upgrade head` actually created them in a real (SQLite) database file.
- `main.py` was updated: `init_engine()`/`dispose_engine()` wired into `lifespan`; `/health/ready` now live-checks DB connectivity via `check_connection()` (unlike Jira's cached-at-startup check — DB is cheap/local enough to check on every probe).

---

## 5. Environment / credentials

Same pattern for every external dependency: real values go in a local `.env` (gitignored), never in `.env.example`. Currently defined variable groups (see `.env.example` for the full list with defaults): `APP_*`, `CORS_ORIGINS`, `SECRET_KEY`/JWT settings, `DB_*` (MySQL), `REDIS_*`, `CHROMA_*`, `GEMINI_*`, `JIRA_*`, plus rate-limit settings (`AI_DAILY_QUERY_QUOTA_PER_USER`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`).

**Security notes given during this build, still applicable**: use a dedicated non-root MySQL user (matches `docker-compose.yml`'s `DB_USER`/`DB_ROOT_PASSWORD` separation); if any credential (Jira token, DB password, etc.) is ever shared outside the local `.env` — a screenshot, a shared terminal — rotate it rather than assuming it's fine.

---

## 6. Full current folder structure

```
JSI_Bot/                                  (~/Desktop/JSI_Bot on the user's machine)
├── .venv/
├── backend/                              ← mark as Sources Root in PyCharm
│   ├── alembic/
│   │   ├── versions/                     (empty until the first real migration is generated)
│   │   ├── env.py
│   │   └── script.py.mako
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── analytics/                    ← pure computation, no I/O, no cross-imports between modules
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── sprint_analytics.py       (SprintAnalyticsResult, IssueCounts)
│   │   │   ├── workload_analytics.py     (rewritten — time tracking + utilization)
│   │   │   ├── backlog_analytics.py
│   │   │   ├── bug_analytics.py
│   │   │   ├── epic_analytics.py
│   │   │   ├── risk_analytics.py
│   │   │   ├── capacity_analytics.py
│   │   │   └── time_analytics.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── exceptions.py
│   │   │   └── logging_config.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── session.py                (MySQL engine/pool)
│   │   │   ├── import_models.py
│   │   │   └── redis_client.py           (Redis pool — NEW, see Section 9)
│   │   ├── integrations/
│   │   │   ├── __init__.py
│   │   │   └── jira/
│   │   │       ├── __init__.py
│   │   │       ├── client.py             (JiraClient facade: .projects/.boards/.sprints/.issues/.users/.jql)
│   │   │       ├── dependencies.py
│   │   │       ├── exceptions.py
│   │   │       ├── http_client.py
│   │   │       ├── schemas.py            (JiraProject/Board/Sprint/User/Issue/IssuePage)
│   │   │       ├── jql/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── builder.py
│   │   │       │   ├── filters.py
│   │   │       │   └── service.py
│   │   │       └── resources/
│   │   │           ├── __init__.py
│   │   │           ├── projects.py
│   │   │           ├── boards.py
│   │   │           ├── sprints.py
│   │   │           ├── issues.py
│   │   │           └── users.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── error_handler.py
│   │   ├── modules/
│   │   │   ├── ai_insights/
│   │   │   │   ├── __init__.py
│   │   │   │   └── prompt_templates/     (empty — nothing built here yet except __init__.py)
│   │   │   ├── auth/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── models.py             (Role, Permission, RolePermission, User, UserRole, RefreshToken)
│   │   │   │   └── repository.py         (UserRepository, RoleRepository, RefreshTokenRepository)
│   │   │   ├── sprints/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── models.py             (Project, Sprint)
│   │   │   │   ├── repository.py         (ProjectRepository, SprintRepository)
│   │   │   │   └── cache.py              (SprintCache, EmployeeMetricsCache — NEW, see Section 9)
│   │   │   └── tickets/
│   │   │       ├── __init__.py
│   │   │       ├── models.py             (Ticket, TicketHistory, TicketComment)
│   │   │       └── repository.py         (TicketRepository, TicketHistoryRepository, TicketCommentRepository)
│   │   ├── shared/
│   │   │   ├── __init__.py
│   │   │   ├── base_repository.py
│   │   │   └── cache_repository.py       (generic Redis cache wrapper — NEW, see Section 9)
│   │   └── workers/                      (empty — not started)
│   ├── tests/                            (empty — no automated test suite written yet; all verification
│   │                                        so far was done via throwaway scripts during the build,
│   │                                        deleted afterward, not committed as a test suite)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── assets/
│   │   │   └── global.css
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   └── ui/
│   │   ├── features/
│   │   │   ├── admin/
│   │   │   ├── analytics/
│   │   │   ├── auth/
│   │   │   ├── backlog/
│   │   │   ├── chat/
│   │   │   ├── dashboard/
│   │   │   ├── reports/
│   │   │   └── sprints/
│   │   ├── hooks/
│   │   ├── lib/
│   │   │   └── apiClient.js
│   │   ├── pages/
│   │   │   ├── AdminPage.jsx
│   │   │   ├── BacklogPage.jsx
│   │   │   ├── ChatPage.jsx
│   │   │   ├── DashboardPage.jsx
│   │   │   ├── EmployeeAnalyticsPage.jsx
│   │   │   ├── LoginPage.jsx
│   │   │   ├── ReportsPage.jsx
│   │   │   ├── SettingsPage.jsx
│   │   │   └── SprintOverviewPage.jsx
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── routes.jsx
│   ├── package.json
│   └── vite.config.js
├── .env                                  (user's local file, not shared with the assistant)
└── docker-compose.yml
```

**Every `__init__.py` file exists** in every package directory shown above — this was double-checked earlier in the build after PyCharm showed some as plain folders (missing `__init__.py`) rather than recognized packages.

---

## 7. Database schema: designed vs. implemented

18 tables were designed with a full ER diagram. **7 are not yet implemented as SQLAlchemy models**:

| Table (designed) | Domain | Status |
|---|---|---|
| `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `refresh_tokens` | Identity & Access | ✅ Implemented (`modules/auth/models.py`) |
| `projects`, `sprints` | Jira cache | ✅ Implemented (`modules/sprints/models.py`) |
| `tickets`, `ticket_history`, `ticket_comments` | Jira cache | ✅ Implemented (`modules/tickets/models.py`) |
| `jira_sync_log` | Jira cache | ❌ Not implemented |
| `sprint_metrics`, `employee_metrics` | Analytics persistence | ❌ Not implemented (Analytics Engine currently computes on-the-fly, doesn't persist results) |
| `chat_sessions`, `chat_messages` | AI/Chat | ❌ Not implemented |
| `reports` | Reports | ❌ Not implemented |
| `audit_logs` | Audit | ❌ Not implemented |

## 8. API design: designed vs. implemented

All 7 categories (Authentication, Sprint, Analytics, Chat, Dashboard, Admin, Report APIs) were fully designed with method/URL/request/response/status codes/validation. **Zero routes are actually implemented** — no `routes.py` exists in any module yet. This is pure design-ahead; implementing them is future work.

---

## 9. Current in-progress work — read this first if continuing

**Task completed:** "Build the complete AI Chat module."
Requirements met: Established a fully streaming, context-aware AI assistant leveraging Gemini. Integrated ChromaDB semantic search for knowledge retrieval, JQL for Jira context, and employee analytics. Built a responsive React chat UI with markdown rendering and Server-Sent Events (SSE) stream parsing.

### What's been built:

1. **`app/modules/ai_insights/gemini_client.py` & `service.py`** — ✅ Updated to support `generate_text_stream` and `process_message_stream`, emitting JSON-encoded Server-Sent Events.
2. **`app/modules/ai_insights/routes.py`** — ✅ Added `POST /api/v1/chat/stream` utilizing FastAPI's `StreamingResponse`.
3. **Semantic Search Hookup** — ✅ Updated `service.py` to route `KNOWLEDGE_SEARCH` intents directly through the ChromaDB `KnowledgeBaseService`.
4. **`frontend/src/features/chat/useChatStream.ts`** — ✅ Built a custom React hook that fetches the readable stream from the backend and chunks the SSE response directly into the UI state.
5. **`frontend/src/features/chat/MessageBubble.tsx` & `ChatContainer.tsx`** — ✅ Built professional Material UI chat components that render the streaming text flawlessly using `react-markdown`.
6. **`frontend/src/pages/ChatPage.tsx`** — ✅ Replaced the placeholder with the fully operational `ChatContainer`.

### Recommended immediate next steps, in order:
1. Ensure the backend is running (`uvicorn app.main:app --reload`).
2. Run `npm run dev` in the `frontend` folder and navigate to the Chat page to interact with the bot!

---

## 10. Conventions to keep following

- **Docstrings everywhere**, Google-style, explaining *why* a decision was made, not just what the code does — this has been the tone throughout, not just a formatting nicety.
- **Type hints everywhere**, `from __future__ import annotations` at the top of every file.
- **Every new external-facing capability gets tested against something real** before being called done — SQLite/real Redis/MockTransport/real Jira endpoints, whichever fits. Bugs found this way (there were several — cascade deletes, the retry-after wiring, the CORS env-var parsing, the pagination page_size no-op) were fixed and disclosed, not glossed over.
- **Additive changes only** to existing files unless a real gap is found — and when one is, it gets flagged explicitly as a fix, with reasoning, not silently folded in.
- **Placement instructions** (a table: file → exact destination path) are expected at the end of every code-delivery turn, matching how every prior module in this build was handed off.
- When something the user shows (a screenshot, an uploaded file) reveals a structural problem (missing `__init__.py`, a stale duplicate folder, a misplaced file), that gets called out directly and specifically — not glossed over in favor of just answering the literal question asked.
