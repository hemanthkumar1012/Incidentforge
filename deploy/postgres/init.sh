#!/usr/bin/env bash
# Runs once, on first start of the Postgres container (docker-entrypoint-initdb.d).
#
# One database per trust boundary, one role per component:
#
#   database        owner         who else connects
#   shop            shop_app      lab_admin, forge_reader, forge_remediator (table grants in shop migration 0002)
#   lab             lab_admin     nobody (holds ground truth)
#   forge           forge_app     nobody
#   shop_validation sandbox_app   forge_app's validation runner, using sandbox_app credentials
#
# Table-level privileges are granted by the migrations that create the tables,
# not here, so they stay next to the schema they protect.
set -euo pipefail

for var in SHOP_DB_PASSWORD LAB_DB_PASSWORD FORGE_DB_PASSWORD FORGE_READER_DB_PASSWORD \
           FORGE_REMEDIATOR_DB_PASSWORD SANDBOX_DB_PASSWORD; do
  if [ -z "${!var:-}" ]; then echo "init.sh: $var must be set" >&2; exit 1; fi
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v shop_pw="$SHOP_DB_PASSWORD" -v lab_pw="$LAB_DB_PASSWORD" -v forge_pw="$FORGE_DB_PASSWORD" \
  -v reader_pw="$FORGE_READER_DB_PASSWORD" -v remed_pw="$FORGE_REMEDIATOR_DB_PASSWORD" \
  -v sandbox_pw="$SANDBOX_DB_PASSWORD" <<'SQL'
CREATE ROLE shop_app LOGIN PASSWORD :'shop_pw';
CREATE ROLE lab_admin LOGIN PASSWORD :'lab_pw';
CREATE ROLE forge_app LOGIN PASSWORD :'forge_pw';
CREATE ROLE forge_reader LOGIN PASSWORD :'reader_pw';
CREATE ROLE forge_remediator LOGIN PASSWORD :'remed_pw';
CREATE ROLE sandbox_app LOGIN PASSWORD :'sandbox_pw';

CREATE DATABASE shop OWNER shop_app;
CREATE DATABASE lab OWNER lab_admin;
CREATE DATABASE forge OWNER forge_app;
CREATE DATABASE shop_validation OWNER sandbox_app;

REVOKE ALL ON DATABASE shop, lab, forge, shop_validation FROM PUBLIC;
GRANT CONNECT ON DATABASE shop TO lab_admin, forge_reader, forge_remediator;
SQL
