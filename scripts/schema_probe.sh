#!/usr/bin/env bash
# Applies the forge control-plane DDL to an empty database and probes the
# constraints that carry correctness guarantees. Needs psql + python3 only.
#   FORGE_PROBE_DSN=postgresql://forge_app:pw@127.0.0.1/forge_probe scripts/schema_probe.sh
set -euo pipefail
: "${FORGE_PROBE_DSN:?set FORGE_PROBE_DSN to an EMPTY database}"
cd "$(dirname "$0")/.."
python3 - > /tmp/forge_ddl.sql <<'PY'
import importlib.util, sys, types
alembic = types.ModuleType("alembic"); alembic.op = types.SimpleNamespace(execute=print); sys.modules["alembic"] = alembic
spec = importlib.util.spec_from_file_location("m", "forge/migrations/versions/0001_control_plane.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.upgrade()
PY
P="psql $FORGE_PROBE_DSN -v ON_ERROR_STOP=1 -qtA"
$P -f /tmp/forge_ddl.sql
$P <<'SQL'
INSERT INTO incidents(id,title,status,severity,source,created_by) VALUES ('inc1','t','open','sev2','manual','olivia');
INSERT INTO investigations(id,incident_id,mode,provider,model,status,created_by) VALUES ('inv1','inc1','runbook','runbook','none','completed','olivia');
INSERT INTO proposals(id,incident_id,investigation_id,action_type,target,parameters,expected_active_version,details,status,created_by) VALUES ('p1','inc1','inv1','rollback_config_version','checkout','{}',2,'{}','validated','olivia');
INSERT INTO validation_runs(id,proposal_id,status,production_version,requested_by) VALUES ('v1','p1','passed',2,'olivia');
INSERT INTO approvals(id,proposal_id,validation_run_id,binding,binding_digest,status,requested_by,expires_at) VALUES ('a1','p1','v1','{}','d','pending','olivia',now()+interval '15 min');
INSERT INTO audit_events(actor,action,subject_type,subject_id) VALUES ('olivia','x','incident','inc1');
SQL
fail=0
expect() { # expect allowed|rejected "description" "sql"
  if $P -c "$3" >/dev/null 2>&1; then got=allowed; else got=rejected; fi
  if [ "$got" = "$1" ]; then echo "PASS  $2 ($got)"; else echo "FAIL  $2 (expected $1, got $got)"; fail=1; fi
}
expect rejected "second open approval for one proposal" "INSERT INTO approvals(id,proposal_id,validation_run_id,binding,binding_digest,status,requested_by,expires_at) VALUES ('a2','p1','v1','{}','d','pending','olivia',now())"
expect rejected "requester approves own request" "UPDATE approvals SET status='approved', decided_by='olivia' WHERE id='a1'"
expect allowed  "different approver approves" "UPDATE approvals SET status='approved', decided_by='arun' WHERE id='a1'"
expect allowed  "first recovery job" "INSERT INTO recovery_jobs(id,proposal_id,approval_id,status,requested_by) VALUES ('r1','p1','a1','requested','olivia')"
expect rejected "duplicate recovery job for a proposal" "INSERT INTO recovery_jobs(id,proposal_id,approval_id,status,requested_by) VALUES ('r2','p1','a1','requested','olivia')"
expect rejected "UPDATE audit event" "UPDATE audit_events SET actor='mallory'"
expect rejected "DELETE audit event" "DELETE FROM audit_events"
expect rejected "TRUNCATE audit events" "TRUNCATE audit_events"
expect rejected "action outside catalogue" "INSERT INTO proposals(id,incident_id,investigation_id,action_type,target,parameters,expected_active_version,details,status,created_by) VALUES ('p2','inc1','inv1','run_shell','checkout','{}',2,'{}','proposed','x')"
expect rejected "two open detector incidents" "INSERT INTO incidents(id,title,status,severity,source,created_by) VALUES ('d1','t','open','sev2','detector','d'),('d2','t','open','sev2','detector','d')"
exit $fail
