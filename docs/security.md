# Security: threat model, authentication, authorization, boundaries

Scope: a local research platform with synthetic data. These controls are real and tested where stated. They are
not a claim of production-grade security.

## Assets and actors

Assets: production shop config (the only thing forge can change), the approval trail, lab ground truth (must
stay hidden from the investigator), credentials. Actors: operator, approver, viewer, admin; the investigator
(LLM or runbook); anyone who can make the shop log text (untrusted input); a compromised browser session.

## Threats and controls

| Threat | Control | Evidence |
|---|---|---|
| Prompt injection via logs, traces or change summaries | All investigator tools are read-only; output is wrapped in untrusted evidence blocks with delimiter neutralisation; instruction-like text is flagged; actions come from a deterministic planner and need validation plus human approval | tests/unit/forge/test_engine.py (injection, delimiter spoof) |
| Model claims without support | Claim checker rejects unknown or failed evidence IDs and high confidence on < 2 items | test_engine.py, test_runbook.py |
| Investigator reads ground truth | forge image excludes `lab/`; forge code never imports lab; ground truth only in the `lab` DB (forge has no role there) | tests/unit/test_isolation.py; init.sh |
| Over-broad DB access | One role per component; `forge_reader` SELECT on two tables; `forge_remediator` INSERT/UPDATE on those two only | psql probes (PASS); tests/db/test_roles_db.py (NOT RUN) |
| Executing something other than what was approved | SHA-256 binding digest over action, target, params, expected config version, validation run; approver submits the digest they reviewed | test_domain.py; tests/db/test_forge_db.py (NOT RUN) |
| Stale approval (production changed) | `expected_active_version` checked at request and inside the config write under an advisory lock | test_domain.py; test_forge_db.py (NOT RUN) |
| Self-approval | policy check plus DB `CHECK (decided_by <> requested_by)` | test_domain.py; schema_probe.sh (PASS) |
| Duplicate or concurrent execution | existing-job check, conditional consume, unique `recovery_jobs.proposal_id`; recovery jobs never auto-retry | schema_probe.sh (PASS, constraint level); test_forge_db.py (NOT RUN) |
| Audit tampering by the app | trigger blocks UPDATE/DELETE/TRUNCATE on `audit_events`. A superuser can still bypass it, so this is **not tamper-proof storage** | schema_probe.sh (PASS) |
| Validation sandbox touching production | sandbox on `internal` network with no production services; URL mapping by explicit allowlist (unknown → `unresolvable.invalid`, IP/localhost rejected); sandbox role refused by shop DB | unit tests (PASS); scripts/sandbox_isolation_check.sh (NOT RUN) |
| SSRF through diagnostics | TCP probe targets limited to URLs in checkout's own config; readiness to known services | test_tools.py |
| PromQL/LogQL injection or scope creep | PromQL identifiers must be shop metrics; LogQL built server-side from typed fields | test_tools.py |
| XSS from evidence | React escapes text; evidence only in `<pre>`; ESLint bans `dangerouslySetInnerHTML`; CSP `default-src 'self'` | web/src/test/EvidenceAndStates.test.tsx (NOT RUN) |
| Secrets leakage | secrets only via env; redaction in logs and tool output; Gemini key in header, not URL; e2e/CI artifacts scrubbed | test_redaction.py |

## Authentication

Local users (`FORGE_BOOTSTRAP_USERS` for the demo), scrypt password hashes, HS256 JWT (8 h) in an
`Authorization: Bearer` header. The role is re-read from the DB on every request, so disabling a user or changing
a role is immediate. Login responses do not reveal whether a username exists.

**Token storage in the UI.** The token is held in memory only, never in `localStorage`/`sessionStorage`. XSS cannot
read a persisted token and closing the tab ends the session; the cost is re-login on reload. The stronger
design is an httpOnly, SameSite=Strict cookie issued by the API with CSRF protection. That is not implemented.

## Authorization

| Permission | viewer | operator | approver | admin |
|---|---|---|---|---|
| read | ✓ | ✓ | ✓ | ✓ |
| register/close incident, run investigation, request validation/approval, execute recovery | | ✓ | | ✓ |
| decide approval (never one's own request) | | | ✓ | ✓ |

Enforced server-side on every state-changing endpoint (`forge/api/deps.py::require`). The UI hides controls by
permission only for clarity; it is not the enforcement point.

## The sandbox, precisely

"Copy live configuration" and "sandbox hostnames only" combine like this: every configuration **value** is
copied from production (so a wrong port or path is reproduced exactly), and every **host** is rewritten by an
explicit allowlist (`payment → sandbox-payment`, `inventory → sandbox-inventory`). Anything not on the list
becomes `unresolvable.invalid`, which reproduces a DNS failure and can reach nothing. IP literals and localhost
are rejected outright. The network adds a second layer: sandbox containers sit only on an `internal` Docker
network without production services. This is containment for correctness, not a security sandbox. Containers
share a kernel, and Postgres is reachable from the sandbox network (with sandbox-only credentials).
