import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from shop.common.logging_setup import JsonFormatter
from shop.common.loki_handler import LokiHandler


class _Capture(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        _Capture.received.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_pushes_batched_json_lines_with_low_cardinality_labels():
    _Capture.received = []
    server = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/loki/api/v1/push"

    handler = LokiHandler(url, labels={"service": "checkout"}, flush_interval_s=0.1)
    handler.setFormatter(JsonFormatter("checkout"))
    log = logging.getLogger("test.loki")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.error("dependency call failed", extra={"fields": {"target": "payment:8020", "card_token": "tok_test_visa"}})
    log.info("ok")

    deadline = time.time() + 5
    while not _Capture.received and time.time() < deadline:
        time.sleep(0.05)
    handler.close()
    log.removeHandler(handler)
    server.shutdown()

    streams = [s for payload in _Capture.received for s in payload["streams"]]
    labels = {tuple(sorted(s["stream"].items())) for s in streams}
    assert (("level", "error"), ("service", "checkout")) in labels
    lines = [json.loads(v[1]) for s in streams for v in s["values"]]
    err = next(line for line in lines if line["level"] == "ERROR")
    assert err["fields"]["target"] == "payment:8020"
    assert err["fields"]["card_token"] == "[REDACTED]"
    assert handler.sent == 2 and handler.dropped == 0


def test_unreachable_loki_never_raises_and_counts_failures():
    handler = LokiHandler("http://127.0.0.1:9/push", labels={"service": "x"}, flush_interval_s=0.05, timeout_s=0.2)
    handler.setFormatter(JsonFormatter("x"))
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    handler.emit(rec)
    time.sleep(0.5)
    handler.close()
    assert handler.failed_pushes >= 1


def test_queue_overflow_drops_instead_of_blocking():
    handler = LokiHandler("http://127.0.0.1:9/push", labels={"service": "x"}, max_queue=2, flush_interval_s=60)
    handler.setFormatter(JsonFormatter("x"))
    for i in range(10):
        handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, f"m{i}", None, None))
    assert handler.dropped == 8
