"""Tests the stdlib journey tool against a stub checkout server."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("journey", Path(__file__).resolve().parents[2] / "tools" / "journey.py")
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)


def make_server(checkout_status: int):
    class Stub(BaseHTTPRequestHandler):
        seen_headers: list = []

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Request-ID", self.headers.get("X-Request-ID", "x"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            elif self.path == "/api/products":
                self._send(200, {"products": [{"sku": "SKU-1", "stock": 9}, {"sku": "SKU-2", "stock": 9}]})
            elif self.path.startswith("/api/orders/"):
                self._send(200, {"status": "confirmed"})

        def do_POST(self):  # noqa: N802
            Stub.seen_headers.append(dict(self.headers))
            self.rfile.read(int(self.headers["Content-Length"]))
            if checkout_status == 201:
                self._send(201, {"order_ref": "ord_1", "status": "confirmed"})
            else:
                self._send(checkout_status, {"error": {"code": "dependency_unavailable"}})

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Stub


def test_success_journey_is_labelled_synthetic():
    server, stub = make_server(201)
    try:
        result = journey.run(f"http://127.0.0.1:{server.server_port}", "tok_test_visa")
    finally:
        server.shutdown()
    assert result["outcome"] == "success" and result["synthetic"]
    assert stub.seen_headers[0]["X-Synthetic"] == "1"
    assert stub.seen_headers[0]["Idempotency-Key"].startswith("journey-")


def test_failure_journey_reports_error_code():
    server, _ = make_server(502)
    try:
        result = journey.run(f"http://127.0.0.1:{server.server_port}", "tok_test_visa")
    finally:
        server.shutdown()
    assert result["outcome"] == "failure"
    checkout = next(s for s in result["steps"] if s["step"] == "checkout")
    assert checkout["error_code"] == "dependency_unavailable"


def test_unreachable():
    assert journey.run("http://127.0.0.1:9", "tok_test_visa")["outcome"] == "unreachable"
