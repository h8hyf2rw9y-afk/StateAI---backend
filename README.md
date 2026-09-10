# StateAI — Backend

StateAI (también referido como **PropPilot**) es un CRM impulsado por IA diseñado específicamente para profesionales inmobiliarios. Su objetivo es centralizar todo el proceso de ventas — desde la gestión de propiedades y leads hasta la programación de citas, el seguimiento de oportunidades y el contacto con potenciales compradores.

A diferencia de los CRMs tradicionales, que se limitan a almacenar información, StateAI está diseñado para asistir activamente a los agentes inmobiliarios. Agentes de IA analizan leads, identifican prioridades, recomiendan próximas acciones, automatizan seguimientos, organizan la información de los clientes y ayudan a mover oportunidades a través del pipeline de ventas.

El objetivo final es reducir el trabajo administrativo asociado a las ventas inmobiliarias y permitir que los agentes dediquen más tiempo a construir relaciones, negociar y cerrar tratos.

Este repositorio contiene el **backend** del proyecto (la API y la lógica de servidor). El frontend vive en un repositorio/carpeta separado ([stateai-frontend](https://github.com/h8hyf2rw9y-afk/StateAI---Frontend)).

## Objetivos del proyecto

1. **Centralizar el proceso de ventas** — una única plataforma donde los agentes gestionen propiedades, leads, clientes, citas, conversaciones y negociaciones.
2. **Mejorar la gestión de leads** — ayudar a organizar y priorizar leads según sus intereses, comportamiento, presupuesto y probabilidad de conversión.
3. **Automatizar el trabajo repetitivo** — usar agentes de IA para automatizar tareas como seguimientos, recordatorios, calificación de leads, coordinación de citas y actualización del CRM.
4. **Proveer insights accionables** — en lugar de solo mostrar datos, indicar a los agentes qué acciones tomar y qué oportunidades merecen su atención.
5. **Aumentar las tasas de conversión** — reducir oportunidades perdidas asegurando que los leads calificados reciban seguimiento oportuno y personalizado.
6. **Construir un CRM AI-first** — ir más allá del modelo tradicional de CRM hacia un sistema donde la IA participa activamente en la gestión del pipeline de ventas.
7. **Crear una plataforma escalable** — sentar las bases de un producto SaaS que eventualmente soporte agentes individuales, equipos inmobiliarios y agencias.

## Status

🚧 **Core CRM (Contacts/Properties/Buyer Requirements/Property Interests/Activities/Features) + deterministic Buyer Matching + the sales Pipeline (Opportunities) + three read-only AI agents (Lead Intelligence, Follow-up, Pipeline) behind an AI Gateway + self-service Organization/User onboarding + controlled, event-driven automation (Phase 5)** — Tasks becoming overdue and Appointments coming up are now detected automatically (`app/automation/`) and turned into real in-app Notifications (the previously-inert Notification model now has a real producer), completing an Appointment marked "completed" can record its outcome as a real Activity in the same request, and closing an Opportunity Won automatically schedules a real 30-day post-sale follow-up Task — all through one small, explicit, fully-audited action layer (`create_task`/`create_activity`/`create_notification`/`update_opportunity_stage`), never an open-ended "AI can call anything." Every automated action stays Level 1 (detect + recommend) or Level 2 (a deterministic, additive, reversible CRM write); nothing moves an Opportunity's stage, marks one Won/Lost, or takes any other significant business action on its own — that stays a human decision through the existing UI, same as before this phase. Live on the real Supabase Postgres database, seeded with realistic demo data, and covered by 371 passing tests. The real frontend is wired to essentially all of this now too (Leads, Properties, Pipeline, Tasks, Appointments, Buyer Matching, all three AI agents, a real Dashboard, real sign-up/sign-in onboarding, and now a real Notification bell — see the frontend's own README). Still no Transactions, Commissions, Documents, real OAuth calendar sync, notification delivery beyond the in-app record (email/push/SMS), team invites into an *existing* organization, Sales Copilot, or any Level 3 autonomous AI action — see [What's next](#whats-next) for exactly what's real versus prepared-but-not-implemented.

## Core architectural principle

The schema is **not** built around a generic "Lead" entity. A **Contact** is the central person/entity; leads, buyer requirements, property interests, opportunities, and (eventually) transactions are relationships and processes involving a Contact over time. A person can hold multiple roles (buyer, seller, investor...) and have several buyer requirements — and several **Opportunities** (see below) — across their relationship with the agency — the same Contact never needs to be recreated.

Two fundamentally different ways a Contact enters the CRM, both modeled explicitly:

- **Case A — arrives through a property**: `Contact → PropertyInterest → Property` (e.g. someone messages about a specific Facebook/Inmuebles24 listing).
- **Case B — arrives looking for a property**: `Contact → BuyerRequirement → (locations, features) → matching Properties` (e.g. "I want a house in San Pedro, $4-5M, 3+ bedrooms").

The same Contact can have both over time (loses interest in one property, but still wants to buy — a **new** `BuyerRequirement` is added to the **existing** Contact, never a new Contact).

## Tech stack

- **Python 3.12**, **FastAPI**, **Pydantic v2**
- **SQLAlchemy 2.0** (sync, `Mapped`/`mapped_column` style) + **Alembic** for migrations
- **PostgreSQL via Supabase** (`psycopg` v3 driver)
- **Supabase Auth** for authentication — verified via JWKS (asymmetric signing keys), not recreated. See [Authentication](#authentication).
- **Ollama** (local dev, default) **+ Anthropic Python SDK** (production option) — the Lead Intelligence Agent's two LLM providers, behind one small provider abstraction so neither is hardwired in. See [Lead Intelligence Agent](#lead-intelligence-agent).
- **uv** for dependency management (`pyproject.toml` + `uv.lock`)
- **pytest** + FastAPI's `TestClient` for tests

## Project structure

```
app/
  main.py                  # FastAPI() instance, CORS, request-id + error-handling middleware, router registration
  core/
    config.py                 # pydantic-settings: DATABASE_URL, SUPABASE_URL, SUPABASE_JWT_AUD, FRONTEND_ORIGINS
    database.py                  # SQLAlchemy engine, SessionLocal, get_db() dependency
    security.py                     # JWT verification (get_current_claims), org resolution (get_current_org_user),
                                       # and require_role/require_any_role — see Authorization Model
    errors.py                          # RequestIDMiddleware + the global {"error": {...}} exception handlers —
                                          # see Error Handling
    seed_data.py                          # initial rows for the roles/features catalog tables — single source
                                             # of truth for both the Alembic migration and the test fixtures
  models/                   # SQLAlchemy ORM models — one module per entity group (see Data model below)
    base.py                     # declarative Base, UUIDPKMixin, TimestampMixin/CreatedAtMixin
    external.py                    # a stub for Supabase's auth.users table (see Data model)
  schemas/                  # Pydantic Create/Update/Read models, one module per entity, plus:
    enums.py                    # every "soft enum" (see Data model) — single source of truth
    common.py                      # ORMModel base (from_attributes=True)
    matching.py                       # response shape for the /matches endpoint
  repositories/             # thin SQLAlchemy query classes, always organization_id-scoped (see base.py)
  services/                 # business logic on top of repositories, including:
    audit_service.py            # the one reusable audit-log write path — see Audit Logging
    agent_execution_service.py     # AgentExecution persistence — see AI Execution Persistence
    opportunity_service.py            # stage validation, won/lost/reopen handling, stage-change
                                         # Activity creation — see Opportunities / Pipeline
  ai/
    lead_context_tool.py      # get_lead_context — the AI Context Layer's tool
    pipeline_agent.py             # PipelineAgent — see Pipeline Agent
    prompts/pipeline.py               # PIPELINE_SYSTEM_PROMPT
    gateway.py                          # AIGateway — orchestrates agents; deliberately never touches the database
    registry.py                            # AGENT_REGISTRY — the explicit list of runnable agents
  integrations/
    calendar/                 # CalendarProvider interface + Google/Apple/Notion STUBS only — see
                                 # Calendar Integration Architecture. Nothing here is called by any route today.
  api/
    routes/                    # one module per resource (health, me, contacts, properties,
                                  # buyer_requirements, opportunities, property_interests, activities,
                                  # features, ai, agent_executions, audit_logs, tasks, appointments,
                                  # calendar_connections, notifications)
    router.py                     # aggregates routers under /api/v1 (health/  is mounted unversioned)
alembic/
  env.py                    # reads DATABASE_URL from app.core.config; excludes the `auth` schema from
                               # autogenerate (see Data model)
  versions/                 # linear migration history — every table below, plus roles/features seed data
tests/
  conftest.py               # in-memory SQLite (FK enforcement on) + a fake authenticated user, via
                               # FastAPI dependency_overrides — no live Supabase project needed to test
  test_security.py             # real JWT verification logic against a self-signed keypair
  test_schemas.py                 # soft-enum + min/max range validation
  test_contacts_api.py               # representative CRUD integration test (the pattern every entity follows)
  test_matching_api.py                  # Use Cases 1-5 end to end, including the matching hard filters
  test_audit_log.py                        # audit record creation, actor tracking, before/after, isolation
  test_agent_execution.py                     # AI execution persistence, success/failure, isolation
  test_opportunities_api.py                      # BUY/SELL creation, stage changes, won/lost/reopen, isolation
  test_lead_context_opportunities.py                # AI Context Layer's Opportunity/Task/Appointment extension
  test_pipeline_agent.py                               # Pipeline Agent: schema, agent, route — offline, FakeLLMProvider
  test_tasks_api.py                                 # Task CRUD, lifecycle, cross-org references, isolation
  test_appointments_api.py                             # Appointment CRUD, lifecycle, isolation
  test_notifications_api.py                            # personal ownership, unread filtering
  test_calendar_connections_api.py                        # connection registration, personal ownership
  test_authorization.py                                      # require_role, and the routes that use it
  test_error_handling.py                                        # the global error envelope
pyproject.toml / uv.lock
alembic.ini
.env.example
```

## Data model

Every business table (except the two catalogs and the join tables) carries `organization_id` — this is deliberately *not* a complex multi-tenancy system yet, but the schema is prepared for one: everything is already scoped so real tenant isolation (or Postgres Row Level Security, later) doesn't require a schema rewrite.

**Design principle used throughout: "soft enums".** Every classification field (`property_type`, `status`, `source`, `timeline`, …) is a plain `VARCHAR` column in the database, validated only at the API boundary via Pydantic `Literal` types (`app/schemas/enums.py`). Native Postgres `ENUM` types are deliberately avoided — they're painful to extend (`ALTER TYPE`); adding a new value here is a one-line Python change, never a migration. Multi-valued taxonomies (roles, features) get real lookup + junction tables instead, since those need referential structure anyway.

| Table | Purpose |
|---|---|
| `organizations` | Tenant root. |
| `users` | Bridges Supabase `auth.users` to an `organization_id` + `role` (`owner`/`admin`/`agent`, matching the frontend's `UserRole`). `id` is the **same UUID** as the Supabase auth user — see below. |
| `contacts` | The central entity — a real person. `CHECK` requires at least an email or phone. |
| `roles` + `contact_roles` | Catalog + many-to-many: a Contact can be buyer + investor at once. |
| `properties` | Listings. `currency` defaults to `MXN` (Monterrey-area examples throughout: San Pedro, Valle Oriente, Chipinque). |
| `features` + `property_features` | Catalog + junction: what a property actually has (pool, garden, …). |
| `buyer_requirements` | Case B — "looking for" criteria for a Contact. Every `*_min`/`*_max` pair has a `CHECK` constraint (`min <= max`, re-validated at the API layer too for a clean 422 instead of a raw DB error). |
| `buyer_requirement_locations` | A requirement can list several acceptable areas, ranked by `priority` — never a single free-text field. |
| `buyer_requirement_features` | Catalog junction with a `classification`: `must_have` / `preferred` / `deal_breaker`. |
| `property_interests` | Case A — a Contact's interest in one specific Property. Not unique on `(contact_id, property_id)`: a contact can lose and regain interest over time, and that history is kept. |
| `opportunities` | The actual sales process an advisor is managing (BUY or SELL) — see [Opportunities / Pipeline](#opportunities--pipeline). Distinct from BuyerRequirement/PropertyInterest, which describe intent/interest, not an actively-managed deal. |
| `activities` | A structured, chronological record of what actually happened with a Contact (call, WhatsApp, viewing, offer, stage change, …) — `property_id`/`opportunity_id` both optional (set when the activity is about a specific listing/deal), `created_by_user_id` optional. `occurred_at` is a business timestamp (*when it happened*), separate from the inherited `created_at`/`updated_at` audit trail (*when the row was logged*) — the same split `property_interests` already uses via `first_contact_at`/`last_contact_at`. This is what replaces free-text `notes` as the CRM's real timeline; see [Activities](#activities). |
| `audit_logs` | "Who changed what, when" — see [Audit Logging](#audit-logging). |
| `agent_executions` | "What did the AI recommend, when, did anyone act on it" — see [AI Execution Persistence](#ai-execution-persistence). |
| `tasks` | "Something that needs to happen" (follow-up, call, document deadline, …) — see [Tasks & Reminders](#tasks--reminders). Distinct from `activities` ("something that already happened"). Optional `opportunity_id`. |
| `appointments` | A scheduled/planned event (showing, notary, signing, …) — see [Appointments](#appointments). Distinct from `activities` (what happened) and `tasks` (an open action item). Optional `opportunity_id`. |
| `calendar_connections` | Metadata-only record of a user's intent to sync with Google/Apple/Notion — **no token columns exist** (see [Calendar Integration Architecture](#calendar-integration-architecture)). |
| `notifications` | An in-app notification record for one user — see [Notifications Architecture](#notifications-architecture). |

**The `auth.users` reference**: `app/models/external.py` defines a minimal `Table` stand-in for Supabase's own `auth.users` — not a real model, just enough for SQLAlchemy to resolve `users.id`'s foreign key against it (SQLAlchemy requires the referenced table to exist somewhere in its metadata graph, even for an external, unmanaged table). `alembic/env.py`'s `include_object` filter explicitly excludes anything in the `auth` schema from autogenerate, so migrations never try to create/alter/drop Supabase's own table.

**Catalog seeding**: `contact_roles`, `property_features`, and `buyer_requirement_features` all foreign-key into `roles`/`features`, so those two catalogs are seeded with their initial rows (`app/core/seed_data.py`) as part of the initial migration itself — nothing can reference a role/feature that doesn't exist yet.

## Activities

The CRM's actual timeline — "what happened with this contact" — as a normalized, queryable log instead of a free-text `notes` field. This is the primary context source future agents (Lead Intelligence, Follow-up, Sales Copilot) will read from.

**Fields, and what was deliberately left out**: `activity_type` (soft enum: `call`/`whatsapp`/`email`/`property_viewing`/`follow_up`/`meeting`/`note`/`offer`/`negotiation`/`stage_change` — the last written automatically by `OpportunityService`, never by a client), optional `direction` (`inbound`/`outbound`), required `contact_id`, optional `property_id`, optional `opportunity_id` (see [Opportunities / Pipeline](#opportunities--pipeline)), optional `created_by_user_id`, required `occurred_at` + `notes`. No `status` — an Activity is something that *already happened*; it has no lifecycle (Appointments, for things not yet happened, is where scheduling status belongs). No `subject` — one content field is enough for now. No speculative `metadata` JSON column. Activities are append-only (no `PATCH`/`DELETE` routes) — a real CRM history log isn't edited, a correction is a new entry.

Endpoints: `POST`/`GET /contacts/{id}/activities` (create; the timeline, oldest-first, filterable by `activity_type`/`occurred_from`/`occurred_to`), `GET /properties/{id}/activities` (most-recent-first), `GET /opportunities/{id}/activities` (oldest-first — the deal's own story), `GET /activities/{id}`.

## Opportunities / Pipeline

An **Opportunity** is the actual sales process an advisor is actively managing — distinct from both `BuyerRequirement` ("what a contact is looking for") and `PropertyInterest` ("a contact's interest in one specific listing"), neither of which implies anyone is actively working a deal yet. A Contact can have **several Opportunities over time** — tried to buy one house and lost it, is now searching again, later sells their own property — each its own row, never overwritten in place (the demo data's Gabriela and Fernando both do this; see [Demo data](#demo-data)).

**Two types, one shared stage enum.** `opportunity_type` is `buy` or `sell` (`rent` deliberately excluded — `BuyerRequirementPurpose` already supports it for a *requirement*, but nothing in the stage lifecycle below was designed around a lease-signing workflow, so adding it now would be speculative). Rather than two separate stage systems, `OPPORTUNITY_STAGES` (`app/schemas/enums.py`) is one 13-value superset — a BUY and a SELL pipeline are *identical* for most of their length (`offer → negotiation → reservation → contract → closing → won/lost`) and diverge only at the start (`search`/`property_selected` vs. `listing`/`marketing`; both converge into a shared `showing` — a buyer's viewing and a seller's showing are the same event). `OPPORTUNITY_STAGES_BY_TYPE` (data, not a second enum) is what actually keeps a BUY opportunity out of a SELL-only stage and vice versa, enforced in `OpportunityService`, not the database.

This is deliberately **not a workflow/state-transition engine** — any stage valid for the opportunity's type can follow any other, forward or backward, in one `PATCH`; only the *destination* is validated, never the path taken to reach it.

**Relationships** — belongs to `organization` + `contact` (both required); optionally `property_id` and/or `buyer_requirement_id` (foreign keys, never copied/duplicated data). Neither is hard-required at creation ("a BUY opportunity should normally have a buyer_requirement_id" is a *should*, not a constraint — an opportunity can start at pure qualification before either is pinned down), but if `buyer_requirement_id` is given, it must belong to the opportunity's own `contact_id` (property has no owning-contact field anywhere in this schema to cross-check a SELL opportunity's property against, so only org-scoping is checked there).

**Business rules enforced in `OpportunityService`** (not the database, except probability/expected_value's `CHECK` constraints as a second layer):
- `probability` (0-100) and `expected_value` (≥ 0) are range-validated at both the Pydantic and DB layers.
- Setting `stage` to `lost` requires `lost_reason` (a **structured soft enum** — `price`/`financing_denied`/`chose_another_property`/`chose_competitor`/`unresponsive`/`changed_mind`/`timeline_changed`/`other` — not free text, so "which deals were lost and why" is answerable by grouping/counting, not by an LLM parsing prose later).
- Setting `stage` to `won`/`lost` auto-stamps `closed_at`; moving a closed opportunity back to a working stage (**reopening**, supported) clears `closed_at`/`lost_reason` again.
- `opportunity_type` and `contact_id` are immutable after creation (not in `OpportunityUpdate`) — if the type is wrong, create a new Opportunity; the domain already expects several per contact over time.

**No hard DELETE.** An Opportunity is business history — the same reasoning Activities/Audit Logs already apply. "Removing" one means setting `stage="lost"` with a `lost_reason`, not deleting the row; there's no soft-delete/archived flag either, since a closed stage already serves that purpose.

**Every stage change**: (1) updates the Opportunity, (2) creates a `stage_change` Activity (`"Opportunity stage changed from X to Y."`, linked via the new `opportunity_id` on Activity — see below) so the historical timeline lives in Activities rather than being duplicated inside Opportunity itself, and (3) writes a specifically-named Audit Log action — `OPPORTUNITY_CREATED`/`OPPORTUNITY_UPDATED`/`OPPORTUNITY_STAGE_CHANGED`/`OPPORTUNITY_WON`/`OPPORTUNITY_LOST`/`OPPORTUNITY_REOPENED` — reusing the existing `AuditService`, not a second audit mechanism.

**Activities, Tasks, and Appointments all gained an optional `opportunity_id`** (nullable, `SET NULL` on delete — an Opportunity is business history that's never hard-deleted in normal use, but if it somehow is, the activities/tasks/appointments that happened along the way remain real historical fact). This is what lets the CRM answer "what activities/tasks/appointments belong to this opportunity?" — via `GET /opportunities/{id}/activities` and the `opportunity_id` filter already added to `GET /tasks`/`GET /appointments`'s existing query-filter pattern, rather than a new mechanism.

**Endpoints**: `GET`/`POST /contacts/{id}/opportunities` (list-for-contact / create — same nested pattern as BuyerRequirement/PropertyInterest/Activity, `contact_id` from the URL, never the body), `GET /opportunities` (filterable by `opportunity_type`/`stage`/`owner_user_id`/`contact_id`/`property_id`/`buyer_requirement_id`/`expected_close_from`/`expected_close_to`/`is_closed`), `GET`/`PATCH /opportunities/{id}` (the PATCH is also how stages change — no separate `/close`/`/lost` action routes, matching Task's PATCH-only completion pattern), `GET /opportunities/{id}/activities`. No `DELETE`.

**Authorization**: deliberately **not** role-gated, unlike deleting a Contact/Property/Buyer Requirement/Property Interest. Creating, updating, and changing an opportunity's stage (including closing won/lost) are normal day-to-day agent operations — the same category as Task/Appointment CRUD — not the kind of destructive action `require_role` exists for; see [Authorization Model](#authorization-model).

## Demo data

`scripts/seed_demo_data.py` populates 20 fictional contacts spanning both ways a person enters the CRM (10 interested in a specific property, 10 with a buyer requirement — including the Property-Interest→not-interested→Buyer-Requirement transition case and a contact whose requirement changed over time), plus ~14 supporting properties and a chronological Activity timeline (2-5 entries) for every contact, under one dedicated **"State AI Demo Organization"**.

**Opportunities (11), on top of the above** — reusing existing contacts/properties/buyer requirements rather than inventing new ones: an active buy search, a negotiation, an offer, a viewing (`stage="showing"`), a property-selected buy, an active sell listing, a won deal, a lost deal, and two contacts each with more than one Opportunity over time — Gabriela (a lost opportunity for the property she rejected, separate from her new active search — the same transition already modeled by her buyer requirement/property interest pair) and Fernando (buying a new home *and* selling his current one, gaining a `seller` contact role alongside his existing `buyer` one — the exact "later sells their own property" scenario from the domain's own framing). A handful of Paola/Carolina/Laura/Natalia's *existing* activities are linked to their new opportunity via `opportunity_id` (not duplicated) for "meaningful activity history." Plus one overdue `Task` (Carlos's stalled follow-up) and one upcoming `Appointment` (Natalia's already-agreed second viewing), both linked to their opportunity the same way.

```bash
uv run python scripts/seed_demo_data.py            # create or update — safe to run repeatedly
uv run python scripts/seed_demo_data.py --reset     # delete the demo org (cascades everything under it), then reseed
uv run python scripts/seed_demo_data.py --reset --no-seed   # delete only, don't reseed
```

**Idempotent by construction**: every row's id is `uuid.uuid5(DEMO_NAMESPACE, "<stable key>")` (e.g. `"contact:alejandro-torres"`), not a random UUID — re-running never creates a duplicate, it updates the same rows in place. `--reset` deletes a single `organizations` row; every table underneath cascades away via the `ondelete="CASCADE"` foreign keys already in the schema (see [Data model](#data-model)), so nothing needs deleting by hand.

The script also re-points your local `egr@proppilot.app` test login (see [Setup](#setup)) at this demo org, so the seeded data shows up immediately when you log into the frontend with it — it looks for that Supabase user id (skipping gracefully with a note if not found, e.g. on a fresh project without that test account).

## Authentication

Supabase Auth is the identity provider — **not recreated here**. This backend independently verifies every request's Supabase-issued JWT; it does not trust the frontend's own route protection (`proxy.ts` there is explicitly documented as an optimistic, client-side-only check).

- **Verification** (`app/core/security.py`): `PyJWKClient` fetches Supabase's public signing keys from `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` (asymmetric keys — Supabase's current recommendation over the legacy shared-secret/HS256 approach) and verifies `iss`, `aud` (`"authenticated"`), `exp`, and the signature. No `service_role` key is needed anywhere — JWKS is public.
- **Org resolution**: the verified token's `sub` (the Supabase user id) is looked up in this app's own `users` table to get `organization_id` and `role`. Every repository method takes `organization_id` and filters by it — tenant isolation is enforced on every query, not left to callers to remember.
- **Not yet provisioned**: a real, valid Supabase session with no matching `users` row returns `403` (not `401` — the caller *is* who they say they are, they just can't use the CRM yet). **`POST /api/v1/me/organization`** is the self-service fix (`app/services/onboarding_service.py`): it creates a brand-new `organizations` row plus a `users` row for the caller (`role: "owner"`), deriving a default organization name from the caller's own JWT claims (`first_name`/`last_name` from sign-up, or their email) when none is given. Idempotent — a caller who's already provisioned just gets their existing identity back, never a second organization — so the frontend calls it unconditionally after every real sign-in (`LoginForm`, `RegisterForm`, and the OAuth/email-confirmation callback), not just once at sign-up.
- **`GET /api/v1/me`** is the simplest possible proof this all works end to end — it returns the resolved `id`, `email`, `organization_id`, `role`, and OAuth `provider` for whoever's Bearer token you send it.

⚠️ Supabase's JWT signing keys page (**Settings → Authentication → JWT Signing Keys**) needs to be on **asymmetric keys** for this to work — if your project still shows only a legacy "JWT secret" field, click **"Migrate JWT secret"** once (safe: both keys stay trusted during the transition).

## Setup

```bash
# 1. Install uv if you don't have it
pip install uv

# 2. Install dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# then fill in DATABASE_URL (Supabase dashboard -> Project Settings -> Database
# -> Connection string) and SUPABASE_URL (same value the frontend uses).
# LLM_PROVIDER defaults to "ollama" (local, no API key) for the Lead
# Intelligence Agent — see "Running Ollama locally" below to set that up,
# or switch LLM_PROVIDER=anthropic and set ANTHROPIC_API_KEY instead. Every
# other endpoint works regardless.

# 4. Apply migrations to your real Supabase Postgres
uv run alembic upgrade head

# 5. Run the server
uv run fastapi dev app/main.py
# -> http://localhost:8000, interactive docs at /docs
```

Other commands:

```bash
uv run pytest -v                 # full test suite (no live Supabase project needed)
uv run alembic downgrade base    # roll back every migration (reversibility check)
uv run alembic revision --autogenerate -m "..."   # generate a new migration after a model change
```

### Local testing against a real session

To call a protected endpoint with a real signed-in session:

1. Sign in via the running frontend, then copy the Supabase access token from the browser (Application → Cookies, or temporarily log `(await supabase.auth.getSession()).data.session.access_token` client-side).
2. `curl http://localhost:8000/api/v1/me -H "Authorization: Bearer <token>"` — the running frontend already calls `POST /api/v1/me/organization` for you right after sign-in (see [Authentication](#authentication)), so this is normally already `200`. If you're calling the API directly without ever going through the frontend's login/register forms, `POST http://localhost:8000/api/v1/me/organization -H "Authorization: Bearer <token>"` first — expect `403` from step 2 beforehand, `200` after.

## API

All endpoints below live under `/api/v1` and require `Authorization: Bearer <supabase-access-token>`, except `GET /health` (unauthenticated, outside `/api/v1`, for uptime checks).

| Method | Path | Notes |
|---|---|---|
| GET | `/me` | Whoami — see [Authentication](#authentication). |
| GET, POST | `/contacts` | List (paginated) / create. |
| GET, PATCH | `/contacts/{id}` | |
| **DELETE** | **`/contacts/{id}`** | **owner/admin only** — see [Authorization Model](#authorization-model). |
| POST, DELETE | `/contacts/{id}/roles[/{role_key}]` | Assign / remove a role. |
| GET, POST | `/contacts/{id}/buyer-requirements` | List / create *for that contact* (Case B). |
| GET, POST | `/contacts/{id}/property-interests` | List / create *for that contact* (Case A). |
| GET, POST | `/contacts/{id}/opportunities` | List / create *for that contact* — see [Opportunities / Pipeline](#opportunities--pipeline). |
| GET, POST | `/contacts/{id}/activities` | Create / the contact's timeline (oldest first) — see [Activities](#activities). |
| GET, POST | `/properties` | |
| GET, PATCH | `/properties/{id}` | |
| **DELETE** | **`/properties/{id}`** | **owner/admin only.** |
| POST, DELETE | `/properties/{id}/features[/{feature_key}]` | What a property actually has. |
| GET | `/properties/{id}/activities` | Most-recent-first. |
| GET | `/buyer-requirements` | |
| GET, PATCH | `/buyer-requirements/{id}` | |
| **DELETE** | **`/buyer-requirements/{id}`** | **owner/admin only.** |
| POST, DELETE | `/buyer-requirements/{id}/locations[/{location_id}]` | Add / remove a preferred area — never deletes the requirement itself. |
| POST, DELETE | `/buyer-requirements/{id}/features[/{feature_key}]` | Tag / untag a must-have/preferred/deal-breaker feature — removes the relationship only, never the global feature catalog row. |
| GET | `/opportunities` | Filterable by `opportunity_type`/`stage`/`owner_user_id`/`contact_id`/`property_id`/`buyer_requirement_id`/`expected_close_from`/`expected_close_to`/`is_closed`. |
| GET, PATCH | `/opportunities/{id}` | PATCH is also how stages change (including closing won/lost, and reopening) — no separate action routes. No DELETE — see [Opportunities / Pipeline](#opportunities--pipeline). |
| GET | `/opportunities/{id}/activities` | The deal's own timeline, oldest first — includes every auto-recorded stage-change entry. |
| **GET** | **`/buyer-requirements/{id}/matches`** | **Use Case 5** — deterministic candidate properties (see below). |
| **GET** | **`/buyer-requirements/{id}/property-matches`** | **Buyer Matching** — every active property, classified match/partial_match/no_match with explained criteria (see below). Not a replacement for `/matches` above — a separate, richer analysis. |
| GET | `/features` | The global feature catalog (`app/models/feature.py`) — `?active=false` includes inactive features too. Defaults to active-only. |
| GET, PATCH | `/property-interests/{id}` | |
| **DELETE** | **`/property-interests/{id}`** | **owner/admin only.** |
| GET | `/activities/{id}` | |
| GET | `/ai/lead-context/{contact_id}` | Internal/debug surface for the AI Context Layer — see [AI Context Layer](#ai-context-layer). |
| POST | `/ai/lead-intelligence/{contact_id}` | Runs the Lead Intelligence Agent — persists an `AgentExecution` either way. See [Lead Intelligence Agent](#lead-intelligence-agent) and [AI Execution Persistence](#ai-execution-persistence). |
| POST | `/ai/follow-up/{contact_id}` | Runs the Follow-up Agent — persists an `AgentExecution` either way. See [Follow-up Agent](#follow-up-agent). |
| POST | `/ai/pipeline/{contact_id}` | Runs the Pipeline Agent — persists an `AgentExecution` either way. See [Pipeline Agent](#pipeline-agent). |
| GET | `/ai/agent-executions` | History of AI runs for this org, filterable by `contact_id`/`agent_name`. |
| GET, PATCH | `/ai/agent-executions/{id}` | PATCH sets `human_action` (`acted_on`/`dismissed`) — the only client-writable field. |
| GET | `/audit-logs`, `/audit-logs/{id}` | Read-only — see [Audit Logging](#audit-logging). |
| GET, POST | `/tasks` | See [Tasks & Reminders](#tasks--reminders). |
| GET, PATCH, DELETE | `/tasks/{id}` | |
| GET, POST | `/appointments` | See [Appointments](#appointments). |
| GET, PATCH, DELETE | `/appointments/{id}` | |
| GET, POST | `/calendar-connections` | A user's own connections only — see [Calendar Integration Architecture](#calendar-integration-architecture). No OAuth flow exists behind this. |
| DELETE | `/calendar-connections/{id}` | |
| GET | `/notifications` | A user's own notifications only — `?unread=true` filters. No POST route — see [Notifications Architecture](#notifications-architecture). |
| PATCH | `/notifications/{id}` | Marks read/unread (`{"read": true/false}`). |

### Example: Use Cases 1–5 via curl

```bash
TOKEN="<supabase-access-token>"
API=http://localhost:8000/api/v1

# 1. Create a contact
CONTACT=$(curl -s -X POST $API/contacts -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"first_name":"Juan","last_name":"Perez","phone":"+52 811 000 0000"}')
CONTACT_ID=$(echo $CONTACT | jq -r .id)

# 2. Create a property
PROPERTY=$(curl -s -X POST $API/properties -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Casa Valle Oriente","property_type":"house","status":"active","price":5000000,"city":"San Pedro Garza Garcia","neighborhood":"Valle Oriente","bedrooms":3,"bathrooms":2,"construction_m2":250}')

# 3. Case A — Juan is interested in that specific property
curl -s -X POST $API/contacts/$CONTACT_ID/property-interests -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"property_id\":\"$(echo $PROPERTY | jq -r .id)\",\"status\":\"interested\"}"

# 4. Case B — Juan didn't like it, but still wants a house in San Pedro
REQUIREMENT=$(curl -s -X POST $API/contacts/$CONTACT_ID/buyer-requirements -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"property_type":"house","budget_min":4000000,"budget_max":5000000,"bedrooms_min":3,"bathrooms_min":2,"construction_m2_min":180}')
REQUIREMENT_ID=$(echo $REQUIREMENT | jq -r .id)
curl -s -X POST $API/buyer-requirements/$REQUIREMENT_ID/locations -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"city":"San Pedro Garza Garcia","neighborhood":"Valle Oriente","priority":1}'

# 5. Find matching properties (no AI — deterministic SQL, see below)
curl -s $API/buyer-requirements/$REQUIREMENT_ID/matches -H "Authorization: Bearer $TOKEN"
```

### How matching works (`app/services/matching_service.py`)

Deterministic, no AI: given a `BuyerRequirement`, candidate `Property` rows in the same organization are filtered by `status = 'active'`, `property_type`, budget range, every `*_min` threshold (bedrooms/bathrooms/m²/parking), and — if the requirement lists any — a match against at least one preferred location. A property missing **any** `must_have` feature is a **hard exclusion**, not a scoring penalty; surviving candidates are ranked by how many `preferred` features they also have. Every numeric threshold treats a `NULL` property value as "doesn't qualify" (a property with an unset budget/bedroom count can't be confirmed to satisfy a requirement) — kept consistent across every field rather than special-casing some as lenient.

### Buyer Matching — the richer, explainable analysis (`analyze_matches`, same file)

`GET /buyer-requirements/{id}/property-matches` is a **separate method on the same `MatchingService`**, not a redesign of `find_matches` above — deliberately kept alongside it rather than replacing it, since `find_matches`'s existing tests and its existing frontend consumer (`features/buyer-requirements/components/match-list.tsx`) both depend on its exact current "silently exclude non-qualifying properties" behavior. The difference: `find_matches` folds every criterion into one SQL `WHERE` clause, so a property that doesn't qualify was never fetched and can't be explained; `analyze_matches` instead fetches every `status = "active"` property in the organization and evaluates each one **criterion-by-criterion in Python**, so every property gets a real, inspectable result — including the ones that don't match at all.

**Criteria evaluated** (only when the requirement actually specifies a value for it — a `NULL` requirement field is "no preference," never counted as met or unmet): property type, budget (with an explicit currency-mismatch check — no FX conversion is invented, a mismatched currency is reported as unconfirmable, not silently compared), city, state, and neighborhood (each independently — a requirement's several `BuyerRequirementLocation` rows are OR'd together per field, same "any one location is enough" philosophy `find_matches` already uses, just split into three separate explainable dimensions instead of one combined AND-per-location filter), bedrooms, bathrooms, parking spaces, construction area, and land area (each a `_min`/`_max` range check against the property's single value). `postal_code` exists on `Property` but has **no corresponding field on `BuyerRequirementLocation`** — confirmed by reading the model, not assumed — so it's never evaluated as a criterion; there's nothing on the requirement side to compare it against.

**Features** are evaluated individually, not as one aggregate count: a `must_have` feature the property lacks, or a `deal_breaker` feature the property has, is a **hard override to `no_match`** regardless of how many other criteria matched (same "hard exclusion, not a scoring penalty" philosophy `find_matches` already established for `must_have` — extended here to `deal_breaker`, a real `FeatureClassification` value `find_matches` itself never actually checked). Each `preferred` feature present or missing is its own explained criterion, not folded into a single "N of M" number.

**Classification** (`match` / `partial_match` / `no_match`) is a plain, documented rule — no numeric score, no invented weighting:
- A missing `must_have` feature or a present `deal_breaker` feature → always `no_match`.
- Otherwise: every specified criterion satisfied → `match`; none satisfied → `no_match`; some but not all → `partial_match`.
- A requirement that specifies **no** comparable criteria at all → `partial_match` (neither a match nor a mismatch can honestly be claimed from zero criteria — a deliberate, documented edge case, not an oversight).

Results are sorted best-first (by classification, then by how many criteria were met) and capped by the same `limit` (default 20, max 100) convention as `find_matches`. The response (`PropertyMatchAnalysis`, `app/schemas/matching.py`) carries `criteria_met`/`criteria_unmet` as plain human-readable sentences and one `summary` line — no score field anywhere on the model.

## AI Context Layer

The seam between the CRM's real data and the AI agents built on top of it — the [Lead Intelligence Agent](#lead-intelligence-agent) today, Follow-up and Sales Copilot later. This layer itself is deterministic and non-LLM: nothing here calls Claude, OpenAI, or any other model; it only assembles data that already exists into a structure an agent can read.

**Required flow, and where each piece lives:**

```
AI Agent  →  AI Tool  →  Backend Service  →  Repository  →  Supabase
(future)     app/ai/     app/services/       app/repositories/
             lead_context_tool.py  lead_context_service.py   (existing, reused as-is)
```

- **Repository layer**: `LeadContextService` composes `ContactRepository`, `BuyerRequirementRepository`, `PropertyInterestRepository`, `ActivityRepository`, `PropertyRepository`, plus (added alongside Opportunities) `OpportunityRepository`, `TaskRepository`, and `AppointmentRepository`. The latter two gained one new method each, `list_for_contact(organization_id, contact_id, opportunity_ids=None)` — a task/appointment tied to one of this contact's opportunities doesn't necessarily have its own `contact_id` set (the two fields are independent), so this matches `contact_id == contact_id OR opportunity_id IN opportunity_ids`; the existing generic `list()` method (contact_id-only) would silently miss that second case. Every entity is still fetched **once each** for the whole contact — Task/Appointment/Activity lists are filtered in memory per opportunity, not re-queried per opportunity, so a contact with several opportunities doesn't cost extra round trips.
- **Backend Service** (`app/services/lead_context_service.py`): `LeadContextService(db).build(organization_id, contact_id, *, activity_limit=20, task_limit=20, appointment_limit=20)` — 404s the same way every other service does if the contact isn't found in that organization, then assembles a `LeadContext` (`app/schemas/lead_context.py`).
- **AI Tool** (`app/ai/lead_context_tool.py`): `get_lead_context(current_user, contact_id, db, *, activity_limit=20, task_limit=20, appointment_limit=20)`. This is the actual security boundary — it takes the **whole authenticated `CurrentUser`**, never a bare `organization_id`, so there is no parameter an agent (or a manipulated prompt) could supply to reach another organization's data: `CurrentUser` can only be constructed by `get_current_org_user` from a verified Supabase JWT (see [Authentication](#authentication)). This held for Buyer Requirements/Property Interests/Activities from day one and holds identically for Opportunities/Tasks/Appointments now — every one of them is loaded through an `organization_id`-scoped repository call inside `LeadContextService.build`, never independently. A small `LEAD_CONTEXT_TOOL_SCHEMA` dict alongside it documents the tool's name/description/input shape for whoever wires up an agent framework later — descriptive metadata only, not wired to any SDK.

**`LeadContext` (the schema)** is a typed tree, not concatenated text, so an agent's prompt-building code reads specific fields instead of parsing prose. Contact/BuyerRequirement/PropertyInterest/Activity/timeline/engagement_summary are as they were; **Opportunities, Tasks, and Appointments were added** so an agent can understand a contact not only as a lead but as a participant in one or more real-estate business processes (see [Opportunities / Pipeline](#opportunities--pipeline)) — never confusing "what they're looking for" (BuyerRequirement), "what happened" (Activity), "what needs to be done" (Task), "what's scheduled" (Appointment), and "what business process this is part of" (Opportunity):

- `contact` — identity, role keys, source, preferred contact method.
- `buyer_requirements` — **all** of them, including `cancelled`/superseded ones, with their `locations`/`features`. Losing old rows would break the exact history this layer exists to preserve (e.g. Sergio Navarro's changed criteria in the demo data).
- `property_interests` — **all** of them, including `not_interested`. Same reasoning: Gabriela Ortiz's rejected-property-interest → active-buyer-requirement transition (Case A → Case B) only makes sense if both rows are visible together.
- `properties` — the de-duplicated set of properties referenced by those interests, activities, **and now opportunities**.
- `opportunities` — **all** of them, including `won`/`lost` ones — a contact's history, including deals that didn't work out, is real context, not noise to discard (Gabriela's demo data again: a `lost` opportunity for the property she rejected, kept fully separate from her later `active` search — never merged, never assumed the newest is the only relevant one). Each carries its own type/stage/`expected_value`/`currency`/`probability`/`expected_close_date`/`closed_at`/`lost_reason`/`owner_user_id`, a concise `property`/`buyer_requirement` **summary** (not the full object — that's already available, deduplicated, in `properties`/`buyer_requirements`; embedding it again per-opportunity was judged unnecessary duplication), a derived `is_active` (`stage` not in the closed set — never a stored field, see [Opportunities / Pipeline](#opportunities--pipeline)), and `activity_ids`/`task_ids`/`appointment_ids` — typed references into the top-level lists below, so "what belongs to this opportunity" is answerable without duplicating those lists once per opportunity.
- `activities` — the most recent `activity_limit` (default `20`), newest first. Opportunity **stage changes already arrive here automatically**: `OpportunityService` records every stage change as a normal `stage_change` Activity (see [Opportunities / Pipeline](#opportunities--pipeline)), so it needed no new code path — it's just another Activity, now also carrying an `opportunity_id`.
- `tasks` / `appointments` — this contact's own, **plus** any tied to one of their opportunities (see the `list_for_contact` note above), up to `task_limit`/`appointment_limit` (default `20` each). Each carries its own `opportunity_id` so it can be cross-referenced from either direction.
- `timeline` — activities (stage changes included, via the mechanism above) + property-interest/buyer-requirement/**opportunity** creation events merged into one oldest-first list, the single "story so far" an agent can read start to finish instead of interleaving four lists itself. Opportunity stage changes deliberately do **not** get their own `event_type` — that would be a second, parallel history of a fact the `stage_change` Activity already records; only an opportunity's *creation* gets one, mirroring how buyer-requirement/property-interest creation already did. "How long has this opportunity been in its current stage?" is answerable the same way: find the most recent `stage_change` Activity/timeline entry referencing that opportunity (via `activity_ids`/`related_id`), rather than a new, easily-stale `stage_entered_at` column nothing else in this schema maintains.
- `engagement_summary` — `activity_count`, `last_activity_at`, `days_since_last_activity`, `has_active_buyer_requirement`, `active_property_interest_count`, plus (Opportunity/Task/Appointment-aware) `active_opportunity_count`, `won_opportunity_count`, `lost_opportunity_count`, `pending_task_count`, `overdue_task_count`, `upcoming_appointment_count`. Every one of these is a plain count or a deterministic date comparison — never a judgment. Deliberately **not** added: a per-stage breakdown (already directly readable from `opportunities[].stage`, so a second summary of the same list would be redundant, not additive), and — same rule as before, now re-confirmed for Opportunities specifically — no `ai_score`, `conversion_probability`, "hot/warm/cold" label, predicted-close-date, or sentiment. Computing a fact is this layer's job; judging what it means is a future agent's.

**Data minimization**: no password, auth token, API key, or other `users`/Supabase-auth field is ever included — the tool only touches CRM entities. `activity_limit`/`task_limit`/`appointment_limit` (each default `20`, capped at `200` on the route) are the context-size controls in place now; `opportunities`/`properties`/`buyer_requirements`/`property_interests` stay unlimited (naturally small per contact, per the demo data — a handful at most) — the parameter/pattern is there so a future limit on any of these is a small addition, not a redesign.

**Context size, measured**: for the real demo contacts with the richest data (Fernando Vargas — two opportunities, one buy one sell; Gabriela Ortiz — two opportunities), the full `LeadContext` JSON is **~2.0-2.3K tokens** (measured via `len(json) // 4`, a standard rough estimate). Comfortably within any local or hosted model's context window (including `llama3.2`'s), and small enough that the existing `activity_limit`/`task_limit`/`appointment_limit` controls are headroom for future growth, not a response to an actual problem today.

**Why a route exists** (`GET /ai/lead-context/{contact_id}?activity_limit=&task_limit=&appointment_limit=`, under the `/ai` prefix): it's how every other feature in this backend gets verified end-to-end against the real Supabase project rather than only unit-tested, it adds no security surface beyond what the tool itself already enforces (same `get_current_org_user` dependency as every other route), and it doubles as a low-risk "what would the AI see for this lead" debugging surface during development. It is not meant for the frontend UI.

**Tests** (`tests/test_lead_context.py` for the original fields, `tests/test_lead_context_opportunities.py` for the Opportunity/Task/Appointment extension — 32 tests): a contact with no opportunities; one BUY opportunity; one SELL opportunity; multiple opportunities preserved independently; an opportunity with a property/buyer requirement (and without — `None` summaries); an opportunity with activities/tasks/appointments (including a task linked only via `opportunity_id`, no `contact_id` of its own); active/won/lost opportunities and `is_active`; multiple opportunities at different stages simultaneously; the timeline's new `opportunity` creation event and confirmation that stage changes reuse the existing Activity mechanism rather than a second history; deterministic `engagement_summary` metrics (including overdue-task and upcoming-appointment edge cases — cancelled-but-future and completed-but-past appointments correctly excluded); organization isolation (both the tool's existing 404 behavior, and a same-organization-id lookup never leaking another org's opportunity); partial data; determinism; an HTTP-level test confirming the route's response includes `opportunities`/`tasks`/`appointments` and accepts the new limit params; and real-demo-data validation against Gabriela (two independent opportunities), Sergio (a `won` opportunity), Carlos (an overdue task), Natalia (an upcoming appointment), and Paola (an opportunity with linked activity history) — the exact scenarios seeded in [Opportunities / Pipeline](#opportunities--pipeline), each also confirmed live against the real Supabase project. Every existing `test_lead_context.py`/`test_golden_contacts.py` test continues to pass unmodified. Most tests call `LeadContextService`/`get_lead_context` directly rather than through HTTP — the whole point of this layer is to be testable without a running server or any agent framework.

**Agents unmodified, on purpose**: neither `LeadIntelligenceAgent` nor `FollowUpAgent`'s reasoning logic or prompts changed. Both already build their prompt from `context.model_dump_json(...)` — the entire `LeadContext` object — so the new Opportunity/Task/Appointment fields simply appear in what the model already receives, with no code change needed for the model to see them. Their system prompts describe the JSON generically ("everything this CRM knows about one contact") rather than enumerating every field, so that description stays accurate without an edit; neither prompt's version was bumped, since the prompt *text* didn't change. Whether either agent's real (non-test) output quality changes now that it can see Opportunity data is exactly the kind of question `scripts/evaluate_agents.py` exists to answer empirically — not something this task decided or measured, on purpose (see [What's next](#whats-next)).

## Lead Intelligence Agent

The first real AI agent in this codebase, and the first time this backend makes an actual LLM call. It's deliberately small: one agent, one provider, read-only, no autonomous actions.

**Flow**: `CurrentUser → get_lead_context → LeadContext → LLMProvider → LeadIntelligenceAnalysis → LeadIntelligenceResult`. The agent never touches a repository or Supabase directly — only `get_lead_context`, same as the contract described in [AI Context Layer](#ai-context-layer).

### Provider abstraction (`app/ai/llm/`)

The agent depends on `LLMProvider` (`base.py`), an abstract interface with one real method — `generate_structured(system_prompt, user_prompt, response_model) -> response_model instance` — never on a specific vendor SDK. Two implementations exist today:

- **`OllamaProvider`** — talks to a locally running [Ollama](https://ollama.com) server. **The local development default**: no API key, no network egress, no cost.
- **`AnthropicProvider`** — the production option, preserved and fully functional, just not required for day-to-day development anymore.

Adding `OpenAIProvider`/`HuggingFaceProvider` later means adding another class here and a case in `factory.py` — not touching the agent or the route. `app/ai/llm/errors.py` defines one exception family (`LLMConfigError`, `LLMTimeoutError`, `LLMProviderError`, `LLMInvalidOutputError`) so callers never need to catch a vendor-specific exception type; both providers also expose a `provider_name` (`"ollama"`/`"anthropic"`, logging only — the agent never branches on it) alongside `model_name`.

`AnthropicProvider.generate_structured` gets reliable structured output by forcing a single tool call whose input schema is the requested Pydantic model's own JSON schema (`response_model.model_json_schema()`, sent as the tool's `input_schema`, with `tool_choice` pinned to that tool's name). `OllamaProvider.generate_structured` uses Ollama's own "Structured outputs" feature instead — the same JSON schema is sent as the request's `format` field, which constrains the model's decoding to that shape; it works with any locally installed chat model, not just tool-calling ones. Neither asks the model to emit JSON in prose and hopes it parses.

`app/ai/llm/factory.py`'s `build_default_provider()` is the one place that decides which provider the app actually uses — see [Provider selection](#provider-selection) below.

### Provider selection

`LLM_PROVIDER` (env var, default `ollama`) picks the branch in `build_default_provider()`:

- **`LLM_PROVIDER=ollama`** (default) — builds an `OllamaProvider` from `OLLAMA_BASE_URL`/`OLLAMA_MODEL`. Needs no `ANTHROPIC_API_KEY` at all; the app starts and this endpoint works with it completely unset.
- **`LLM_PROVIDER=anthropic`** — builds an `AnthropicProvider` from `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`; raises `LLMConfigError` (surfaced as `503`) if the key is missing.

No provider registry — it's an `if`/`elif` in one function, on purpose (see [What's next](#whats-next) for when a registry might actually earn its keep).

### Model configuration

Model names are never hardcoded — `app/core/config.py`'s `ollama_model` (env `OLLAMA_MODEL`, default `llama3.2`, ~2 GB) and `anthropic_model` (env `ANTHROPIC_MODEL`, default `claude-sonnet-5`) are the single source of truth for each provider, read once by the factory above. Change either by setting its environment variable, not by editing code.

`llama3.2` (3B), not the larger `llama3.1` (8B), is the default specifically because this is meant to run well on CPU-only development machines: on hardware with no GPU, `llama3.1` took several minutes per lead for this agent's JSON-schema-constrained output and sometimes still timed out at 300s. If you have GPU acceleration (or don't mind the wait), `llama3.1` gives noticeably better reasoning — just `ollama pull llama3.1` and set `OLLAMA_MODEL=llama3.1`.

### Environment variables

Add to your `.env` (see `.env.example`):

```bash
# Local development (default) — needs Ollama installed and running, see below.
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_TIMEOUT_SECONDS=180  # measured, not guessed — see the note below

# Production option — only read when LLM_PROVIDER=anthropic.
ANTHROPIC_API_KEY=sk-ant-...    # from https://console.anthropic.com/settings/keys
ANTHROPIC_MODEL=claude-sonnet-5 # optional, this is already the default
```

Every other endpoint in this backend works regardless of any of this. With `LLM_PROVIDER=ollama` (the default), `ANTHROPIC_API_KEY` isn't needed at all.

**`OLLAMA_TIMEOUT_SECONDS` exists because of a real bug found through measurement, not guesswork**: `OllamaProvider`'s own class default is 60s, and `build_default_provider()` didn't override it for a while — on this project's actual CPU-only development hardware (see [Agent Evaluation](#agent-evaluation)'s performance numbers), every real request through `/ai/lead-intelligence` or `/ai/follow-up` was silently failing with `LLMTimeoutError` after 60 seconds, well before the model was done. `settings.ollama_timeout_seconds` (default `180`) is now wired through the factory and covered by a regression test (`test_ollama_provider_uses_the_configured_timeout_not_the_class_default` in `tests/test_llm_provider_selection.py`).

### Running Ollama locally

1. Install Ollama — Windows: download from [ollama.com/download](https://ollama.com/download), or `winget install Ollama.Ollama`. macOS/Linux: see the same page.
2. Pull the configured model (matches `OLLAMA_MODEL`'s default): `ollama pull llama3.2` (~2 GB).
3. Make sure the server is up: `curl http://localhost:11434/api/tags` should return JSON, not a connection error. The installer usually registers Ollama as a background service that's already running; if not, `ollama serve`.
4. Call the endpoint as usual (see [API](#api) below) — no other setup needed.

If Ollama isn't installed or the model isn't pulled, `POST /ai/lead-intelligence/{contact_id}` fails cleanly (`502`, with a message telling you exactly which of those two is missing — see [Error handling](#error-handling)) instead of hanging or crashing.

### Structured output (`app/schemas/lead_intelligence.py`)

Two schemas, deliberately separate:

- **`LeadIntelligenceAnalysis`** — exactly what the LLM is asked to produce (its JSON schema *is* the structured-output shape both providers are constrained to): `priority` (`high`/`medium`/`low`, soft enum in `app/schemas/enums.py`), `confidence` (`0.0`-`1.0`), `reasoning`, `positive_signals`/`risk_signals` (lists of short strings), `recommended_next_action` (soft enum: `call`/`whatsapp`/`email`/`schedule_viewing`/`send_properties`/`follow_up`/`meeting`/`re_engage`/`no_action_needed`), and `insufficient_data` (a boolean the model sets instead of guessing when the context is too sparse to say anything meaningful).
- **`LeadIntelligenceResult`** — what the route actually returns: the analysis plus provenance the agent fills in itself (`contact_id`, `model`, `prompt_version`, `generated_at`) — the LLM can't know its own model name or the current time, so those aren't fields the model fills in.

**Lesson from real local testing (prompt `v2`)**: both `llama3.1` and `llama3.2` initially returned `confidence` as a percentage integer (e.g. `80`) instead of the schema's `0.0`-`1.0` decimal — a JSON schema's `minimum`/`maximum` alone isn't always enough for a small local model to infer the intended scale, even though Anthropic's forced tool-use never showed this. Pydantic correctly rejected it both times (`LLMInvalidOutputError`, never silently coerced or divided by 100 — that would be inventing a value, not validating one). The fix was making both the schema's `Field(description=...)` and the system prompt explicitly state "a decimal between 0.0 and 1.0 (e.g. 0.85), never a percentage" — confirmed fixed by re-running the same contact that had failed.

**Fact vs. inference**: the schema and the system prompt both exist to keep this distinction explicit, regardless of which provider is active. `positive_signals`/`risk_signals`/`reasoning` are instructed to stay traceable to facts already present in the `LeadContext` JSON (an activity count, a stated budget, a status) — the *judgment* (`priority`, `recommended_next_action`, `confidence`) is the inference layered on top. No field here is a raw, unexplained score; `reasoning` is mandatory so a human can always see which facts led to which conclusion.

### System prompt (`app/ai/prompts/lead_intelligence.py`)

Kept in its own module, versioned via `LEAD_INTELLIGENCE_PROMPT_VERSION` (currently `"v1"`, echoed onto every `LeadIntelligenceResult` so a stored result can be traced back to the exact prompt that produced it) — unchanged by, and identical across, whichever provider is active. Defines the agent as a real-estate CRM intelligence assistant that reasons only from the provided CRM data, never invents facts, distinguishes facts from inference, treats a rejected-property → buyer-requirement transition (Case A → Case B, see [AI Context Layer](#ai-context-layer)) as one continuing lead rather than two, sets `insufficient_data` honestly when the context is too sparse, and never claims to take action itself.

### API

`POST /ai/lead-intelligence/{contact_id}` — same auth as every other route (`get_current_org_user`); the agent 404s through `get_lead_context` if the contact doesn't exist or belongs to another organization, before the LLM is ever called.

```bash
curl -X POST $API/ai/lead-intelligence/$CONTACT_ID -H "Authorization: Bearer $TOKEN"
```

### Error handling

| Situation | Response |
|---|---|
| Contact not found / belongs to another organization | `404` (from `get_lead_context`, same as every other contact-scoped route) |
| `LLM_PROVIDER=anthropic` selected but `ANTHROPIC_API_KEY` not configured | `503`, generic message — never a raw provider error |
| Ollama server unreachable (not running, wrong `OLLAMA_BASE_URL`) | `502` to the client; the server-side log/exception says plainly to start Ollama (`ollama serve`) |
| Configured Ollama model not pulled locally | `502` to the client; the server-side log/exception names the exact `ollama pull <model>` command |
| Provider call times out (either provider) | `504` |
| Provider returns an error (Anthropic auth/rate-limit/5xx, or an Ollama HTTP error) | `502`, generic message — provider details are logged server-side only, never sent to the client |
| Model didn't return the requested structured output, or its output fails schema validation | `502`, generic message |

Every one of these is a generic message to the API consumer — the specific, actionable detail (which command to run, which server to start) only ever reaches the server-side log via `logger.warning(...)` in `LeadIntelligenceAgent.analyze`, never the HTTP response body.

### Read-only, by construction

The agent can analyze, prioritize, and recommend — it cannot send a message, modify a contact or property, create an activity or appointment, or contact anyone. It has no tool other than `get_lead_context`, which is itself read-only; there is nothing in this codebase yet that would let it take an action even if the model asked it to.

### Testing

Fully offline and deterministic, no Ollama/Anthropic required, four files:

- **`tests/test_lead_intelligence_agent.py`** — a `FakeLLMProvider` (implements `LLMProvider`, returns a canned response or raises a canned error, records every call) stands in for any real provider throughout, so this file needs no API key, no local Ollama, and makes no network call. Covers: schema validation (valid payload, out-of-range confidence, unknown priority/action), context retrieval and organization isolation (a nonexistent or cross-org contact 404s *before* the LLM is ever called — asserted via `fake.calls == []`), prompt construction (the contact's name and key facts actually appear in the prompt sent to the "model"), every documented error path (timeout, invalid output) at both the agent and route level, and the `502`/`503`/`404` route paths.
- **`tests/test_ollama_provider.py`** — `OllamaProvider` in isolation: a valid structured response, the exact request shape sent (`format` = the schema, correct `model`), timeout, connection-refused (with the "Is Ollama running?" message asserted), model-not-found (404, with the `ollama pull` message asserted), and both malformed-response-shape and schema-validation failure. Every case but one monkeypatches `httpx.post`; the exception is a real connection to a closed local port, proving the "Ollama unavailable" path against a genuine socket failure rather than only a simulated one — still instant, no install needed.
- **`tests/test_llm_provider_selection.py`** — `build_default_provider()`'s branching: default (`ollama`, no key needed), `anthropic` without a key (`LLMConfigError`), `anthropic` with one (returns a working `AnthropicProvider` — confirms the pre-Ollama implementation is still intact and functional), and both providers satisfying the same `LLMProvider` interface.

Two integration tests call a real provider and are skipped by default — CI and the normal `uv run pytest` run never depend on either:

```bash
# Real Ollama, against the demo data's Carlos/Gabriela/Carolina/Sergio — requires the explicit
# RUN_OLLAMA_INTEGRATION_TESTS=1 opt-in (not just Ollama being reachable — see below) plus a live
# Ollama server. Each contact can take 1-3+ minutes on CPU-only hardware; expect several minutes total.
RUN_OLLAMA_INTEGRATION_TESTS=1 uv run pytest tests/test_lead_intelligence_ollama_integration.py -v -s

# Real Anthropic — skipped unless ANTHROPIC_API_KEY resolves through settings.
ANTHROPIC_API_KEY=sk-ant-... uv run pytest tests/test_lead_intelligence_integration.py -v -s
```

The Ollama test needs an explicit env var, not just Ollama being reachable, on purpose: on a dev machine where Ollama happens to already be running for something unrelated, a plain `uv run pytest` must stay fast (a few seconds) rather than silently turning into several minutes of real LLM calls just because Ollama was up in the background.

## Follow-up Agent

The second real AI agent, built on exactly the same architecture as [Lead Intelligence Agent](#lead-intelligence-agent) — same `LeadContext`, same `LLMProvider` abstraction, same providers, same route/error-handling shape. It answers a different question, though:

| | Lead Intelligence | Follow-up |
|---|---|---|
| Question | "How important is this lead, what should the advisor prioritize?" | "Does this lead need follow-up **right now**, through which channel, and what should the advisor say?" |
| Schema | `LeadIntelligenceAnalysis` | `FollowUpRecommendation` |
| Prompt | `app/ai/prompts/lead_intelligence.py` | `app/ai/prompts/follow_up.py` (written from scratch, not derived from the other) |
| Route | `POST /ai/lead-intelligence/{contact_id}` | `POST /ai/follow-up/{contact_id}` |

**Flow**: `CurrentUser → get_lead_context → LeadContext → LLMProvider → FollowUpRecommendation → FollowUpResult` — identical shape to Lead Intelligence's, reusing the same AI Tool. `FollowUpAgent` (`app/ai/follow_up_agent.py`) never touches a repository or Supabase directly; `ActivityRepository`/`BuyerRequirementRepository`/`PropertyInterestRepository`/`PropertyRepository` are all reused exactly as `LeadContextService` already composes them — no new repository or database-access code was needed for this agent.

### Response schema (`app/schemas/follow_up.py`)

`FollowUpRecommendation` — what the LLM produces: `should_follow_up` (bool), `priority` (reuses the `LeadPriority` soft enum — same three values, no reason for a second tuple), `recommended_channel` (`whatsapp`/`email`/`call`/`none`), `recommended_action` (`follow_up`/`send_properties`/`confirm_viewing`/`check_in`/`call_client`/`prepare_for_appointment`/`no_action`), `reason`, `suggested_message` (nullable), `confidence` (`0.0`-`1.0`, with the same explicit "a decimal, never a percentage" description Lead Intelligence's `confidence` field needed after real testing — see below). `FollowUpResult` wraps it with the same provenance fields (`contact_id`, `model`, `prompt_version`, `generated_at`).

**`suggested_message` is a prompt-level rule, not a hard schema validator**: the brief asks that it be null/empty when `should_follow_up` is false, but this is enforced only by instructing the model, not by a Pydantic cross-field check that would reject the response outright. Given what real local-model testing already showed with Lead Intelligence's `confidence` field (small models don't always follow instructions embedded only in a schema description), adding a strict validator here risked the same class of spurious `LLMInvalidOutputError` for a cosmetic inconsistency (a stray non-null message) rather than a real correctness problem (a wrong probability). `confidence`'s numeric range stays hard-enforced because an out-of-range confidence is actually meaningless; a redundant message alongside `should_follow_up=false` is just noise the advisor would immediately recognize as irrelevant.

### System prompt (`app/ai/prompts/follow_up.py`)

Deliberately not copied from Lead Intelligence's — written to this agent's actual job. Versioned via `FOLLOW_UP_PROMPT_VERSION` (`v1`). Instructs the model to: reason over the whole CRM context rather than a fixed "N days" rule (the same lead's silence can be normal or urgent depending on what else is happening); read `direction` (`inbound` vs `outbound`) on the last activity, since an unanswered outbound message means something different from an unanswered inbound one; tell a buyer (searching, or interested in one listing) from a seller (has a listing) and recommend accordingly (matching properties/viewing follow-up/negotiation prep for buyers; availability/documentation/interested-buyer updates for sellers); treat a `not_interested` property interest followed by a new `buyer_requirement` as one continuing lead, not a dead one; keep fact, inference, and recommendation distinct; write a short, grounded `suggested_message` only when `should_follow_up` is true; and never claim to contact anyone or take any action itself.

### API

`POST /ai/follow-up/{contact_id}` — identical auth, org-scoping, and error-handling shape as `/ai/lead-intelligence/{contact_id}` (`404` unauthorized/missing contact, `503` misconfigured provider, `504` timeout, `502` provider/invalid-output error — see [Lead Intelligence Agent](#lead-intelligence-agent)'s error table, unchanged here).

### Safety: recommendation-only

Same guarantee as Lead Intelligence, worth restating because this agent's whole subject is "what to say to the client": it can analyze and recommend a channel/action/message, but it cannot send anything, modify any contact/activity/property, change any status, or create any appointment. It has no tool besides the same read-only `get_lead_context`. Sending the suggested message (WhatsApp/email integration) is explicitly a future capability, not implemented here.

### Testing

`tests/test_follow_up_agent.py` (26 tests) — same fully-offline `FakeLLMProvider` pattern as Lead Intelligence's test file. Covers the schema (valid payload, null message on no-follow-up, confidence boundaries and out-of-range/percentage rejection, unknown channel/action/priority rejection), the agent (an active buyer with a stale contact; a recently-contacted lead needing no follow-up; the prompt carrying `direction` and `days_since_last_activity` rather than a precomputed verdict; Gabriela's rejected-interest-plus-new-requirement pattern reaching the prompt together; recent multi-activity engagement reflected in `activity_count`; a brand-new contact with no history still producing a valid context; 404 for a missing or cross-org contact with the LLM never called; every `LLMError` subtype propagating; and that no `Contact`/`Activity`/`BuyerRequirement` row is created, changed, or removed by running the agent), and the route (success, `503`/`504`/`502` for each failure mode, `404` cross-org).

`tests/test_follow_up_agent_ollama_integration.py` — the real-Ollama smoke test, gated the same way as Lead Intelligence's (`RUN_OLLAMA_INTEGRATION_TESTS=1` plus a live server; see that section above for why reachability alone isn't enough). Runs Carlos/Gabriela/Carolina/Sergio and checks only the structural contract (valid enum values, `confidence` in range, `recommended_channel="none"` whenever `should_follow_up` is false) — never a hardcoded expected conclusion.

## Pipeline Agent

The third real AI agent, built on exactly the same architecture as [Lead Intelligence Agent](#lead-intelligence-agent) and [Follow-up Agent](#follow-up-agent) — same `LeadContext`, same `LLMProvider` abstraction, same providers, same route/error-handling shape, same read-only guarantee. It answers a third, different question: not "how important is this lead" and not "does this lead need contact right now", but **"where does this contact's pipeline of Opportunities stand, and what does the advisor need to do about it?"**

| | Lead Intelligence | Follow-up | Pipeline |
|---|---|---|---|
| Question | "How important is this lead overall?" | "Does this lead need follow-up **right now**?" | "Where do this contact's **Opportunities** stand, and what needs attention?" |
| Schema | `LeadIntelligenceAnalysis` | `FollowUpRecommendation` | `PipelineAnalysis` |
| Prompt | `app/ai/prompts/lead_intelligence.py` | `app/ai/prompts/follow_up.py` | `app/ai/prompts/pipeline.py` (written from scratch, not derived from the other two) |
| Route | `POST /ai/lead-intelligence/{contact_id}` | `POST /ai/follow-up/{contact_id}` | `POST /ai/pipeline/{contact_id}` |

**Flow**: `CurrentUser → get_lead_context → LeadContext → LLMProvider → PipelineAnalysis → PipelineResult` — identical shape to the other two agents, reusing the same AI Tool. `PipelineAgent` (`app/ai/pipeline_agent.py`) never touches a repository or Supabase directly — `get_lead_context` is its only source of CRM data, exactly like the other two.

### Response schema (`app/schemas/pipeline.py`)

`PipelineAnalysis` — what the LLM produces: `overall_priority` (reuses `LeadPriority`), `summary`, `confidence` (`0.0`-`1.0`), and three lists reasoned about independently per Opportunity — never merged, never assuming the newest is the only one that matters (see [Opportunities / Pipeline](#opportunities--pipeline)'s own domain rule, now enforced at the prompt level too):

- `opportunities: list[OpportunityRecommendation]` — one entry per opportunity worth surfacing, each with its own `opportunity_id`, `priority`, `status_assessment` (a short factual sentence, not a fixed category — see below), `reason`, `recommended_action`, `confidence`.
- `immediate_actions: list[ImmediateAction]` — `opportunity_id`, `action`, `reason`, `urgency` (reuses `TaskPriority`'s four levels — low/medium/high/**urgent** — a closer fit for "how soon" than the three-level `LeadPriority`).
- `risk_flags: list[RiskFlag]` — `opportunity_id`, `risk` (a short factual description, not a fixed category), `reason`, `severity` (reuses `LeadPriority`, same three-value scale already reused for `FollowUpRecommendation.priority`).

`PipelineResult` wraps it with the same provenance fields as the other two agents (`contact_id`, `model`, `prompt_version`, `generated_at`) — **note the deliberate placement**: `contact_id` lives on `PipelineResult`, not inside `PipelineAnalysis`, even though the task brief that specified this schema suggested putting it there. Reasoning: the caller already knows which contact was analyzed (it's the function argument), so asking the LLM to also faithfully reproduce that single UUID only risks it being typo'd — exactly the same reasoning `LeadIntelligenceResult`/`FollowUpResult` already apply. `opportunity_id` on each nested item is different and does have to come from the model: a contact can have *several* opportunities, so the model must say which one each item is about; there's no wrapper-level equivalent for that. This is the one intentional schema deviation from the task's suggested field list, made to keep the same convention the other two agents already established — see the schema file's own docstring for the full reasoning.

**`status_assessment`/`risk` are free text, not enums, on purpose**: every categorical/actionable field here (`priority`, `recommended_action`, `severity`, `urgency`) is a strict soft enum, matching this codebase's established convention — but the situations an opportunity can be in, or a risk can describe, are genuinely varied ("active, no activity in 9 days despite an upcoming appointment" reads very differently from "won 2 days ago, no documentation task created yet"). Forcing either into a fixed category would itself be exactly the kind of arbitrary rule the brief asked this agent to avoid ("do not create hard-coded rules like '5 days always means cold'") — so both stay short factual sentences, the same treatment `reasoning`/`positive_signals`/`risk_signals` already get on `LeadIntelligenceAnalysis`.

**No hard-coded scoring**: `priority`/`overall_priority` are never computed from a formula (e.g. `expected_value × probability`) — the brief was explicit that the LLM makes the final reasoning from the combination of signals, not a mathematical score, and this codebase has no `ai_score` field anywhere to hang one on. The model sees every relevant raw signal (stage, expected_value, probability, expected_close_date, activity recency/direction, overdue tasks, upcoming appointments, historical stage changes via the timeline) and reasons over the combination itself.

### System prompt (`app/ai/prompts/pipeline.py`)

Written from scratch, not derived from the other two. Versioned via `PIPELINE_PROMPT_VERSION` (`v1`). Explicitly instructs the model to: reason only from the supplied JSON, never inventing facts, opportunities, or properties; distinguish fact from inference from recommendation; **never confuse Contact, Property, BuyerRequirement, and Opportunity** — a contact can have several opportunities over time and several at once, a lost opportunity doesn't mean the contact is lost, and a buyer can also be a seller; reason about every opportunity's *combination* of signals rather than any single field or a fixed day-count rule; only include an opportunity/action/risk when the data genuinely supports it (an opportunity with nothing concerning gets no risk flag; a contact with no opportunities gets empty lists); only recommend actions the available information actually supports (e.g. never `coordinate_notary` unless the data shows the deal is actually near contract/closing); and the same `confidence`-is-a-decimal-never-a-percentage rule as the other two agents.

### Agent (`app/ai/pipeline_agent.py`)

`PipelineAgent(db, llm).analyze(current_user, contact_id) -> PipelineResult` — same five-step shape as the task brief asked for and the other two agents already follow: resolve `CurrentUser` → `get_lead_context` → hand the context to `LLMProvider.generate_structured` → Pydantic validates the response against `PipelineAnalysis` → wrap as `PipelineResult`. `_MAX_TOKENS = 1536` here, higher than the other two agents' `1024`: this agent's output can include several nested opportunities/actions/risks (one item per Opportunity in the pipeline), not one single judgment — 1024 was measured too tight against real demo contacts with multiple opportunities (Fernando, Gabriela — see [Opportunities / Pipeline](#opportunities--pipeline)'s demo data).

### API

`POST /ai/pipeline/{contact_id}` — identical auth, org-scoping, error-handling shape, and `AgentExecution` persistence as the other two agents' routes (`404` unauthorized/missing contact, `503` misconfigured provider, `504` timeout, `502` provider/invalid-output error; every run, success or failure, recorded via the existing `_run_and_record` helper — see [AI Execution Persistence](#ai-execution-persistence) — with zero new persistence code needed for a third agent).

```bash
curl -X POST $API/ai/pipeline/$CONTACT_ID -H "Authorization: Bearer $TOKEN"
```

### Safety: read-only, by construction

Same guarantee as the other two agents, worth restating because this one's whole subject is the pipeline's own state: it can analyze and recommend, but it has no tool besides the same read-only `get_lead_context`, and nothing in `PipelineAgent`, the route, or the Gateway ever calls `OpportunityService`, `TaskService`, `AppointmentService`, or any other write path. No contact, property, opportunity, task, or appointment is ever modified; no opportunity stage is ever changed; no message is ever sent. A human advisor reads the recommendation and decides.

### Testing

`tests/test_pipeline_agent.py` (32 tests) — same fully-offline `FakeLLMProvider` pattern as the other two agents' test files. Covers the schema (valid payload, nested `OpportunityRecommendation`/`ImmediateAction`/`RiskFlag` items, confidence boundaries, unknown `overall_priority`/`recommended_action`/`severity` rejection), the agent (no opportunities; one active opportunity; multiple opportunities together — both ids reach the prompt; a won opportunity; a lost opportunity; an active and a lost opportunity together — the lost one doesn't disappear; an opportunity with an overdue task; one with an upcoming appointment; negotiation stage; offer stage; a "stale" scenario — an old `created_at` with zero activity, verified as raw facts reaching the prompt rather than a precomputed "stale" label, since staleness is the model's own judgment call, never a hard-coded rule; 404 for a missing/cross-org contact with the LLM never called; organization isolation, including a belt-and-suspenders check that another organization's opportunity id never appears in the prompt; every `LLMError` subtype propagating, including `LLMProviderError`; and that running the agent never changes the analyzed opportunity's own `stage`), and the route (success, `503`/`504`/`502` for each failure mode, `404` cross-org, and that a run is actually persisted as an `AgentExecution`).

`tests/test_pipeline_agent_ollama_integration.py` — the real-Ollama smoke test, gated exactly like the other two (`RUN_OLLAMA_INTEGRATION_TESTS=1` plus a live server). Runs Carlos/Gabriela/Carolina/Sergio and checks only the structural contract (valid enum values, every `confidence` — overall and per-item — in range) — never a hardcoded expected conclusion. See [Real Ollama validation results](#real-ollama-validation-results) below for an actual run's output.

### Real Ollama validation results

Captured by running `PipelineAgent` directly (not through the test suite) against a **fresh in-memory SQLite copy of the demo seed data** (`scripts/seed_demo_data.py`'s `run_seed`), with a genuinely local `llama3.2` served by `ollama serve` on this CPU-only dev machine — not a round-trip against the live Supabase project, and the real demo data was never touched. Each contact was run as its own isolated process so none competed with another for CPU; running two at once was tried first and measurably slowed both (see "Problems discovered" in the final report) — these numbers are the clean, uncontended baseline.

| Contact | Duration | Schema valid | Overall priority | Opportunities | Risk flags | Immediate actions | Confidence |
|---|---|---|---|---|---|---|---|
| gabriela-ortiz | 224.9s | ✅ | medium | 2 (1 lost, 1 active search) | 0 | 0 | 0.7 |
| carolina-reyes | 161.3s | ✅ | high | 1 (negotiation) | 0 | 0 | 0.95 |
| carlos-mendoza | 232.8s | ✅ | medium | 1 (qualification, flagged "stale") | 1 (stale, medium severity) | 1 (follow_up, high urgency) | 0.85 |
| sergio-navarro | 175.3s | ✅ | high | 1 (won, closed) | 0 | 0 | 0.85 |

All four passed Pydantic validation against `PipelineAnalysis` on the first attempt — no retries, no manual correction. Qualitatively: Carlos's opportunity (no `expected_close_date`, an overdue task, 3 days since last activity) is the one the model flagged with both a risk (`stale`) and an immediate action (`follow_up`, `urgent`), which lines up with the raw signals in his context. Sergio's single opportunity is `won`/closed, and the model correctly recommended `monitor` rather than any sales action — a small but real confirmation that it's reading `stage`/`status` rather than pattern-matching "opportunity exists → recommend closing action." One rough edge worth flagging honestly: both Carolina's and Carlos's opportunities got `coordinate_notary` recommended — appropriate for Carolina (an active negotiation) but a stretch for Carlos (still in `qualification`, no offer yet) — the model's own stated `reason` for Carlos doesn't actually argue for that action, which is a real prompt-quality gap, not a schema or architecture problem; the field itself worked exactly as designed (free text you can audit against the recommendation).

## AI Gateway & Agent Registry

With three agents now built the same way, the part that was starting to repeat itself — timing, logging, and provider/version bookkeeping duplicated across each agent — moved into one small orchestration layer. This is *not* multi-agent orchestration or a message bus; it's a thin façade that makes the agents manageable and measurable.

```
STATE AI
     ↓
 AI Gateway  (app/ai/gateway.py)
     ↓
 ┌───────────────────┬───────────────────┬───────────────────┐
 Lead Intelligence      Follow-up            Pipeline           (looked up via app/ai/registry.py)
 └───────────────────┴───────────────────┴───────────────────┘
     ↓
 LLMProvider
     ↓
 Ollama / Anthropic
```

**Agent Registry** (`app/ai/registry.py`) — a plain module-level dict, `AGENT_REGISTRY: dict[str, AgentDescriptor]`, not a plugin system or anything reflection-based. Each `AgentDescriptor` carries `agent_id`, `name`, `description`, `version` (the agent's own implementation version — `LEAD_INTELLIGENCE_AGENT_VERSION`/`FOLLOW_UP_AGENT_VERSION`/`PIPELINE_AGENT_VERSION`, all `"v1"` today, distinct from the prompt's own version), `prompt_version` (imported from each agent's own prompt module, unchanged for the first two), `input_type`/`output_type` (the actual Pydantic classes — `LeadContext` in, `LeadIntelligenceResult`/`FollowUpResult`/`PipelineResult` out), and a `run` callable that builds and calls that specific agent. `get_agent(agent_id)` and `list_agents()` are the only two functions anything needs. Adding the Pipeline Agent meant adding exactly one more `AgentDescriptor` entry here — confirming the registry's own docstring claim ("adding a third agent... means adding one more `AgentDescriptor` entry here, never new machinery"): nothing else in the Gateway, the route helper, or `scripts/evaluate_agents.py` (already registry-driven — `--agents` defaults to every registered agent id) needed to change.

**AI Gateway** (`app/ai/gateway.py`) — `AIGateway(db, llm).run(agent_id, current_user, contact_id)` looks up the descriptor, calls it, times the whole call, and returns a `GatewayExecution(result, metadata)`. `ExecutionMetadata` is a small frozen dataclass: `agent`, `agent_version`, `prompt_version`, `provider`, `model`, `duration_ms`, `success` — never the `LeadContext`, never a credential, nothing persisted anywhere — no AI-execution database table exists or is planned until the architecture settles; this metadata is logging/evaluation-only for now. A `404` from context authorization (unknown/cross-org contact) propagates straight through *before* the gateway starts timing anything — it's an authorization outcome, not an AI execution one, so it's never logged as a "failed" run. Any `LLMError` subclass *is* logged (`ai_gateway.failed agent=... provider=... model=... duration_ms=... error=...`) and re-raised untouched, so `app/api/routes/ai.py`'s existing `LLMTimeoutError`/`LLMInvalidOutputError`/`LLMProviderError` → HTTP status mapping needed no changes.

**Agents got simpler, not more complex**: both `LeadIntelligenceAgent.analyze` and `FollowUpAgent.recommend` had their own `try/except LLMError` + `logger.warning`/`logger.info` + manual `time.monotonic()` timing removed — that's now the gateway's job, done once, uniformly, for every agent. Each agent is back to exactly its own reasoning: build the context, call `self.llm.generate_structured(...)`, shape the result. **The routes now go through the gateway** (`AIGateway(db, llm).run("lead_intelligence", ...)` / `.run("follow_up", ...)`) instead of instantiating an agent class directly — the route itself is unchanged in every other respect (same auth, same org-scoping, same error-to-HTTP-status mapping, same request/response shape). No provider selection logic moved: `_get_llm_provider`/`build_default_provider()` still decide *which* `LLMProvider` to hand the gateway, exactly as before (see [Lead Intelligence Agent's Provider selection](#provider-selection)) — the gateway only ever calls whatever `LLMProvider` it's given.

**Tests** (`tests/test_ai_gateway.py`, 13 tests, fully offline): the registry (all three agents present, correct descriptor fields for Lead Intelligence and Pipeline, an unknown `agent_id` raises `KeyError`), the gateway's happy path for all three agents (correct `GatewayExecution.result` type, correct metadata fields, metadata reflects whatever the *injected* provider identifies as — the gateway never decides this itself), every `LLMError` subtype propagating unmodified, a `caplog`-verified warning log on failure, a `caplog`-verified *absence* of any gateway log line when a `404` happens instead, and an unregistered `agent_id` raising before the LLM is ever called.

## Agent Evaluation

Comparing prompts, models, and providers needs a way to run the agents against known contacts and see what comes back — without ever pretending an AI's judgment call can be graded "correct" by code. Two separate pieces, kept deliberately apart:

### Golden test cases (`tests/test_golden_contacts.py`)

Fully offline, no LLM involved — these assert only deterministic CRM facts about Carlos, Gabriela, Carolina, and Sergio, built straight from `LeadContextService` (the exact same data an agent's prompt is built from): Carlos has an active buyer requirement and recent activity; Gabriela's rejected property interest *and* her later active buyer requirement are both still present and correctly ordered (the transition this whole context layer exists to preserve); Carolina has a `negotiation`-status property interest and a `negotiation` activity; Sergio's old (`cancelled`) and new (`active`) buyer requirements are both visible. If a future change to the seed data, `LeadContextService`, or the `LeadContext` schema ever silently dropped one of these facts, this file catches it in the normal fast offline suite — *before* it could show up as a hallucination or context-loss bug in a real agent run. This file makes no claim at all about what an LLM should conclude from these facts.

### Real-model evaluation (`scripts/evaluate_agents.py`)

A standalone script — **not** a pytest test, **never** run by `uv run pytest` — that runs real agents through the real, currently-configured provider (`build_default_provider()`, respecting `LLM_PROVIDER`/`OLLAMA_MODEL`/`ANTHROPIC_MODEL` exactly like the API does) against the demo contacts, through the same `AIGateway` the API uses. For each `(agent, contact)` pair it records `agent`, `contact`, `provider`, `model`, `agent_version`, `prompt_version`, `duration_ms`, `schema_valid`, and the full structured `output` — then prints it, and optionally writes the full set to a JSON file. It never declares an answer "correct": that judgment (or any deterministic fact-check) belongs in the golden tests above, kept intentionally separate from schema/execution validity here.

```bash
uv run python scripts/evaluate_agents.py                                    # every registered agent x all four demo contacts
uv run python scripts/evaluate_agents.py --agents lead_intelligence         # one agent
uv run python scripts/evaluate_agents.py --contacts carlos-mendoza          # one contact
uv run python scripts/evaluate_agents.py --output eval_results.json         # also save full results as JSON
```

Comparing across models/providers today means re-running this after changing `OLLAMA_MODEL` (or `LLM_PROVIDER`/`ANTHROPIC_MODEL`) and comparing the two output files — there is no automatic comparison or scoring built in, on purpose — the goal is to gather real data before making an infrastructure decision, not to pre-judge one.

**Performance, measured, not assumed** (CPU-only Intel Core i7-1065G7, ~12 GB RAM, no GPU): with `llama3.2` (3B), each `(agent, contact)` run took roughly **2-2.5 minutes**, occasionally longer for a contact with a larger context (Carlos's Follow-up run needed a 240s ceiling instead of 180s during real testing — see that test file's comment). Both agents together against all four demo contacts is a **~20-25 minute** sweep. `llama3.1` (8B) was tried first and was markedly worse on this hardware — several minutes per call, sometimes exceeding a 300s timeout outright — which is why `llama3.2` is the current default (see [Model configuration](#model-configuration)). This is real, measured data point toward a future decision (GPU infrastructure, a different local model, or routing specific agents to Anthropic) — no such decision has been made yet.

## Audit Logging

"Who changed what, when" for CRM data — a real production-readiness gap the core CRUD modules shipped without. `audit_logs` (`app/models/audit_log.py`) captures `organization_id`, `actor_user_id` (nullable, `SET NULL` — a deleted user account never erases the historical fact that *someone* acted), `entity_type`/`entity_id`/`action` (freeform strings, not a soft-enum `Literal`, deliberately: every future module adds its own entity/action pair and this table must accept that without a code change here), and `before_data`/`after_data` (JSONB on Postgres, plain JSON on SQLite via `.with_variant()` — the test DB).

**One reusable write path, not duplicated per route**: `app/services/audit_service.py`'s `AuditService.record(...)` is the only place that writes to this table. A Service method (never a route) calls it around its own existing create/update/delete, in the *same* unit of work — `AuditService.record` deliberately doesn't call `db.commit()` itself, so the audit row and the change it describes commit (or roll back) together. Wired in today for `Contact`, `Property`, `BuyerRequirement`, `Activity` (create only — no update/delete route exists for it), `Task`, `Appointment`, and `Opportunity` (whose stage changes get specifically-named actions — `OPPORTUNITY_WON`/`OPPORTUNITY_LOST`/`OPPORTUNITY_REOPENED`/`OPPORTUNITY_STAGE_CHANGED` — see [Opportunities / Pipeline](#opportunities--pipeline)); a future module follows the same one-line-per-service-method pattern rather than inventing its own.

Snapshots are built from each entity's own `*Read` Pydantic schema (`ContactRead.model_validate(contact).model_dump(mode="json")`), never the raw ORM `__dict__` — so a field already excluded from that entity's API response (there are none sensitive today) is excluded here the same way, not via a second exclusion list. No credential, token, or password ever appears in any snapshot, because none of the audited entities have such a field to begin with.

Read-only from the API: `GET /audit-logs` (filterable by `entity_type`/`entity_id`) and `GET /audit-logs/{id}`, both organization-scoped like everything else — there is no create/update/delete route, since nothing outside `AuditService` should ever write here.

## AI Execution Persistence

Every agent (Lead Intelligence, Follow-up, and — added later — Pipeline) has been read-only/advisory from day one; that doesn't change here or with any of them. What was missing was any record of *what they said*: "what did the AI recommend for this lead, when, which agent, did it work, did anyone act on it." `agent_executions` (`app/models/agent_execution.py`) now answers that.

**Deliberately NOT written from inside `AIGateway`**: the Gateway's own docstring states it "never touches the database or Supabase directly," and that stays true. Persistence happens in `app/api/routes/ai.py`'s `_run_and_record` helper — one function shared by all three agent routes, called right around the existing `AIGateway(db, llm).run(...)` call, exactly the same layer that already owned mapping `LLMError` subclasses to HTTP status codes. When the Pipeline Agent was added later, its route called this same helper unchanged, exactly as this section originally predicted.

- **Success** records `agent_name`, `agent_version`, `contact_id`, `user_id`, `provider`, `model`, `duration_ms` (from the Gateway's own `ExecutionMetadata` — already accurate, no extra timer needed), and `output` (the agent's full structured result, dumped as JSON).
- **Failure** (`LLMTimeoutError`/`LLMInvalidOutputError`/`LLMProviderError`) still records a row — `status="failed"`, `output={"error": "<exception class>", "message": "..."}` — timed by the route itself since no `GatewayExecution` exists to read a duration from.
- **A `404` from context authorization is not recorded**, matching the Gateway's own documented behavior: an unknown/cross-org `contact_id` is an authorization outcome, never an AI execution one.
- `input_snapshot` exists as a column but is intentionally left `NULL` today — the `LeadContext` an agent read is already deterministic and reconstructible on demand via `GET /ai/lead-context/{contact_id}`, so storing a full duplicate on every single execution wasn't judged worth the extra write/storage yet.
- `human_action`/`human_action_at` (soft enum: `acted_on`/`dismissed`) let an advisor record whether they did anything with a recommendation, via `PATCH /ai/agent-executions/{id}` — the only client-writable field on this table.

`GET /ai/agent-executions` (filterable by `contact_id`/`agent_name`) and `GET/PATCH /ai/agent-executions/{id}` are organization-scoped like everything else. This remains pure observability: nothing here lets an agent write CRM data, and a failed AI call is still logged, not swallowed.

## Tasks & Reminders

`tasks` (`app/models/task.py`) — "something that needs to happen": a follow-up call, a document deadline, a notary reminder, an AI recommendation a human turned into concrete work. **Deliberately distinct from `Activity`** ("something that already happened") — completing a Task never auto-creates an Activity; a human decides whether the outcome is worth logging as one.

`task_type` (soft enum: `follow_up`/`call`/`showing`/`document`/`contract`/`notary`/`payment`/`commission`/`other` — several of these exist for modules that don't yet, so a Task can already reference them), `status` (`pending`/`in_progress`/`completed`/`cancelled`), `priority` (`low`/`medium`/`high`/`urgent`), `due_at` (required — every task has a deadline), `completed_at` (nullable, auto-stamped server-side when `status` is set to `completed` without an explicit value). Optionally associated with a `contact_id`/`property_id`/`buyer_requirement_id`/`property_interest_id` (all `CASCADE` on delete — a task about something that no longer exists stops being actionable, unlike an Activity's historical record) and/or an `opportunity_id` (`SET NULL` instead — see [Opportunities / Pipeline](#opportunities--pipeline)) — every one of these is validated against the caller's own organization before the task is created, never trusted blindly. `assigned_to_user_id`/`created_by_user_id` are `SET NULL` — an unassigned task is still a valid backlog item, and deleting a user account shouldn't delete task history.

`GET/POST /tasks` (filterable by `status`/`priority`/`assigned_to_user_id`/`contact_id`/`property_id`/`opportunity_id`), `GET/PATCH/DELETE /tasks/{id}`.

## Appointments

`appointments` (`app/models/appointment.py`) — a scheduled/planned event: "this showing is booked for Tuesday at 4pm." **Deliberately distinct from both `Activity`** (what happened) **and `Task`** (an open action item with no fixed time) — an Appointment doesn't become an Activity automatically once it occurs; a human logs the outcome as an Activity separately, matching the intended flow: *agent creates appointment → occurs → Activity records the outcome*.

`appointment_type` (`showing`/`call`/`meeting`/`notary`/`signing`/`other`), `status` (`scheduled`/`confirmed`/`completed`/`cancelled`/`no_show`), `start_at`/`end_at` (both required, `CHECK (start_at <= end_at)` at the DB level *and* re-validated at the service layer against the merged row on a partial update — checking before the repository's flush, not after, so the friendly 422 fires instead of the DB constraint surfacing as a generic 409). `contact_id` is `CASCADE` (mirrors `PropertyInterest`); `property_id` and `opportunity_id` are both `SET NULL` (mirrors `Activity.property_id`'s exact reasoning — deleting a property, or an opportunity, must not erase the historical fact that an appointment happened there).

`external_calendar_event_id`/`external_calendar_provider` exist so a future real calendar sync has somewhere to record "this is already mirrored externally as event X" — both `NULL` today; nothing populates them yet (see [Calendar Integration Architecture](#calendar-integration-architecture)). This PropPilot row is always the source of truth, never the external calendar.

`GET/POST /appointments` (filterable by `status`/`contact_id`/`property_id`/`opportunity_id`/`assigned_to_user_id`/`start_from`/`start_to`), `GET/PATCH/DELETE /appointments/{id}`.

## Notifications Architecture

The shape: `Task.due_at` / `Appointment.start_at` → a scheduled detector → a `Notification` row → a delivery channel. **The first three steps are real as of Phase 5 — see [Automation (Phase 5)](#automation-phase-5) for the detector/scheduler that now produces these. Only the last step (delivery beyond this in-app record) remains future work.**

`notifications` (`app/models/notification.py`): `type` (soft enum — `task_due`/`appointment_upcoming`/`follow_up_reminder`/`document_deadline`/`contract_deadline`/`system`), `title`, `body`, an optional freeform `related_entity_type`/`related_entity_id` pointer (same pattern as `AuditLog`, for the same reason — any future module can point a notification at its own rows without a schema change), and `read_at`.

**What's real**: `NotificationService.create(...)` and the record itself, now with a real producer (`app/automation/`, not just tests). A notification is *personal*, not just organization-scoped — `GET /notifications` only ever returns the caller's own (verified by `user_id`, not just `organization_id` — another org member, even an owner/admin, cannot read or mark someone else's), and `PATCH /notifications/{id}` (`{"read": true/false}`) is the only mutation. The real frontend now has a Notification bell (`components/layout/notification-bell.tsx`) consuming both.

**What's explicitly NOT implemented**: there is still no `POST /notifications` route (a client should never fabricate a notification for anyone, including themselves — only this backend's own services decide someone gets notified, and as of Phase 5 that's specifically `app/automation/actions.create_notification`) and no `DELETE /notifications/{id}` (same append-only-ish philosophy as `AuditLog`/`Activity` — a notification's `related_entity_id` can go stale if that entity is later deleted, since the pointer isn't a real foreign key; see [What's next](#whats-next)). There is also still no delivery channel beyond this in-app record: email, push, and SMS/WhatsApp are all future work, each its own integration the way [Calendar Integration Architecture](#calendar-integration-architecture) is being prepared.

## Automation (Phase 5)

Controlled, event-driven automation — `app/automation/`. The full loop this phase actually built: `EVENT → DETECT → CONTEXT → RULE → ACTION → AUDIT → NOTIFICATION`, using only real, already-existing infrastructure — no new database tables, no new pipeline stages.

**The rule this whole package exists to enforce**: automation never gets arbitrary repository/API access. Not "AI can call any endpoint" — instead, exactly four named, approved functions in `app/automation/actions.py`:

- `create_task(...)` — a thin, validated, already-audited call into `TaskService.create`.
- `create_activity(...)` — same, into `ActivityService.create`.
- `create_notification(...)` — the one wrapper with real logic of its own: deduplication (see below), plus its own explicit `NOTIFICATION_CREATED` audit entry (unlike `NotificationService.create` itself, which has no other caller and no audit trail of its own).
- `update_opportunity_stage(...)` — built and tested, but **not called by anything automated in this phase**. Moving a deal remains exclusively a human action through the existing `StageSelector` UI and `PATCH /opportunities/{id}`.

**Detectors** (`app/automation/detectors.py`) — two, both plain, deterministic, read-only queries; neither needs an LLM call ("is this task's due_at in the past" is not a judgment call):

- `detect_overdue_tasks` — any task with `due_at` in the past and `status` not `completed`/`cancelled`. Every task has a required `assigned_to_user_id`, so there is always a real recipient.
- `detect_upcoming_appointments` — any `scheduled`/`confirmed` appointment starting within `UPCOMING_APPOINTMENT_WINDOW` (24h, a plain documented constant). An appointment with no `assigned_to_user_id` (that field is optional, unlike Task's) is skipped rather than guessing a recipient.

Both take `organization_id` and an explicit `now` parameter (never computed internally), so every boundary is testable with a controlled clock, and both only ever act through `create_notification`.

**Deduplication** — the single most important property here: running a detector any number of times, at any interval, must never create a duplicate notification for the same event. Enforced by `NotificationRepository.exists_for_related_entity`: one `(user, type, related_entity_type, related_entity_id)` triple ever gets a notification, full stop — not "one per day," not "one per detector run," and not reset by the user marking it read (a dismissed notification about a still-overdue task must not reappear).

**The scheduler** (`app/automation/scheduler.py`) — the one genuinely new piece of infrastructure this phase adds, and only after checking whether the existing runtime already had something to reuse (it didn't: one FastAPI process, sync SQLAlchemy, no async event loop framework, no Celery/Redis/Kafka/pg_cron anywhere in this project). `APScheduler`'s `BackgroundScheduler` runs `run_all_organizations_once` every 5 minutes on a background thread inside this same process — no new service to deploy. Each organization gets its own DB session; one organization's failure is logged and skipped, never allowed to stop another's. Started/stopped via a FastAPI `lifespan` context in `app/main.py` (not at import time, so `pytest` never spins up a background thread scanning an in-memory test database).

**Appointment outcomes** (User Story F/K) — `AppointmentUpdate.outcome_notes` (`app/schemas/appointment.py`) is not a real column; sending it alongside `status: "completed"` makes `AppointmentService.update` create one real `Activity` from it via `create_activity` instead of storing the text a second time. That Activity is then real context for `LeadContextService`/`get_lead_context` — automatically visible to the Follow-up and Pipeline agents, with no changes needed to either.

**Post-sale follow-up** (Part 9) — no new `post_sale` pipeline stage. `OpportunityService._maybe_create_post_sale_task`, triggered from the same stage-change hook that already records the stage-change `Activity`, creates one real Task (`POST_SALE_FOLLOW_UP_DAYS = 30`, a plain documented constant) whenever an opportunity reaches `won`. Assigned to the opportunity's own `owner_user_id` (or whoever closed it); skipped — logged, not raised — only in the rare case neither is known, so a missing post-sale task never blocks the Won transition itself.

**Autonomy levels implemented**: Level 1 (a detector surfaces something for a human to act on — e.g. Follow-up Agent's existing recommendation, unchanged) and Level 2 (a deterministic rule performs one additive, reversible, fully-audited CRM write: a task, an activity, or a notification). **Not implemented**: Level 3 (an agent deciding and executing multi-step actions on its own) — see [What's next](#whats-next).

## Calendar Integration Architecture

Prepared, not implemented — per the explicit instruction not to build fake integrations. `app/integrations/calendar/base.py` defines `CalendarProvider`, a `Protocol` with the operations a real integration would need: `create_event`, `update_event`, `delete_event`, `list_events`, `refresh_token`. `google.py`/`apple.py`/`notion.py` each implement that Protocol's shape but every method raises `CalendarIntegrationNotImplementedError` — no real Google/Apple/Notion API call exists anywhere in this codebase, and nothing calls these classes today (no route, no service, no scheduled job).

**Design principle this package protects**: a PropPilot `Appointment` row is always the source of truth. An external calendar is a synchronization *target* — something an Appointment gets mirrored to — never the other way around, and never something the app depends on to function.

`calendar_connections` (`app/models/calendar_connection.py`) records a user's *intent* to connect a provider — `provider` (`google`/`apple`/`notion`), `status` (`pending`/`connected`/`expired`/`error`/`disconnected` — never actually reaches `connected` today, since there's no OAuth flow to get it there), `external_account_id`, `scopes`, `expires_at`. **It has no `access_token`/`refresh_token` columns.** Storing a real OAuth token needs encryption at rest (pgcrypto, envelope encryption via a KMS, or app-level encryption with a securely-managed key) — none of that exists in this codebase (no `cryptography` dependency, no key management), so per this project's own security rules, that column is omitted rather than implemented as insecure plaintext storage. `POST /calendar-connections` only ever registers this metadata row (upserting on `(user_id, provider)` — reconnecting updates the existing row rather than duplicating it); it never performs an OAuth handshake. `GET`/`DELETE` are scoped to the caller's own connections, the same personal-ownership pattern as Notifications.

**To make this real**, in order: (1) pick and stand up a token-encryption approach, (2) add `access_token`/`refresh_token` columns using it, (3) implement the OAuth authorization-code flow per provider, (4) implement one `CalendarProvider` subclass for real, starting with Google (most likely first). None of that is started here.

## Authorization Model

Roles (`owner`/`admin`/`agent`, on `users.role`) existed since the very first migration but were never enforced anywhere — every authenticated org member could do anything any other member could. `app/core/security.py` now adds `require_role(*roles)` (aliased as `require_any_role` — the same function; "any of these roles" already generalizes the single-role case), a dependency *factory* layered on top of `get_current_org_user` (which still runs first, so an unauthenticated or unprovisioned caller still gets 401/403 for that reason first): `Depends(require_role("owner", "admin"))` 403s unless the caller's role matches.

**Applied today to exactly one category of action: deleting a Contact, Property, Buyer Requirement, or Property Interest** — restricted to `owner`/`admin`. Every create/update/read/list operation, and every sub-resource action (roles, features, locations), stays open to any authenticated org member — this is *not* a general RBAC matrix, and normal day-to-day CRM work was deliberately left unrestricted. Tasks, Appointments, and Calendar Connections are likewise unrestricted (routine CRM work, same category as the entities above before deletion specifically was called out as the destructive case worth gating).

**Nothing else is gated today because nothing else in this codebase yet warrants it** — there is no Transactions/Commissions module and no Organization-settings/User-management route to protect. `require_role`/`require_any_role` is the exact mechanism those future modules should use (`dependencies=[Depends(require_role("owner"))]` on a route, or as a parameter dependency where the resolved `CurrentUser` is also needed) — adding one is a one-line change per route, not new machinery.

## Error Handling

Every error response — validation, not-found, forbidden, a conflicting write, or a genuine bug — now has the same shape:

```json
{"error": {"code": "NOT_FOUND", "message": "Contact not found.", "request_id": "..."}}
```

instead of whatever shape happened to bubble up (FastAPI's default `{"detail": ...}`, a raw SQLAlchemy traceback, an unhandled 500 with no body at all). `app/core/errors.py` has two parts: `RequestIDMiddleware` stamps a fresh UUID onto every request (`request.state.request_id`, also returned as the `X-Request-ID` response header — the value to hand a user asking "what happened?" so it can be found in the server logs), and `register_exception_handlers` maps every exception type this app can raise into that envelope:

- `HTTPException` → the same status code as before (404/403/422/502/503/504/...), now in the shared shape.
- `RequestValidationError` (a malformed body/query, or a failed Pydantic `model_validator` like `ContactBase`'s email-or-phone check) → 422, with a `message` naming which field(s) failed.
- `IntegrityError` (a database constraint rejected the write — e.g. a race-condition double-submit past an in-memory duplicate check) → 409, generic message. **Never echoes the raw exception**: it can contain literal SQL and values.
- Anything else (a genuine bug) → 500, generic message. The real exception and full traceback go to the server log only (`logger.exception(...)`), never the response.

Never leaked to a client, under any of these paths: a stack trace, raw SQL, a filesystem path, or any exception detail beyond the short, safe message.

## Security considerations

- **JWT verification is the real security boundary here** — not the frontend's `proxy.ts` (documented there as optimistic-only). Every protected route depends on `get_current_org_user`, which cryptographically verifies the token against Supabase's own public keys.
- **No `service_role` key anywhere in this codebase.** JWKS verification only needs public keys. If a future feature needs the Supabase Admin API, that key must live only in this backend's own environment (never `NEXT_PUBLIC_*`, never in the frontend).
- **Tenant isolation is enforced server-side on every query** (`organization_id` from the verified token, never taken from client input) — not left to the client to get right.
- **`DATABASE_URL` contains your database password** — never commit a real value; only `.env.example` (placeholders) is tracked. `.env` is gitignored.
- **No Row Level Security yet.** Isolation is enforced in the application layer (services/repositories), not via Postgres RLS — this backend connects with a single pooled role, not per-user Postgres sessions, so RLS would need a different connection strategy (`SET LOCAL` per-request claims) to be meaningful. A reasonable future hardening layer, not implemented in Phase 1.
- **No sensitive financial data stored** — no bank account numbers, passwords, or credit card details anywhere in this schema, per the project brief. `financing_type`/`preapproval_status` are coarse status fields only.
- **`ANTHROPIC_API_KEY` is a secret like `DATABASE_URL`** — never commit a real value; only `.env.example` (placeholder) is tracked. With the default `LLM_PROVIDER=ollama`, this key isn't needed or read at all.
- **Neither LLM provider ever gets database credentials, Supabase credentials, auth tokens, or user passwords** — organization authorization happens in `get_lead_context` *before* any data reaches `LeadContext`, and `LeadContext` itself already excludes that class of field (see [AI Context Layer](#ai-context-layer)). Whether the model runs on Anthropic's servers or entirely on your own machine via Ollama, it has no database access, direct or otherwise, and cannot choose or run any query.
- **AI agents remain read-only/advisory.** Every recommendation is now persisted (`AgentExecution` — see [AI Execution Persistence](#ai-execution-persistence)) so it's observable and auditable, but nothing in this codebase lets an agent write CRM data, send a message, or create a task/appointment on its own.
- **No OAuth token is stored anywhere.** `calendar_connections` has no `access_token`/`refresh_token` column on purpose — see [Calendar Integration Architecture](#calendar-integration-architecture) for why, and what real token storage would require before it's added.
- **Errors never leak internals.** No stack trace, raw SQL, filesystem path, or exception detail beyond a short, safe message ever reaches a client — see [Error Handling](#error-handling). Every error response carries a `request_id` for correlating with the (server-side-only) full detail in the logs.
- **Role authorization exists for the one destructive action category that needed it today** (deleting Contacts/Properties/Buyer Requirements/Property Interests — `owner`/`admin` only) via a reusable `require_role` dependency — see [Authorization Model](#authorization-model). Not a full RBAC matrix; normal CRUD stays open to any authenticated org member.

## What's next

- Sales Copilot ("what should I work on today across my whole book of business", not one contact at a time) — deliberately not built yet. The Pipeline Agent (see [Pipeline Agent](#pipeline-agent)) answers "where does *this contact's* pipeline stand"; Sales Copilot would need to reason across *many* contacts' pipelines at once, which is a different context-assembly problem (today's `LeadContext`/`get_lead_context` are both scoped to one contact by design) — not a bigger prompt, a genuinely different tool. Built the same way the other three agents were once that's designed: on top of the same `LLMProvider` abstraction, not a new pattern.
- Provider routing (e.g. routing specific agents to Anthropic while others stay on Ollama, or picking a provider per-request) — explicitly out of scope; `LLM_PROVIDER` remains one global setting for every agent.
- Empirically evaluating whether Lead Intelligence/Follow-up's real (non-test) output quality changes now that they can see Opportunity/Task/Appointment data — `scripts/evaluate_agents.py` exists for exactly this (and already picked up the Pipeline Agent automatically, being registry-driven); running it as a deliberate before/after comparison for the other two agents wasn't part of this task's scope.
- Cross-referencing the `opportunity_id`s a LLM returns in a `PipelineAnalysis` against the real ids it was actually given, and rejecting/flagging ones that don't match — today a syntactically-valid-but-wrong UUID (the model naming a real-looking id that isn't one of the contact's own opportunities) would pass Pydantic validation undetected. No agent in this codebase cross-validates returned ids against source data yet, so this wasn't added as a one-off just for Pipeline; worth revisiting if it's ever observed in practice — see [Pipeline Agent](#pipeline-agent) for whether real-Ollama validation runs happened to surface it.
- Actually sending the Follow-up Agent's `suggested_message` (WhatsApp/email integration) — deliberately out of scope; today's agent only recommends, a human sends it.
- ~~Wiring the frontend to Notifications~~ — done in Phase 5 (a real Notification bell, see the frontend's own README). Every real CRM entity now has a real frontend surface.
- A real production rollout decision for `LLM_PROVIDER` (Ollama is a local-dev choice, not a production one) — plus a third `LLMProvider` implementation (OpenAI/HuggingFace) if there's ever a real reason to compare providers beyond the two that already exist.
- A provider registry, if a third or fourth provider ever makes the current `if`/`elif` in `factory.py` awkward — not needed at two providers.
- Inviting a *second* person into an *existing* organization, and any organization-settings/team-management UI — `POST /me/organization` (see [Authentication](#authentication)) only covers a brand-new signup provisioning their own new organization as its owner; a real invite flow (and the role-management UI to go with it) is a separate, larger piece.
- Transactions, commissions, documents, notary/closing workflow — explicitly out of scope so far, but now with an Audit Log and a `require_role` mechanism already in place to enforce authorization/traceability on them from day one, per this project's own rule that financial/legal modules must use both.
- Real Google/Apple/Notion OAuth + token storage — see [Calendar Integration Architecture](#calendar-integration-architecture) for the exact ordered steps this needs (encryption at rest first, then the token columns, then the OAuth flow, then one real `CalendarProvider` implementation).
- ~~A scheduled job that scans `Task.due_at`/`Appointment.start_at` and calls `NotificationService.create` automatically~~ — done in Phase 5: `app/automation/` (an in-process APScheduler `BackgroundScheduler`, chosen specifically because this backend's actual runtime — one FastAPI process, sync SQLAlchemy, no existing job runner — had no Celery/Redis/Kafka/pg_cron to reuse and didn't need one). Runs every 5 minutes, organization-scoped, idempotent (see `app/repositories/notification_repo.py`'s `exists_for_related_entity` — one notification per (user, type, related entity), ever, regardless of how many times the detector runs). If organization/task/appointment volume ever makes a single in-process scheduler too slow, this is the natural point to move to a real worker — not needed yet.
- Notification delivery beyond the in-app record: email, push, SMS/WhatsApp — each its own future integration.
- Level 3 autonomy (an AI agent deciding and executing multi-step actions on its own — see [Automation (Phase 5)](#automation-phase-5)) — Phase 5 deliberately stayed at Level 1 (detect + recommend) and Level 2 (deterministic, additive, reversible writes only: creating a task/activity/notification). No detector or rule in this codebase calls `update_opportunity_stage` — a human always moves a deal through the existing `StageSelector` UI. Level 3 would need a policy layer deciding *which* of the four approved actions to take and in what order, and almost certainly a pipeline-wide (not one-contact-scoped) context — the same architectural gap already named above for Sales Copilot.
- Cross-referencing a Task/Appointment's `related_entity_id` on a Notification against whether that entity still exists — `related_entity_type`/`related_entity_id` is a freeform pointer (same convention as `AuditLog`), not a real foreign key, so deleting a Task/Appointment leaves any Notification that named it pointing at an id that no longer resolves. Harmless today (the frontend never tries to fetch that specific entity — `getNotificationLink` only ever links to the relevant list page, never a detail route built from that id) but worth a real decision later: a foreign key with `ON DELETE SET NULL`, or a cleanup job, rather than leaving it implicit.
- Broader role authorization once Transactions/Commissions/Organization-settings/User-management routes actually exist — `require_role` is ready, nothing to build there, just apply it.
- Row Level Security, once/if the connection strategy supports it (see [Security considerations](#security-considerations) — isolation is enforced at the application layer today).
- Async SQLAlchemy, if/when request volume justifies the added complexity — sync was the deliberate Phase 1 choice for simplicity.
- Transactions/Commissions, once built, should reference `Opportunity` the same way Activities/Tasks/Appointments now can (a nullable `opportunity_id`) — an Opportunity reaching `won` is the natural trigger point for a future Transaction to exist.
- A pre-existing, unrelated data-corruption issue was noticed (not introduced or fixed in this task): a handful of Spanish accented characters (e.g. "í", "ú", em dashes) in already-seeded demo data round-trip incorrectly through this specific Windows development machine's connection to the real Supabase Postgres database (confirmed present in older seed rows from before this task, and reproducible with brand-new writes too) — most accented characters (e.g. "á") are unaffected. Worth a dedicated investigation (likely a client/connection encoding setting) before this environment is used for anything demo-facing; out of scope here since it's environmental, not application logic, and pre-dates this task.
- A related but distinct environmental quirk, newly observed during Phase 5's live verification: `curl -d '<string with an em dash or accented character>'` on this same Windows/Git-Bash setup fails with a generic "There was an error parsing the body" 400 — not a backend bug (the request body genuinely arrives malformed), but a shell/tooling encoding issue passing multi-byte UTF-8 as a literal command-line argument. `curl --data-binary @file.json` with the JSON written to a real UTF-8-encoded file works correctly and was used as the workaround throughout that verification. Worth knowing if this comes up again; not investigated further since it's a local tooling quirk, not application code.

## Known environment note

This machine runs Node 20.17 for the frontend and Python 3.12.6 here — both fine for this phase. `uv` was not preinstalled and was added via `pip install uv` as the first setup step; anyone else setting this up should do the same (or use `uv`'s official standalone installer).
