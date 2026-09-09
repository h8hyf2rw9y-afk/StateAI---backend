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

🚧 **Foundational data model + Activities/Interactions**, live on the real Supabase Postgres database, seeded with realistic demo data, and covered by 40 passing tests. No FastAPI-side business workflows beyond CRUD + deterministic matching + activity logging exist yet: no transactions, commissions, documents, appointments, AI agents, or advanced automation. See [What's next](#whats-next).

## Core architectural principle

The schema is **not** built around a generic "Lead" entity. A **Contact** is the central person/entity; leads, buyer requirements, property interests, and (eventually) opportunities/transactions are relationships and processes involving a Contact over time. A person can hold multiple roles (buyer, seller, investor...) and have several buyer requirements across their relationship with the agency — the same Contact never needs to be recreated.

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
  main.py                  # FastAPI() instance, CORS, router registration
  core/
    config.py                 # pydantic-settings: DATABASE_URL, SUPABASE_URL, SUPABASE_JWT_AUD, FRONTEND_ORIGINS
    database.py                  # SQLAlchemy engine, SessionLocal, get_db() dependency
    security.py                     # JWT verification (get_current_claims) + org resolution (get_current_org_user)
    seed_data.py                       # initial rows for the roles/features catalog tables — single source
                                          # of truth for both the Alembic migration and the test fixtures
  models/                   # SQLAlchemy ORM models — one module per entity group (see Data model below)
    base.py                     # declarative Base, UUIDPKMixin, TimestampMixin/CreatedAtMixin
    external.py                    # a stub for Supabase's auth.users table (see Data model)
  schemas/                  # Pydantic Create/Update/Read models, one module per entity, plus:
    enums.py                    # every "soft enum" (see Data model) — single source of truth
    common.py                      # ORMModel base (from_attributes=True)
    matching.py                       # response shape for the /matches endpoint
  repositories/             # thin SQLAlchemy query classes, always organization_id-scoped (see base.py)
  services/                 # business logic on top of repositories (contact/property/buyer-requirement/
                               # property-interest CRUD + matching_service.py for Use Case 5)
  api/
    routes/                    # one module per resource (health, me, contacts, properties,
                                  # buyer_requirements, property_interests)
    router.py                     # aggregates routers under /api/v1 (health/  is mounted unversioned)
alembic/
  env.py                    # reads DATABASE_URL from app.core.config; excludes the `auth` schema from
                               # autogenerate (see Data model)
  versions/                 # one initial migration — every table below, plus roles/features seed data
tests/
  conftest.py               # in-memory SQLite (FK enforcement on) + a fake authenticated user, via
                               # FastAPI dependency_overrides — no live Supabase project needed to test
  test_security.py             # real JWT verification logic against a self-signed keypair
  test_schemas.py                 # soft-enum + min/max range validation
  test_contacts_api.py               # representative CRUD integration test (the pattern every entity follows)
  test_matching_api.py                  # Use Cases 1-5 end to end, including the matching hard filters
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
| `activities` | A structured, chronological record of what actually happened with a Contact (call, WhatsApp, viewing, offer, …) — `property_id` optional (only set when the activity is about a specific listing), `created_by_user_id` optional. `occurred_at` is a business timestamp (*when it happened*), separate from the inherited `created_at`/`updated_at` audit trail (*when the row was logged*) — the same split `property_interests` already uses via `first_contact_at`/`last_contact_at`. This is what replaces free-text `notes` as the CRM's real timeline; see [Activities](#activities). |

**The `auth.users` reference**: `app/models/external.py` defines a minimal `Table` stand-in for Supabase's own `auth.users` — not a real model, just enough for SQLAlchemy to resolve `users.id`'s foreign key against it (SQLAlchemy requires the referenced table to exist somewhere in its metadata graph, even for an external, unmanaged table). `alembic/env.py`'s `include_object` filter explicitly excludes anything in the `auth` schema from autogenerate, so migrations never try to create/alter/drop Supabase's own table.

**Catalog seeding**: `contact_roles`, `property_features`, and `buyer_requirement_features` all foreign-key into `roles`/`features`, so those two catalogs are seeded with their initial rows (`app/core/seed_data.py`) as part of the initial migration itself — nothing can reference a role/feature that doesn't exist yet.

## Activities

The CRM's actual timeline — "what happened with this contact" — as a normalized, queryable log instead of a free-text `notes` field. This is the primary context source future agents (Lead Intelligence, Follow-up, Sales Copilot) will read from.

**Fields, and what was deliberately left out**: `activity_type` (soft enum: `call`/`whatsapp`/`email`/`property_viewing`/`follow_up`/`meeting`/`note`/`offer`/`negotiation`), optional `direction` (`inbound`/`outbound`), required `contact_id`, optional `property_id`, optional `created_by_user_id`, required `occurred_at` + `notes`. No `status` — an Activity is something that *already happened*; it has no lifecycle (a future Appointments module, for things not yet happened, is where scheduling status belongs). No `subject` — one content field is enough for now. No speculative `metadata` JSON column. Activities are append-only (no `PATCH`/`DELETE` routes) — a real CRM history log isn't edited, a correction is a new entry.

Endpoints: `POST`/`GET /contacts/{id}/activities` (create; the timeline, oldest-first, filterable by `activity_type`/`occurred_from`/`occurred_to`), `GET /properties/{id}/activities` (most-recent-first), `GET /activities/{id}`.

## Demo data

`scripts/seed_demo_data.py` populates 20 fictional contacts spanning both ways a person enters the CRM (10 interested in a specific property, 10 with a buyer requirement — including the Property-Interest→not-interested→Buyer-Requirement transition case and a contact whose requirement changed over time), plus ~14 supporting properties and a chronological Activity timeline (2-5 entries) for every contact, under one dedicated **"State AI Demo Organization"**.

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
- **Not yet provisioned**: a real, valid Supabase session with no matching `users` row returns `403` (not `401` — the caller *is* who they say they are, they just can't use the CRM yet). There's no self-service "join an organization" flow yet; assign a `users` row manually for now (see [Local testing against a real session](#local-testing-against-a-real-session)).
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
2. `curl http://localhost:8000/api/v1/me -H "Authorization: Bearer <token>"` — expect `403` the first time (no `users` row yet).
3. Insert a `users` row for that Supabase user id manually (`INSERT INTO users (id, organization_id, role) VALUES ('<sub-from-the-403-or-jwt>', '<some-organization-id>', 'owner')`, creating an `organizations` row first if needed) — there's no API for this yet, by design (see [What's next](#whats-next)).
4. Repeat step 2 — now `200`, with your real name/email/provider.

## API

All endpoints below live under `/api/v1` and require `Authorization: Bearer <supabase-access-token>`, except `GET /health` (unauthenticated, outside `/api/v1`, for uptime checks).

| Method | Path | Notes |
|---|---|---|
| GET | `/me` | Whoami — see [Authentication](#authentication). |
| GET, POST | `/contacts` | List (paginated) / create. |
| GET, PATCH, DELETE | `/contacts/{id}` | |
| POST, DELETE | `/contacts/{id}/roles[/{role_key}]` | Assign / remove a role. |
| GET, POST | `/contacts/{id}/buyer-requirements` | List / create *for that contact* (Case B). |
| GET, POST | `/contacts/{id}/property-interests` | List / create *for that contact* (Case A). |
| GET, POST | `/contacts/{id}/activities` | Create / the contact's timeline (oldest first) — see [Activities](#activities). |
| GET, POST | `/properties` | |
| GET, PATCH, DELETE | `/properties/{id}` | |
| POST, DELETE | `/properties/{id}/features[/{feature_key}]` | What a property actually has. |
| GET | `/properties/{id}/activities` | Most-recent-first. |
| GET | `/buyer-requirements` | |
| GET, PATCH, DELETE | `/buyer-requirements/{id}` | |
| POST | `/buyer-requirements/{id}/locations` | Add a preferred area. |
| POST | `/buyer-requirements/{id}/features` | Tag a must-have/preferred/deal-breaker feature. |
| **GET** | **`/buyer-requirements/{id}/matches`** | **Use Case 5** — deterministic candidate properties (see below). |
| GET, PATCH, DELETE | `/property-interests/{id}` | |
| GET | `/activities/{id}` | |
| GET | `/ai/lead-context/{contact_id}` | Internal/debug surface for the AI Context Layer — see [AI Context Layer](#ai-context-layer). |
| POST | `/ai/lead-intelligence/{contact_id}` | Runs the Lead Intelligence Agent — see [Lead Intelligence Agent](#lead-intelligence-agent). |
| POST | `/ai/follow-up/{contact_id}` | Runs the Follow-up Agent — see [Follow-up Agent](#follow-up-agent). |

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

## AI Context Layer

The seam between the CRM's real data and the AI agents built on top of it — the [Lead Intelligence Agent](#lead-intelligence-agent) today, Follow-up and Sales Copilot later. This layer itself is deterministic and non-LLM: nothing here calls Claude, OpenAI, or any other model; it only assembles data that already exists into a structure an agent can read.

**Required flow, and where each piece lives:**

```
AI Agent  →  AI Tool  →  Backend Service  →  Repository  →  Supabase
(future)     app/ai/     app/services/       app/repositories/
             lead_context_tool.py  lead_context_service.py   (existing, reused as-is)
```

- **Repository layer**: unchanged — `LeadContextService` composes the existing `ContactRepository`, `BuyerRequirementRepository`, `PropertyInterestRepository`, `ActivityRepository`, and `PropertyRepository`. No new repository methods were needed.
- **Backend Service** (`app/services/lead_context_service.py`): `LeadContextService(db).build(organization_id, contact_id, *, activity_limit=20)` — 404s the same way every other service does if the contact isn't found in that organization, then assembles a `LeadContext` (`app/schemas/lead_context.py`).
- **AI Tool** (`app/ai/lead_context_tool.py`): `get_lead_context(current_user, contact_id, db, *, activity_limit=20)`. This is the actual security boundary — it takes the **whole authenticated `CurrentUser`**, never a bare `organization_id`, so there is no parameter an agent (or a manipulated prompt) could supply to reach another organization's data: `CurrentUser` can only be constructed by `get_current_org_user` from a verified Supabase JWT (see [Authentication](#authentication)). A small `LEAD_CONTEXT_TOOL_SCHEMA` dict alongside it documents the tool's name/description/input shape for whoever wires up an agent framework later — descriptive metadata only, not wired to any SDK. The Lead Intelligence Agent (below) is the first real caller of this tool.

**`LeadContext` (the schema)** is a typed tree, not concatenated text, so an agent's prompt-building code reads specific fields instead of parsing prose:

- `contact` — identity, role keys, source, preferred contact method.
- `buyer_requirements` — **all** of them, including `cancelled`/superseded ones, with their `locations`/`features`. Losing old rows would break the exact history this layer exists to preserve (e.g. Sergio Navarro's changed criteria in the demo data).
- `property_interests` — **all** of them, including `not_interested`. Same reasoning: Gabriela Ortiz's rejected-property-interest → active-buyer-requirement transition (Case A → Case B) only makes sense if both rows are visible together.
- `properties` — the de-duplicated set of properties referenced by those interests and activities.
- `activities` — the most recent `activity_limit` (default `20`), newest first.
- `timeline` — activities + property-interest/buyer-requirement creation events merged into one oldest-first list, the single "story so far" an agent can read start to finish instead of interleaving three lists itself.
- `engagement_summary` — `activity_count`, `last_activity_at`, `days_since_last_activity`, `has_active_buyer_requirement`, `active_property_interest_count`. Only objective aggregations of facts already in the data (a count, a max date, a day difference, a boolean) — deliberately **no** `ai_score`, `conversion_probability`, or "hot/warm/cold" label. Computing a fact is this layer's job; judging what it means is the future Lead Intelligence Agent's.

**Data minimization**: no password, auth token, API key, or other `users`/Supabase-auth field is ever included — the tool only touches CRM entities. `activity_limit` (default `20`, capped at `200` on the route) is the one context-size control in place now; the parameter/pattern is there so future limits (e.g. on `timeline`) are a small addition, not a redesign — the other lists are naturally small per contact and weren't limited yet, to avoid over-engineering ahead of real usage data.

**Why a route exists** (`GET /ai/lead-context/{contact_id}?activity_limit=`, under a new `/ai` prefix since more AI-layer endpoints are coming): it's how every other feature in this backend gets verified end-to-end against the real Supabase project rather than only unit-tested, it adds no security surface beyond what the tool itself already enforces (same `get_current_org_user` dependency as every other route), and it doubles as a low-risk "what would the AI see for this lead" debugging surface during development. It is not meant for the frontend UI.

**Tests** (`tests/test_lead_context.py`): a plain contact with no related data; a contact with a buyer requirement; one with a property interest; one with activities (and timeline ordering); one with both a property interest and a buyer requirement at once; Gabriela's Case A → Case B transition against the real seeded demo data (both rows present, correctly ordered, nothing lost or duplicated); organization isolation (the tool rejects a contact id from another organization with a 404, even though it was asked for by id); partial data (only activities, every list still well-formed); determinism (two back-to-back calls produce identical output apart from `generated_at`); and one HTTP-level smoke test for the route itself. Most call `LeadContextService`/`get_lead_context` directly rather than through HTTP — the whole point of this layer is to be testable without a running server or any agent framework.

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

## AI Gateway & Agent Registry

With two agents now built the same way, the part that was starting to repeat itself — timing, logging, and provider/version bookkeeping duplicated in both `LeadIntelligenceAgent` and `FollowUpAgent` — moved into one small orchestration layer. This is *not* multi-agent orchestration or a message bus; it's a thin façade that makes the two agents manageable and measurable before a third (Sales Copilot) arrives.

```
STATE AI
     ↓
 AI Gateway  (app/ai/gateway.py)
     ↓
 ┌───────────────────┬───────────────────┐
 Lead Intelligence      Follow-up          (looked up via app/ai/registry.py)
 └───────────────────┴───────────────────┘
     ↓
 LLMProvider
     ↓
 Ollama / Anthropic
```

**Agent Registry** (`app/ai/registry.py`) — a plain module-level dict, `AGENT_REGISTRY: dict[str, AgentDescriptor]`, not a plugin system or anything reflection-based. Each `AgentDescriptor` carries `agent_id`, `name`, `description`, `version` (the agent's own implementation version — new constants `LEAD_INTELLIGENCE_AGENT_VERSION`/`FOLLOW_UP_AGENT_VERSION`, both `"v1"` today, distinct from the prompt's own version), `prompt_version` (imported from each agent's own prompt module — `v2`/`v1` respectively, unchanged), `input_type`/`output_type` (the actual Pydantic classes — `LeadContext` in, `LeadIntelligenceResult`/`FollowUpResult` out), and a `run` callable that builds and calls that specific agent. `get_agent(agent_id)` and `list_agents()` are the only two functions anything needs. Adding a third agent later means adding one more `AgentDescriptor` entry here — nothing else changes.

**AI Gateway** (`app/ai/gateway.py`) — `AIGateway(db, llm).run(agent_id, current_user, contact_id)` looks up the descriptor, calls it, times the whole call, and returns a `GatewayExecution(result, metadata)`. `ExecutionMetadata` is a small frozen dataclass: `agent`, `agent_version`, `prompt_version`, `provider`, `model`, `duration_ms`, `success` — never the `LeadContext`, never a credential, nothing persisted anywhere — no AI-execution database table exists or is planned until the architecture settles; this metadata is logging/evaluation-only for now. A `404` from context authorization (unknown/cross-org contact) propagates straight through *before* the gateway starts timing anything — it's an authorization outcome, not an AI execution one, so it's never logged as a "failed" run. Any `LLMError` subclass *is* logged (`ai_gateway.failed agent=... provider=... model=... duration_ms=... error=...`) and re-raised untouched, so `app/api/routes/ai.py`'s existing `LLMTimeoutError`/`LLMInvalidOutputError`/`LLMProviderError` → HTTP status mapping needed no changes.

**Agents got simpler, not more complex**: both `LeadIntelligenceAgent.analyze` and `FollowUpAgent.recommend` had their own `try/except LLMError` + `logger.warning`/`logger.info` + manual `time.monotonic()` timing removed — that's now the gateway's job, done once, uniformly, for every agent. Each agent is back to exactly its own reasoning: build the context, call `self.llm.generate_structured(...)`, shape the result. **The routes now go through the gateway** (`AIGateway(db, llm).run("lead_intelligence", ...)` / `.run("follow_up", ...)`) instead of instantiating an agent class directly — the route itself is unchanged in every other respect (same auth, same org-scoping, same error-to-HTTP-status mapping, same request/response shape). No provider selection logic moved: `_get_llm_provider`/`build_default_provider()` still decide *which* `LLMProvider` to hand the gateway, exactly as before (see [Lead Intelligence Agent's Provider selection](#provider-selection)) — the gateway only ever calls whatever `LLMProvider` it's given.

**Tests** (`tests/test_ai_gateway.py`, 11 tests, fully offline): the registry (both agents present, correct descriptor fields, an unknown `agent_id` raises `KeyError`), the gateway's happy path for both agents (correct `GatewayExecution.result` type, correct metadata fields, metadata reflects whatever the *injected* provider identifies as — the gateway never decides this itself), every `LLMError` subtype propagating unmodified, a `caplog`-verified warning log on failure, a `caplog`-verified *absence* of any gateway log line when a `404` happens instead, and an unregistered `agent_id` raising before the LLM is ever called.

## Agent Evaluation

Comparing prompts, models, and providers needs a way to run the agents against known contacts and see what comes back — without ever pretending an AI's judgment call can be graded "correct" by code. Two separate pieces, kept deliberately apart:

### Golden test cases (`tests/test_golden_contacts.py`)

Fully offline, no LLM involved — these assert only deterministic CRM facts about Carlos, Gabriela, Carolina, and Sergio, built straight from `LeadContextService` (the exact same data an agent's prompt is built from): Carlos has an active buyer requirement and recent activity; Gabriela's rejected property interest *and* her later active buyer requirement are both still present and correctly ordered (the transition this whole context layer exists to preserve); Carolina has a `negotiation`-status property interest and a `negotiation` activity; Sergio's old (`cancelled`) and new (`active`) buyer requirements are both visible. If a future change to the seed data, `LeadContextService`, or the `LeadContext` schema ever silently dropped one of these facts, this file catches it in the normal fast offline suite — *before* it could show up as a hallucination or context-loss bug in a real agent run. This file makes no claim at all about what an LLM should conclude from these facts.

### Real-model evaluation (`scripts/evaluate_agents.py`)

A standalone script — **not** a pytest test, **never** run by `uv run pytest` — that runs real agents through the real, currently-configured provider (`build_default_provider()`, respecting `LLM_PROVIDER`/`OLLAMA_MODEL`/`ANTHROPIC_MODEL` exactly like the API does) against the demo contacts, through the same `AIGateway` the API uses. For each `(agent, contact)` pair it records `agent`, `contact`, `provider`, `model`, `agent_version`, `prompt_version`, `duration_ms`, `schema_valid`, and the full structured `output` — then prints it, and optionally writes the full set to a JSON file. It never declares an answer "correct": that judgment (or any deterministic fact-check) belongs in the golden tests above, kept intentionally separate from schema/execution validity here.

```bash
uv run python scripts/evaluate_agents.py                                    # both agents x all four demo contacts
uv run python scripts/evaluate_agents.py --agents lead_intelligence         # one agent
uv run python scripts/evaluate_agents.py --contacts carlos-mendoza          # one contact
uv run python scripts/evaluate_agents.py --output eval_results.json         # also save full results as JSON
```

Comparing across models/providers today means re-running this after changing `OLLAMA_MODEL` (or `LLM_PROVIDER`/`ANTHROPIC_MODEL`) and comparing the two output files — there is no automatic comparison or scoring built in, on purpose — the goal is to gather real data before making an infrastructure decision, not to pre-judge one.

**Performance, measured, not assumed** (CPU-only Intel Core i7-1065G7, ~12 GB RAM, no GPU): with `llama3.2` (3B), each `(agent, contact)` run took roughly **2-2.5 minutes**, occasionally longer for a contact with a larger context (Carlos's Follow-up run needed a 240s ceiling instead of 180s during real testing — see that test file's comment). Both agents together against all four demo contacts is a **~20-25 minute** sweep. `llama3.1` (8B) was tried first and was markedly worse on this hardware — several minutes per call, sometimes exceeding a 300s timeout outright — which is why `llama3.2` is the current default (see [Model configuration](#model-configuration)). This is real, measured data point toward a future decision (GPU infrastructure, a different local model, or routing specific agents to Anthropic) — no such decision has been made yet.

## Security considerations

- **JWT verification is the real security boundary here** — not the frontend's `proxy.ts` (documented there as optimistic-only). Every protected route depends on `get_current_org_user`, which cryptographically verifies the token against Supabase's own public keys.
- **No `service_role` key anywhere in this codebase.** JWKS verification only needs public keys. If a future feature needs the Supabase Admin API, that key must live only in this backend's own environment (never `NEXT_PUBLIC_*`, never in the frontend).
- **Tenant isolation is enforced server-side on every query** (`organization_id` from the verified token, never taken from client input) — not left to the client to get right.
- **`DATABASE_URL` contains your database password** — never commit a real value; only `.env.example` (placeholders) is tracked. `.env` is gitignored.
- **No Row Level Security yet.** Isolation is enforced in the application layer (services/repositories), not via Postgres RLS — this backend connects with a single pooled role, not per-user Postgres sessions, so RLS would need a different connection strategy (`SET LOCAL` per-request claims) to be meaningful. A reasonable future hardening layer, not implemented in Phase 1.
- **No sensitive financial data stored** — no bank account numbers, passwords, or credit card details anywhere in this schema, per the project brief. `financing_type`/`preapproval_status` are coarse status fields only.
- **`ANTHROPIC_API_KEY` is a secret like `DATABASE_URL`** — never commit a real value; only `.env.example` (placeholder) is tracked. With the default `LLM_PROVIDER=ollama`, this key isn't needed or read at all.
- **Neither LLM provider ever gets database credentials, Supabase credentials, auth tokens, or user passwords** — organization authorization happens in `get_lead_context` *before* any data reaches `LeadContext`, and `LeadContext` itself already excludes that class of field (see [AI Context Layer](#ai-context-layer)). Whether the model runs on Anthropic's servers or entirely on your own machine via Ollama, it has no database access, direct or otherwise, and cannot choose or run any query.

## What's next

- Sales Copilot, built the same way Lead Intelligence and Follow-up were: on top of the existing `get_lead_context` tool and the `LLMProvider` abstraction, not a new pattern.
- Actually sending the Follow-up Agent's `suggested_message` (WhatsApp/email integration) — deliberately out of scope; today's agent only recommends, a human sends it.
- Wiring the frontend to the Lead Intelligence and Follow-up agents' endpoints (deliberately not done yet — backend-only so far).
- A real production rollout decision for `LLM_PROVIDER` (Ollama is a local-dev choice, not a production one) — plus a third `LLMProvider` implementation (OpenAI/HuggingFace) if there's ever a real reason to compare providers beyond the two that already exist.
- A provider registry, if a third or fourth provider ever makes the current `if`/`elif` in `factory.py` awkward — not needed at two providers.
- Wire the frontend's `lib/api/*` to this backend instead of mock data.
- A self-service way to provision `users` rows (invites/onboarding) — right now it's a manual `INSERT`.
- Transactions, commissions, documents, notary/closing workflow (explicitly out of scope so far).
- Appointments — a separate module from Activities (future events vs. historical record); exists as mock data in the frontend already, not in this backend yet.
- Row Level Security, once/if the connection strategy supports it.
- Async SQLAlchemy, if/when request volume justifies the added complexity — sync was the deliberate Phase 1 choice for simplicity.

## Known environment note

This machine runs Node 20.17 for the frontend and Python 3.12.6 here — both fine for this phase. `uv` was not preinstalled and was added via `pip install uv` as the first setup step; anyone else setting this up should do the same (or use `uv`'s official standalone installer).
