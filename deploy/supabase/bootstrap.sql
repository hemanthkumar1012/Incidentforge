-- IncidentForge control plane on Supabase: one-time bootstrap.
--
-- Run ONCE as the project's `postgres` role (SQL editor or psql), BEFORE `alembic upgrade head`:
--   psql "$SUPABASE_ADMIN_URL" -v ON_ERROR_STOP=1 -v forge_pw="'<strong password>'" -f bootstrap.sql
--
-- Result: a private `forge` schema owned by a dedicated `forge_app` role. Supabase's Data API
-- (PostgREST) only exposes schemas listed in its settings, and `public` by default, so the
-- control plane is not reachable through the project's REST/GraphQL endpoints.

CREATE ROLE forge_app LOGIN PASSWORD :forge_pw NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- Lets the admin role create objects owned by forge_app (needed on Supabase, where
-- `postgres` is not a true superuser).
GRANT forge_app TO postgres;

CREATE SCHEMA IF NOT EXISTS forge AUTHORIZATION forge_app;

-- Alembic and the app create unqualified names; the first schema on the path receives them.
ALTER ROLE forge_app SET search_path = forge;

-- Nothing in this schema is for the Data API roles.
REVOKE ALL ON SCHEMA forge FROM PUBLIC;
REVOKE ALL ON SCHEMA forge FROM anon, authenticated;

-- Anything forge_app creates later is closed to the Data API roles by default.
ALTER DEFAULT PRIVILEGES FOR ROLE forge_app IN SCHEMA forge REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE forge_app IN SCHEMA forge REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE forge_app IN SCHEMA forge REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
