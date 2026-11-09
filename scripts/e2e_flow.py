#!/usr/bin/env python3
"""End-to-end acceptance for the full product flow (runbook mode, no LLM credentials).

    python3 scripts/e2e_flow.py            # after `make up`

healthy → checkout OK → inject S1 (synthetic) → checkout fails → incident (detector, else manual)
→ runbook investigation on real telemetry → evidence-backed diagnosis → proposal → sandbox validation
→ approval request → rejection → re-request → approval by a different user → execution
→ checkout OK → recovery verified → audit history recorded.
Also checks: viewer cannot start an investigation (403); requester cannot self-approve (403).

Passing this says nothing about the Gemini integration (see tests/live).
Every wait is a bounded poll. On failure, redacted artifacts go to artifacts/e2e/.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shop.common.redaction import redact  # noqa: E402  (stdlib-only module)

API = os.environ.get("FORGE_URL", "http://localhost:8080")
SHOP = os.environ.get("CHECKOUT_URL", "http://localhost:8000")
ARTIFACTS = ROOT / "artifacts" / "e2e"
USERS = {
    "operator": ("olivia", "FORGE_OPERATOR_PASSWORD"),
    "approver": ("arun", "FORGE_APPROVER_PASSWORD"),
    "viewer": ("vera", "FORGE_VIEWER_PASSWORD"),
}
log: list[dict[str, Any]] = []
report: dict[str, Any] = {"mode": "runbook", "synthetic": True, "steps": []}


class StepFailed(AssertionError):
    pass


def env_secrets() -> list[str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return []
    return [
        v
        for line in env_file.read_text().splitlines()
        if "=" in line and not line.startswith("#")
        for v in [line.split("=", 1)[1].strip()]
        if len(v) >= 8
    ]


def scrub(text: str) -> str:
    for secret in env_secrets():
        text = text.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", text)


def call(method: str, url: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        status, raw = 0, json.dumps({"error": str(exc)}).encode()
    data = json.loads(raw) if raw[:1] in (b"{", b"[") else {"raw": raw[:200].decode(errors="replace")}
    log.append({"t": time.time(), "method": method, "url": url, "status": status, "response": redact(data)})
    return status, data


def step(name: str, ok: bool, **detail: Any) -> None:
    report["steps"].append({"step": name, "ok": ok, **detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(detail, default=str)[:200]}", file=sys.stderr)
    if not ok:
        raise StepFailed(name)


def poll(fn, *, timeout: float, interval: float = 2.0, what: str):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.monotonic() > deadline:
            raise StepFailed(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(interval)


def login(role: str) -> str:
    username, var = USERS[role]
    password = os.environ.get(var) or bootstrap_password(username)
    status, data = call("POST", f"{API}/api/auth/login", {"username": username, "password": password})
    step(f"login as {role}", status == 200, status=status)
    return data["access_token"]


def bootstrap_password(username: str) -> str:
    spec = os.environ.get("FORGE_BOOTSTRAP_USERS") or next(
        (
            line.split("=", 1)[1]
            for line in (ROOT / ".env").read_text().splitlines()
            if line.startswith("FORGE_BOOTSTRAP_USERS=")
        ),
        "",
    )
    for entry in spec.split(","):
        name, _, password = entry.strip().split(":", 2)
        if name == username:
            return password
    raise StepFailed(f"no password for {username}; set FORGE_BOOTSTRAP_USERS or the per-role variable")


def lab(*args: str) -> None:
    proc = subprocess.run(
        ["docker", "compose", "--profile", "tools", "run", "--rm", "-T", "lab", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    step(f"lab {' '.join(args)}", proc.returncode == 0, stderr=scrub(proc.stderr[-300:]))


def journey(expect: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "tools/journey.py", "--base-url", SHOP, "--expect", expect],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {"matched": False}


def main() -> int:
    operator, approver, viewer = login("operator"), login("approver"), login("viewer")
    lab("reset")
    # Earlier runs may have left incidents open; an open detector incident would suppress detection.
    _, existing = call("GET", f"{API}/api/incidents?page_size=100", token=operator)
    for old in existing.get("items", []):
        if old["status"] not in ("resolved", "closed"):
            call("POST", f"{API}/api/incidents/{old['id']}/close", {"reason": "closed by e2e setup"}, token=operator)
    step("healthy checkout", poll(lambda: journey("success").get("matched"), timeout=60, what="healthy checkout"))
    lab("inject", "S1")
    failed = poll(lambda: (j := journey("failure")).get("matched") and j, timeout=30, what="checkout failure")
    step("checkout fails after injection", True, trace_request=failed["steps"][-1].get("request_id"))
    for _ in range(8):  # extra synthetic failures so the detector threshold is crossed
        journey("failure")

    def open_detector_incident():
        _, data = call("GET", f"{API}/api/incidents?status=open", token=operator)
        return next((i for i in data.get("items", []) if i["source"] == "detector"), None)

    try:
        incident = poll(open_detector_incident, timeout=60, interval=5, what="detector incident")
        report["incident_source"] = "detector"
    except StepFailed:
        status, incident = call(
            "POST", f"{API}/api/incidents", {"title": "Checkout failing (e2e)", "severity": "sev2"}, token=operator
        )
        step("manual incident registration (detector did not fire in time)", status == 201)
        report["incident_source"] = "manual"
    iid = incident["id"]

    status, _ = call("POST", f"{API}/api/incidents/{iid}/investigations", {"mode": "runbook"}, token=viewer)
    step("viewer cannot start investigation", status == 403, status=status)
    status, inv = call("POST", f"{API}/api/incidents/{iid}/investigations", {"mode": "runbook"}, token=operator)
    step("investigation queued", status == 202, status=status)

    def finished():
        _, data = call("GET", f"{API}/api/investigations/{inv['id']}", token=operator)
        return data if data.get("status") not in ("queued", "running") else None

    inv = poll(finished, timeout=120, what="investigation to finish")
    top = (inv.get("diagnosis") or {}).get("hypotheses", [{}])[0]
    labels = {e["id"] for e in inv.get("evidence", []) if e["ok"]}
    step(
        "evidence-backed diagnosis",
        inv["status"] == "completed"
        and bool(top)
        and set(top.get("evidence_ids", [])) <= labels
        and top.get("component") == "checkout",
        status=inv["status"],
        top=top.get("summary"),
        evidence=sorted(labels),
    )

    def proposal():
        _, ws = call("GET", f"{API}/api/incidents/{iid}", token=operator)
        return (ws.get("proposals") or [None])[0]

    prop = poll(proposal, timeout=20, what="proposal")
    step("repair proposal created", prop["action_type"] == "rollback_config_version", parameters=prop["parameters"])
    status, _ = call("POST", f"{API}/api/proposals/{prop['id']}/validations", token=operator)
    step("validation requested", status == 202, status=status)

    def validated():
        _, p = call("GET", f"{API}/api/proposals/{prop['id']}", token=operator)
        v = p.get("latest_validation") or {}
        return p if v.get("status") not in (None, "queued", "running") else None

    prop = poll(validated, timeout=120, what="validation")
    step(
        "isolated validation passed",
        prop["latest_validation"]["status"] == "passed",
        verdict=prop["latest_validation"]["status"],
    )

    status, apr = call("POST", f"{API}/api/proposals/{prop['id']}/approvals", token=operator)
    step("approval requested", status == 201, status=status)
    digest = apr["binding_digest"]
    status, _ = call(
        "POST",
        f"{API}/api/approvals/{apr['id']}/decision",
        {"approve": False, "note": "e2e: reject first", "binding_digest": digest},
        token=approver,
    )
    step("approver rejects", status == 200, status=status)
    status, _ = call("POST", f"{API}/api/proposals/{prop['id']}/recovery", token=operator)
    step("execution refused without approval", status == 412, status=status)
    status, apr = call("POST", f"{API}/api/proposals/{prop['id']}/approvals", token=operator)
    step("approval re-requested", status == 201, status=status)
    status, _ = call(
        "POST",
        f"{API}/api/approvals/{apr['id']}/decision",
        {"approve": True, "note": "self", "binding_digest": apr["binding_digest"]},
        token=operator,
    )
    step("requester cannot self-approve", status == 403, status=status)
    status, _ = call(
        "POST",
        f"{API}/api/approvals/{apr['id']}/decision",
        {"approve": True, "note": "e2e: approved", "binding_digest": apr["binding_digest"]},
        token=approver,
    )
    step("different user approves", status == 200, status=status)
    status, job = call("POST", f"{API}/api/proposals/{prop['id']}/recovery", token=operator)
    step("recovery requested", status == 202, status=status)
    status, again = call("POST", f"{API}/api/proposals/{prop['id']}/recovery", token=operator)
    step("duplicate recovery request returns same job", status == 200 and again["id"] == job["id"])

    def recovered():
        _, data = call("GET", f"{API}/api/recovery/{job['id']}", token=operator)
        return data if data.get("status") not in ("requested", "executing", "verifying") else None

    job = poll(recovered, timeout=120, what="recovery")
    step("recovery verified", job["status"] == "succeeded", status=job["status"])
    step("checkout succeeds after repair", journey("success").get("matched", False))
    _, timeline = call("GET", f"{API}/api/incidents/{iid}/timeline", token=operator)
    actions = [e["action"] for e in timeline.get("items", [])]
    needed = [
        "investigation.started",
        "proposal.created",
        "validation.finished",
        "approval.rejected",
        "approval.approved",
        "recovery.applied",
        "recovery.succeeded",
    ]
    step("audit history recorded", all(a in actions for a in needed), missing=[a for a in needed if a not in actions])
    lab("reset")
    return 0


def save_artifacts() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "api_responses.json").write_text(scrub(json.dumps(log, indent=1, default=str)))
    health = {
        name: call("GET", url)[0] for name, url in {"checkout": f"{SHOP}/ready", "forge": f"{API}/health"}.items()
    }
    (ARTIFACTS / "health.json").write_text(json.dumps(health))
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--tail=400"], cwd=ROOT, capture_output=True, text=True, timeout=60
    ).stdout
    (ARTIFACTS / "service_logs.txt").write_text(scrub(logs))


if __name__ == "__main__":
    try:
        code = main()
    except (StepFailed, KeyError, TypeError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    report["passed"] = code == 0
    if code:
        save_artifacts()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "report.json").write_text(scrub(json.dumps(report, indent=2, default=str)))
    print(json.dumps({"passed": report["passed"], "steps": len(report["steps"]), "error": report.get("error")}))
    sys.exit(code)
