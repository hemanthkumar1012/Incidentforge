# Checkout API contract (`POST /api/checkout`)

Clients should send an `Idempotency-Key` header (≤ 80 chars). The key and a fingerprint of the
body (customer, items, card token, currency) are claimed atomically with
`INSERT … ON CONFLICT DO NOTHING`, so exactly one request owns a key.

| Situation | Response | Client should |
|---|---|---|
| First request, success | `201` order body | — |
| Same key, same body, after success | `200` same order, `"replayed": true`; no second charge | — |
| Same key, **different** body | `422 idempotency_key_reused` | use a new key |
| Same key while the first is still running (claim < 30 s old) | `409 request_in_progress`, `Retry-After: 2` | retry with the **same** key |
| Payment outcome uncertain (timeout / 5xx / bad response after the built-in retry) | `504 payment_outcome_unknown`, `Retry-After: 2`; order `unknown`, stock hold **kept** | retry with the **same** key; the retry resumes the order and settles it |
| Previous attempt crashed (claim `pending` > 30 s, e.g. process died) | the retry with the same key resumes the same order | retry with the same key |
| Definitive failure: out of stock (`409`), card declined (`402`), payment never reached (connect error / 4xx, `502`), inventory unavailable (`502`/`504`) | order `failed`, stock released | a retry with the same key returns `409 previous_attempt_failed`; use a **new** key to try again |
| No key | every request is a new order | — |

**Why resuming is safe.** Inventory reservations are unique per `order_ref` (a repeat returns the existing hold),
and the charge carries `order_ref` as its idempotency key (the processor returns the original result). A resumed
order replays both steps without doing either twice. Takeover of an `unknown` or stale `pending` order is an
atomic conditional `UPDATE`, so two concurrent retries cannot both resume it.

**Known limit.** The payment simulator keeps idempotency results in memory. If it restarts between the uncertain
attempt and the retry, it cannot recognise the original charge. A real processor persists these results.

Tests: `tests/unit/test_orchestrator.py` (logic) and `tests/db/test_checkout_db.py` (PostgreSQL races, crash/restart,
unknown outcome; NOT RUN here).
