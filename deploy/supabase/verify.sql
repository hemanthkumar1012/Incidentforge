-- Read-only checks; each row should say ok = true. Run as postgres after harden.sql.
SELECT 'every forge table has RLS enabled' AS check,
       coalesce(bool_and(c.relrowsecurity), false) AS ok
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'forge' AND c.relkind = 'r'
UNION ALL
SELECT 'anon/authenticated hold no table privileges in forge',
       NOT EXISTS (
         SELECT 1 FROM information_schema.role_table_grants
         WHERE table_schema = 'forge' AND grantee IN ('anon', 'authenticated', 'PUBLIC'))
UNION ALL
SELECT 'anon/authenticated cannot use schema forge',
       NOT has_schema_privilege('anon', 'forge', 'USAGE') AND NOT has_schema_privilege('authenticated', 'forge', 'USAGE')
UNION ALL
SELECT 'forge_app is not superuser and does not bypass RLS',
       NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = 'forge_app')
UNION ALL
SELECT 'forge_app search_path is forge',
       coalesce((SELECT bool_or(s = 'search_path=forge') FROM pg_db_role_setting d, unnest(d.setconfig) s
                 WHERE d.setrole = 'forge_app'::regrole), false);
