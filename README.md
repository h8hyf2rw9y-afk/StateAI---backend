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
| GET | `/ai/lead-context/{contact_id}` | Internal/debug surface for the AI Context Layer — see below. |

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

The seam between the CRM's real data and the future AI agents (Lead Intelligence first, then Follow-up, Sales Copilot) — deterministic and non-LLM. Nothing in this layer calls Claude, OpenAI, or any other model; it only assembles data that already exists into a structure an agent can read.

**Required flow, and where each piece lives:**

```
AI Agent  →  AI Tool  →  Backend Service  →  Repository  →  Supabase
(future)     app/ai/     app/services/       app/repositories/
             lead_context_tool.py  lead_context_service.py   (existing, reused as-is)
```

- **Repository layer**: unchanged — `LeadContextService` composes the existing `ContactRepository`, `BuyerRequirementRepository`, `PropertyInterestRepository`, `ActivityRepository`, and `PropertyRepository`. No new repository methods were needed.
- **Backend Service** (`app/services/lead_context_service.py`): `LeadContextService(db).build(organization_id, contact_id, *, activity_limit=20)` — 404s the same way every other service does if the contact isn't found in that organization, then assembles a `LeadContext` (`app/schemas/lead_context.py`).
- **AI Tool** (`app/ai/lead_context_tool.py`): `get_lead_context(current_user, contact_id, db, *, activity_limit=20)`. This is the actual security boundary — it takes the **whole authenticated `CurrentUser`**, never a bare `organization_id`, so there is no parameter an agent (or a manipulated prompt) could supply to reach another organization's data: `CurrentUser` can only be constructed by `get_current_org_user` from a verified Supabase JWT (see [Authentication](#authentication)). A small `LEAD_CONTEXT_TOOL_SCHEMA` dict alongside it documents the tool's name/description/input shape for whoever wires up the actual agent framework later — descriptive metadata only, not wired to any SDK yet.

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

## Security considerations

- **JWT verification is the real security boundary here** — not the frontend's `proxy.ts` (documented there as optimistic-only). Every protected route depends on `get_current_org_user`, which cryptographically verifies the token against Supabase's own public keys.
- **No `service_role` key anywhere in this codebase.** JWKS verification only needs public keys. If a future feature needs the Supabase Admin API, that key must live only in this backend's own environment (never `NEXT_PUBLIC_*`, never in the frontend).
- **Tenant isolation is enforced server-side on every query** (`organization_id` from the verified token, never taken from client input) — not left to the client to get right.
- **`DATABASE_URL` contains your database password** — never commit a real value; only `.env.example` (placeholders) is tracked. `.env` is gitignored.
- **No Row Level Security yet.** Isolation is enforced in the application layer (services/repositories), not via Postgres RLS — this backend connects with a single pooled role, not per-user Postgres sessions, so RLS would need a different connection strategy (`SET LOCAL` per-request claims) to be meaningful. A reasonable future hardening layer, not implemented in Phase 1.
- **No sensitive financial data stored** — no bank account numbers, passwords, or credit card details anywhere in this schema, per the project brief. `financing_type`/`preapproval_status` are coarse status fields only.

## What's next

- The real AI agents (Lead Intelligence first, then Follow-up, Sales Copilot) — the AI Context Layer (`get_lead_context`, see above), Activities, and the deterministic `/matches` endpoint are the foundation they'll build on, not a replacement for them. This is the next phase: actually calling an LLM, prompt orchestration, and (if needed) RAG/embeddings — none of which exist in this codebase yet.
- Wire the frontend's `lib/api/*` to this backend instead of mock data.
- A self-service way to provision `users` rows (invites/onboarding) — right now it's a manual `INSERT`.
- Transactions, commissions, documents, notary/closing workflow (explicitly out of scope so far).
- Appointments — a separate module from Activities (future events vs. historical record); exists as mock data in the frontend already, not in this backend yet.
- Row Level Security, once/if the connection strategy supports it.
- Async SQLAlchemy, if/when request volume justifies the added complexity — sync was the deliberate Phase 1 choice for simplicity.

## Known environment note

This machine runs Node 20.17 for the frontend and Python 3.12.6 here — both fine for this phase. `uv` was not preinstalled and was added via `pip install uv` as the first setup step; anyone else setting this up should do the same (or use `uv`'s official standalone installer).
