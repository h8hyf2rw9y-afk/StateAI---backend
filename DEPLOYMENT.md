# Backend deployment (Render)

The repository is ready to deploy as a single Docker web service through `render.yaml`.

## Required production variables

- `DATABASE_URL`: the existing Supabase Postgres connection string. Use the same database; do not create or import a second copy.
- `SUPABASE_URL`: the same Supabase project used by the frontend.
- `FRONTEND_ORIGINS`: the final Vercel origin, for example `https://state-ai-frontend.vercel.app`. Add localhost separated by a comma only when local development must remain allowed.
- `ALLOW_SELF_SERVICE_SIGNUP=false`: keeps registration invitation-only.
- `RENOVA_ENCRYPTION_KEY`: the exact current key. Changing or losing it makes previously encrypted NSS and credit numbers unreadable.
- `ANTHROPIC_API_KEY`: optional for authentication, required only when the hosted AI features use `LLM_PROVIDER=anthropic`.

Never copy these values into Git. Enter them in Render's environment settings.

## Data safety

The container runs `uv run alembic upgrade head` before starting FastAPI. Alembic applies only pending migrations and does not recreate the database. Take a Supabase backup before the first production deployment and verify `/health` after every deploy.

The service intentionally runs one application process because the project currently includes an in-process APScheduler instance.
