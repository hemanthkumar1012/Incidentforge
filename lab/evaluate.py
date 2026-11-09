"""Evaluation runner: scenarios × investigation modes × trials, against the live stack.

    docker compose --profile tools run --rm lab evaluate --modes runbook,llm_summary,llm --trials 3

Runs in the lab container because scoring needs ground truth, which exists only
there. It drives forge exclusively through its public API with ordinary operator
and approver accounts, exactly as a human would; forge never sees the label.

Per trial: reset → warm-up checkouts → inject → failing checkouts → register incident
→ investigate (mode) → score → [validate → approve → recover → verify] → cleanup.
Results come only from these runs; the report states sample sizes and limitations.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from lab.controller import LabController
from lab.scenarios import Scenario
from lab.scoring import TrialResult, score


class Forge:
    def __init__(self, base: str, user: str, password: str) -> None:
        self.base, self.http = base, httpx.Client(timeout=20)
        resp = self.http.post(f"{base}/api/auth/login", json={"username": user, "password": password})
        resp.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    def get(self, path: str) -> Any:
        resp = self.http.get(self.base + path)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: Any = None) -> httpx.Response:
        return self.http.post(self.base + path, json=body)


def poll(fn, timeout: float, interval: float = 2.0) -> Any:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"no result within {timeout:.0f}s")


def checkout_once(shop: str) -> int:
    key = f"eval-{uuid.uuid4().hex[:12]}"
    try:
        resp = httpx.post(
            f"{shop}/api/checkout",
            timeout=10,
            headers={"X-Synthetic": "1", "Idempotency-Key": key},
            json={
                "customer_id": "synthetic-eval",
                "card_token": "tok_test_visa",
                "items": [{"sku": "SKU-1004", "qty": 1}],
            },
        )
    except httpx.HTTPError:
        return 0
    return resp.status_code


def run_trial(
    ctl: LabController, sc: Scenario, mode: str, trial_no: int, op: Forge, ap: Forge, shop: str, recover: bool
) -> TrialResult:
    t = TrialResult(sc.id, sc.split, mode, trial_no)
    ctl.reset()
    for incident in op.get("/api/incidents?page_size=100")["items"]:
        if incident["status"] not in ("resolved", "closed"):
            op.post(f"/api/incidents/{incident['id']}/close", {"reason": "evaluation setup"})
    for _ in range(5):
        checkout_once(shop)
    ctl.inject(sc.id)
    time.sleep(5)  # checkout config cache TTL is 3 s
    for _ in range(10):
        checkout_once(shop)
    time.sleep(10)  # one Prometheus scrape interval plus margin
    incident = op.post(
        "/api/incidents", {"title": "Customers report checkout errors (evaluation trial)", "severity": "sev2"}
    ).json()
    versions_before = op.get("/api/system/overview")["checkout_config"]["version"]
    resp = op.post(f"/api/incidents/{incident['id']}/investigations", {"mode": mode})
    if resp.status_code != 202:
        t.error = f"could not start investigation: {resp.status_code} {resp.text[:200]}"
        return t
    inv_id = resp.json()["id"]
    inv = poll(
        lambda: (d := op.get(f"/api/investigations/{inv_id}"))["status"] not in ("queued", "running") and d, timeout=420
    )
    t.provider, t.model, t.investigation_status = inv["provider"], inv["model"], inv["status"]
    t.config_writes_during_investigation = (
        op.get("/api/system/overview")["checkout_config"]["version"] - versions_before
    )
    score(t, inv, sc.ground_truth)
    if recover and t.outcome == "diagnosed":
        _recover(t, sc, op, ap, incident["id"], shop)
    return t


def _recover(t: TrialResult, sc: Scenario, op: Forge, ap: Forge, incident_id: str, shop: str) -> None:
    try:
        proposal = poll(lambda: (op.get(f"/api/incidents/{incident_id}")["proposals"] or [None])[0], timeout=20)
    except TimeoutError:
        t.notes.append("no proposal (planner found no supported action)")
        return
    t.proposal_action = proposal["action_type"]
    t.proposal_matches_supported_recovery = proposal["action_type"] == sc.supported_recovery.action_type
    op.post(f"/api/proposals/{proposal['id']}/validations")
    prop = poll(
        lambda: (
            (p := op.get(f"/api/proposals/{proposal['id']}"))["latest_validation"]["status"]
            not in ("queued", "running")
            and p
        ),
        timeout=180,
    )
    t.validation = prop["latest_validation"]["status"]
    if t.validation != "passed":
        return
    approval = op.post(f"/api/proposals/{proposal['id']}/approvals").json()
    ap.post(
        f"/api/approvals/{approval['id']}/decision",
        {"approve": True, "note": "evaluation", "binding_digest": approval["binding_digest"]},
    )
    job = op.post(f"/api/proposals/{proposal['id']}/recovery").json()
    job = poll(
        lambda: (
            (j := op.get(f"/api/recovery/{job['id']}"))["status"] not in ("requested", "executing", "verifying") and j
        ),
        timeout=180,
    )
    t.recovery = job["status"]
    t.checkout_after = checkout_once(shop) in (200, 201)


def summarise(results: list[TrialResult]) -> list[dict[str, Any]]:
    rows = []
    for mode in sorted({r.mode for r in results}):
        rs = [r for r in results if r.mode == mode]
        ok = [r for r in rs if not r.error]
        lat = [r.latency_s for r in ok if r.latency_s is not None]
        rows.append(
            {
                "mode": mode,
                "trials": len(rs),
                "errored": len(rs) - len(ok),
                "top1": f"{sum(r.top1 for r in ok)}/{len(ok)}",
                "top3": f"{sum(r.top3 for r in ok)}/{len(ok)}",
                "unsupported": f"{sum(not r.supported for r in ok if r.outcome == 'diagnosed')}/"
                f"{sum(r.outcome == 'diagnosed' for r in ok)}",
                "median_latency_s": statistics.median(lat) if lat else None,
                "mean_tool_calls": round(statistics.mean(r.tool_calls for r in ok), 1) if ok else None,
                "total_tokens": sum(r.input_tokens + r.output_tokens for r in ok),
                "est_cost_usd": round(sum(r.est_cost_usd for r in ok), 4),
                "recovered": f"{sum(r.recovery == 'succeeded' for r in ok)}/{sum(r.recovery is not None for r in ok)}",
                "policy_violations": sum(r.config_writes_during_investigation != 0 for r in ok),
                "rejected_tool_calls": sum(r.rejected_tool_calls for r in ok),
            }
        )
    return rows


def write_report(results: list[TrialResult], scenarios: list[Scenario], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows = summarise(results)
    (out_dir / f"results-{stamp}.json").write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "scenarios": [s.id for s in scenarios],
                "summary": rows,
                "trials": [asdict(r) for r in results],
            },
            indent=2,
        )
    )
    head = list(rows[0].keys()) if rows else []
    lines = [
        f"# Evaluation report ({stamp})",
        "",
        f"Generated from {len(results)} actual trial(s) over {len(scenarios)} scenario(s): "
        f"{', '.join(s.id + ' (' + s.split + ')' for s in scenarios)}.",
        "",
    ]
    if len(scenarios) < 3:
        lines += [
            "> **Limitation:** only "
            f"{len(scenarios)} scenario(s) exist. These numbers describe behaviour on that scenario only "
            "and do not support claims about generalisation. There is no held-out split yet.",
            "",
        ]
    lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(r[h]) for h in head) + " |" for r in rows]
    lines += ["", "Rubric and definitions: docs/evaluation.md. Raw per-trial data: the matching results JSON."]
    path = out_dir / f"report-{stamp}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main(ctl: LabController, modes: list[str], trials: int, scenario_ids: list[str] | None, recover: bool) -> int:
    def creds(var: str) -> tuple[str, str]:
        user, _, password = os.environ[var].partition(":")
        return user, password

    base, shop = (
        os.environ.get("FORGE_URL", "http://forge-api:8080"),
        os.environ.get("CHECKOUT_URL", "http://checkout:8000"),
    )
    op, ap = Forge(base, *creds("EVAL_OPERATOR")), Forge(base, *creds("EVAL_APPROVER"))
    scenarios = [s for s in ctl.scenarios.values() if not scenario_ids or s.id in scenario_ids]
    results: list[TrialResult] = []
    for sc in scenarios:
        for mode in modes:
            for n in range(1, trials + 1):
                try:
                    result = run_trial(ctl, sc, mode, n, op, ap, shop, recover)
                except (httpx.HTTPError, TimeoutError, KeyError) as exc:
                    result = TrialResult(sc.id, sc.split, mode, n, error=f"{type(exc).__name__}: {exc}")
                finally:
                    ctl.reset()
                print(json.dumps(asdict(result)))
                results.append(result)
    report = write_report(results, scenarios, Path(os.environ.get("EVAL_OUTPUT_DIR", "/app/artifacts/eval")))
    print(f"report written to {report}")
    return 0 if all(not r.error for r in results) else 1
