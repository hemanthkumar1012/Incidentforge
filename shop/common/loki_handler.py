"""A bounded, non-blocking logging handler that pushes JSON logs to Loki.

Design choice: logs go to Loki through its stable native push API
(``POST /loki/api/v1/push``) instead of the OpenTelemetry logs SDK, whose
Python API has churned between releases. Trace correlation is preserved because
every log line carries the OpenTelemetry ``trace_id``/``span_id`` (added by the
JSON formatter). Labels are kept low-cardinality (service, level); everything
else lives in the JSON line and is queried with ``| json``.

Guarantees:
* ``emit`` never blocks the request path: records go into a bounded queue and
  are dropped (and counted) if the queue is full.
* A background thread flushes in batches with a per-request timeout.
* Failures to reach Loki are counted, never raised into application code.

Pure stdlib so it is unit-testable without service dependencies.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.request
from typing import Any


class LokiHandler(logging.Handler):
    def __init__(
        self,
        push_url: str,
        labels: dict[str, str],
        *,
        batch_size: int = 200,
        flush_interval_s: float = 1.0,
        max_queue: int = 10_000,
        timeout_s: float = 2.0,
    ) -> None:
        super().__init__()
        if not push_url.startswith(("http://", "https://")):
            raise ValueError("Loki push URL must be http(s)")
        self.push_url = push_url
        self.labels = dict(labels)
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self.timeout_s = timeout_s
        self._queue: queue.Queue[tuple[int, str, str]] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self.dropped = 0
        self.failed_pushes = 0
        self.sent = 0
        self._thread = threading.Thread(target=self._run, name="loki-push", daemon=True)
        self._thread.start()

    # logging.Handler API -------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            ts_ns = int(record.created * 1_000_000_000)
            self._queue.put_nowait((ts_ns, record.levelname.lower(), line))
        except queue.Full:
            self.dropped += 1
        except Exception:  # noqa: BLE001 - a log handler must never raise
            self.handleError(record)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.timeout_s + 1)
        self._flush_all()
        super().close()

    # internals -----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.flush_interval_s)
            self._flush_all()

    def _drain(self) -> list[tuple[int, str, str]]:
        items: list[tuple[int, str, str]] = []
        while len(items) < self.batch_size:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _flush_all(self) -> None:
        while True:
            batch = self._drain()
            if not batch:
                return
            self._push(batch)

    def build_payload(self, batch: list[tuple[int, str, str]]) -> dict[str, Any]:
        streams: dict[str, list[list[str]]] = {}
        for ts_ns, level, line in batch:
            streams.setdefault(level, []).append([str(ts_ns), line])
        return {
            "streams": [
                {"stream": {**self.labels, "level": level}, "values": values} for level, values in streams.items()
            ]
        }

    def _push(self, batch: list[tuple[int, str, str]]) -> None:
        body = json.dumps(self.build_payload(batch)).encode()
        req = urllib.request.Request(  # noqa: S310 - scheme validated in __init__
            self.push_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                resp.read()
            self.sent += len(batch)
        except Exception:  # noqa: BLE001 - telemetry loss must not crash the app
            self.failed_pushes += 1
            # Avoid hot-looping against an unreachable Loki.
            time.sleep(min(self.flush_interval_s, 0.5))
