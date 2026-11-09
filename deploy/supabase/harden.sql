-- Run after `alembic upgrade head`, as `postgres`, and again after any migration that adds tables.
-- Idempotent. Defence in depth for the Data API: even if someone later exposes the `forge`
-- schema, these tables have RLS enabled with no policies (deny all) and no grants for the
-- Data API roles. forge_app owns the tables, so the application itself is unaffected.
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'forge' LOOP
    EXECUTE format('ALTER TABLE forge.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    EXECUTE format('REVOKE ALL ON TABLE forge.%I FROM PUBLIC, anon, authenticated', t.tablename);
  END LOOP;
END
$$;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA forge FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA forge FROM PUBLIC, anon, authenticated;
