# State machines

Source of truth: `forge/domain/states.py` (illegal transitions raise and map to HTTP 409).

## Investigation

```mermaid
stateDiagram-v2
  [*] --> queued: POST /incidents/{id}/investigations
  queued --> running: worker claims job
  queued --> cancelled
  running --> completed: diagnosis (diagnosed or no_incident)
  running --> insufficient_evidence
  running --> budget_exhausted: turns / tool calls / tokens / time
  running --> failed: provider error or repeated invalid output
  running --> queued: worker lease expired, job retried
```

## Proposal → validation → approval → recovery

```mermaid
stateDiagram-v2
  [*] --> proposed: planner (diagnosed + allowlisted action)
  proposed --> validating: POST /proposals/{id}/validations
  validating --> validated: sandbox reproduced + repaired + no regressions
  validating --> validation_failed
  validating --> not_reproducible: failure did not reproduce (NOT verified)
  validating --> superseded: production config moved
  validated --> validating: re-validate (invalidates open approvals)
  validated --> executed: approved recovery applied
```

```mermaid
stateDiagram-v2
  [*] --> pending: POST /proposals/{id}/approvals (proposal validated)
  pending --> approved: different user with approver role, digest matches
  pending --> rejected
  pending --> expired: 15 min
  pending --> invalidated: proposal re-validated
  approved --> consumed: exactly one recovery job (conditional UPDATE)
  approved --> expired
  approved --> invalidated
```

```mermaid
stateDiagram-v2
  [*] --> requested: POST /proposals/{id}/recovery (idempotent per proposal)
  requested --> executing: worker; re-checks digest + config version
  requested --> refused
  executing --> refused: preconditions changed / expected_active_version mismatch
  executing --> verifying: config written (forge_remediator)
  executing --> failed
  verifying --> succeeded: N synthetic checkouts pass
  verifying --> verification_failed: no automatic rollback (would be an unapproved write)
```

## Incident

`open → investigating → diagnosed → remediating → resolved`. `closed` is reachable from any non-terminal state
(closed without a verified repair). Failed investigations return the incident to `open`. Failed or refused
recoveries return it to `diagnosed`.
