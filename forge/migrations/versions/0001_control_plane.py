"""control plane schema

Revision ID: f0001
Revises:
Create Date: 2026-11-08

Written as explicit SQL so the revision is frozen and reviewable; it must stay
in sync with forge/db/models.py (tests/db/test_migrations.py compares them).
"""

from alembic import op

revision = "f0001"
down_revision = None
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE users (
  id serial PRIMARY KEY,
  username varchar(64) NOT NULL UNIQUE,
  password_hash varchar(256) NOT NULL,
  role varchar(16) NOT NULL CHECK (role IN ('viewer', 'operator', 'approver', 'admin')),
  disabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE incidents (
  id varchar(40) PRIMARY KEY,
  title varchar(200) NOT NULL,
  status varchar(16) NOT NULL,
  severity varchar(8) NOT NULL CHECK (severity IN ('sev1', 'sev2', 'sev3')),
  source varchar(16) NOT NULL CHECK (source IN ('manual', 'detector')),
  signal jsonb NOT NULL DEFAULT '{}',
  synthetic_traffic boolean NOT NULL DEFAULT true,
  created_by varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  version integer NOT NULL DEFAULT 1
);
CREATE INDEX ix_incidents_status ON incidents (status);
CREATE INDEX ix_incidents_created_at ON incidents (created_at);
-- At most one open detector incident at a time: the detector dedupes on this.
CREATE UNIQUE INDEX uq_incidents_one_open_detector ON incidents (source)
  WHERE source = 'detector' AND status NOT IN ('resolved', 'closed');

CREATE TABLE investigations (
  id varchar(40) PRIMARY KEY,
  incident_id varchar(40) NOT NULL REFERENCES incidents (id),
  mode varchar(16) NOT NULL CHECK (mode IN ('llm', 'runbook')),
  provider varchar(32) NOT NULL,
  model varchar(64) NOT NULL,
  status varchar(24) NOT NULL,
  diagnosis jsonb,
  usage jsonb NOT NULL DEFAULT '{}',
  failure_reason text,
  created_by varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);
CREATE INDEX ix_investigations_incident_id ON investigations (incident_id);

CREATE TABLE investigation_steps (
  id bigserial PRIMARY KEY,
  investigation_id varchar(40) NOT NULL REFERENCES investigations (id),
  seq integer NOT NULL,
  kind varchar(24) NOT NULL,
  summary text NOT NULL,
  tool varchar(48),
  evidence_label varchar(8),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (investigation_id, seq)
);
CREATE INDEX ix_investigation_steps_investigation_id ON investigation_steps (investigation_id);

CREATE TABLE evidence (
  id bigserial PRIMARY KEY,
  investigation_id varchar(40) NOT NULL REFERENCES investigations (id),
  label varchar(8) NOT NULL,
  tool varchar(48) NOT NULL,
  arguments jsonb NOT NULL,
  ok boolean NOT NULL,
  data jsonb,
  error jsonb,
  summary text NOT NULL,
  injection_flags jsonb NOT NULL DEFAULT '[]',
  truncated boolean NOT NULL DEFAULT false,
  duration_ms double precision NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_evidence_label UNIQUE (investigation_id, label)
);
CREATE INDEX ix_evidence_investigation_id ON evidence (investigation_id);

CREATE TABLE proposals (
  id varchar(40) PRIMARY KEY,
  incident_id varchar(40) NOT NULL REFERENCES incidents (id),
  investigation_id varchar(40) NOT NULL REFERENCES investigations (id),
  action_type varchar(48) NOT NULL
    CHECK (action_type IN ('rollback_config_version', 'restore_previous_config')),
  target varchar(32) NOT NULL,
  parameters jsonb NOT NULL,
  expected_active_version integer NOT NULL,
  details jsonb NOT NULL,
  status varchar(24) NOT NULL,
  created_by varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1
);
CREATE INDEX ix_proposals_incident_id ON proposals (incident_id);

CREATE TABLE validation_runs (
  id varchar(40) PRIMARY KEY,
  proposal_id varchar(40) NOT NULL REFERENCES proposals (id),
  status varchar(24) NOT NULL,
  production_version integer NOT NULL,
  report jsonb NOT NULL DEFAULT '{}',
  requested_by varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX ix_validation_runs_proposal_id ON validation_runs (proposal_id);

CREATE TABLE approvals (
  id varchar(40) PRIMARY KEY,
  proposal_id varchar(40) NOT NULL REFERENCES proposals (id),
  validation_run_id varchar(40) NOT NULL REFERENCES validation_runs (id),
  binding jsonb NOT NULL,
  binding_digest varchar(64) NOT NULL,
  status varchar(16) NOT NULL,
  requested_by varchar(64) NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  decided_by varchar(64),
  decided_at timestamptz,
  note text,
  CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE INDEX ix_approvals_proposal_id ON approvals (proposal_id);
CREATE INDEX ix_approvals_status ON approvals (status);
CREATE UNIQUE INDEX uq_approvals_one_open ON approvals (proposal_id) WHERE status IN ('pending', 'approved');

CREATE TABLE recovery_jobs (
  id varchar(40) PRIMARY KEY,
  proposal_id varchar(40) NOT NULL REFERENCES proposals (id),
  approval_id varchar(40) NOT NULL REFERENCES approvals (id),
  status varchar(24) NOT NULL,
  requested_by varchar(64) NOT NULL,
  config_version_before integer,
  config_version_after integer,
  result jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CONSTRAINT uq_recovery_jobs_proposal UNIQUE (proposal_id),
  CONSTRAINT uq_recovery_jobs_approval UNIQUE (approval_id)
);

CREATE TABLE jobs (
  id bigserial PRIMARY KEY,
  kind varchar(32) NOT NULL,
  subject_id varchar(40) NOT NULL,
  status varchar(16) NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 2,
  run_after timestamptz NOT NULL DEFAULT now(),
  locked_by varchar(64),
  locked_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_jobs_ready ON jobs (status, run_after);

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor varchar(64) NOT NULL,
  action varchar(64) NOT NULL,
  subject_type varchar(32) NOT NULL,
  subject_id varchar(40) NOT NULL,
  incident_id varchar(40),
  details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_audit_events_occurred_at ON audit_events (occurred_at);
CREATE INDEX ix_audit_events_subject_id ON audit_events (subject_id);
CREATE INDEX ix_audit_events_incident_id ON audit_events (incident_id);

-- Append-only audit log. Enforced for the application role; a superuser can
-- still bypass it, so this is not tamper-proof storage.
CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP;
END $$;
CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
"""

TABLES = (
    "audit_events",
    "jobs",
    "recovery_jobs",
    "approvals",
    "validation_runs",
    "proposals",
    "evidence",
    "investigation_steps",
    "investigations",
    "incidents",
    "users",
)


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608 - constant names
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
