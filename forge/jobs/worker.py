"""Background worker: runs queued jobs and the incident detector.

    python -m forge.jobs.worker

Loop: requeue stale leases → claim one job (SKIP LOCKED) → run it → mark done
or failed (with retry). Between jobs it runs the detector at most every
``DETECT_EVERY``. One job at a time per process; scale out with more processes.
SIGTERM finishes the current job, then exits.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from collections.abc import Callable

from forge.jobs import detector
from forge.jobs.queue import claim_next, complete, fail, requeue_stale
from forge.services import investigations, proposals, recovery
from forge.settings import ForgeSettings
from forge.wiring import Container
from shop.common.logging_setup import configure_logging

log = logging.getLogger("forge.worker")
POLL_IDLE_S = 1.0
DETECT_EVERY_S = 15.0


def handlers(c: Container) -> dict[str, Callable[[str], str]]:
    return {
        "investigation": lambda subject: investigations.execute(c.sessions, subject, c.investigator, c.planner_inputs),
        "validation": lambda subject: proposals.run_validation(
            c.sessions, subject, c.config_history, c.sandbox, c.sandbox_hosts
        ),
        "recovery": lambda subject: recovery.execute(
            c.sessions, subject, c.config_history, c.config_writer, c.verifier
        ),
    }


def run_one(c: Container, worker_id: str, table: dict[str, Callable[[str], str]]) -> bool:
    with c.sessions.begin() as s:
        requeue_stale(s)
        job = claim_next(s, worker_id)
        if job is None:
            return False
        job_id, kind, subject = job.id, job.kind, job.subject_id
    log.info("job started", extra={"fields": {"job_id": job_id, "kind": kind, "subject": subject}})
    try:
        outcome = table[kind](subject)
    except Exception as exc:  # noqa: BLE001 - recorded on the job and logged with traceback, then retried
        log.exception("job failed", extra={"fields": {"job_id": job_id, "kind": kind}})
        with c.sessions.begin() as s:
            retried = fail(s, job_id, f"{type(exc).__name__}: {exc}")
        log.warning("job %s", "will retry" if retried else "gave up", extra={"fields": {"job_id": job_id}})
        return True
    with c.sessions.begin() as s:
        complete(s, job_id)
    log.info("job finished", extra={"fields": {"job_id": job_id, "kind": kind, "outcome": outcome}})
    return True


def main() -> None:
    configure_logging("forge-worker", os.environ.get("LOG_LEVEL", "INFO"), os.environ.get("LOKI_PUSH_URL"))
    c = Container(ForgeSettings.from_env())
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    table = handlers(c)
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_detect = 0.0
    log.info("worker started", extra={"fields": {"worker_id": worker_id}})
    while not stopping:
        if c.settings.detector_enabled and time.monotonic() - last_detect >= DETECT_EVERY_S:
            last_detect = time.monotonic()
            detector.run_once(c)
        if not run_one(c, worker_id, table):
            time.sleep(POLL_IDLE_S)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
