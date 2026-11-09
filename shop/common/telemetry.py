"""OpenTelemetry tracing, Prometheus metrics and request middleware.

* Traces: OpenTelemetry SDK -> OTLP/HTTP -> Jaeger v2. FastAPI, httpx and
  SQLAlchemy are auto-instrumented, so W3C ``traceparent`` is propagated on
  every service-to-service call.
* Metrics: ``prometheus_client`` exposed at ``/metrics`` and scraped by
  Prometheus. Route labels use the route *template* (``/api/orders/{order_ref}``)
  rather than the raw path to keep cardinality bounded.
* Request IDs: accepted from ``X-Request-ID`` (validated) or minted, stored in a
  contextvar, echoed in the response, attached to the current span, and
  forwarded on outbound calls.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from shop.common.context import (
    REQUEST_ID_HEADER,
    SYNTHETIC_HEADER,
    accept_request_id,
    parse_synthetic,
    request_id_var,
    synthetic_var,
)

log = logging.getLogger("shop.http")

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

HTTP_REQUESTS = Counter(
    "shop_http_requests_total",
    "Inbound HTTP requests",
    ["service", "method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "shop_http_request_duration_seconds",
    "Inbound HTTP request latency",
    ["service", "method", "route"],
    buckets=LATENCY_BUCKETS,
)
DEPENDENCY_REQUESTS = Counter(
    "shop_dependency_requests_total",
    "Outbound calls to dependencies, by outcome",
    ["service", "dependency", "operation", "outcome"],
)
DEPENDENCY_LATENCY = Histogram(
    "shop_dependency_request_duration_seconds",
    "Outbound dependency call latency",
    ["service", "dependency", "operation"],
    buckets=LATENCY_BUCKETS,
)
CHECKOUT_ORDERS = Counter(
    "shop_checkout_orders_total",
    "Checkout attempts by final status",
    ["status", "reason"],
)
CONFIG_VERSION = Gauge(
    "shop_runtime_config_version",
    "Active runtime configuration version observed by the service",
    ["service", "config_service"],
)
CONFIG_LOAD_ERRORS = Counter(
    "shop_runtime_config_load_errors_total",
    "Failures to load or validate runtime configuration",
    ["service", "config_service"],
)

_UNMATCHED_ROUTE = "__unmatched__"


def setup_tracing(service_name: str, otlp_traces_endpoint: str | None) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": service_name, "service.namespace": "shop", "deployment.environment": "demo"}
        )
    )
    if otlp_traces_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_traces_endpoint, timeout=5)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return provider


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or _UNMATCHED_ROUTE


def install_http_middleware(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = accept_request_id(request.headers.get(REQUEST_ID_HEADER))
        synthetic = parse_synthetic(request.headers.get(SYNTHETIC_HEADER))
        rid_token = request_id_var.set(rid)
        syn_token = synthetic_var.set(synthetic)
        span = trace.get_current_span()
        span.set_attribute("shop.request_id", rid)
        span.set_attribute("shop.synthetic", synthetic)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = _route_template(request)
            if route not in ("/metrics", "/health"):
                HTTP_REQUESTS.labels(service_name, request.method, route, str(status)).inc()
                HTTP_LATENCY.labels(service_name, request.method, route).observe(elapsed)
                log.info(
                    "request completed",
                    extra={
                        "fields": {
                            "method": request.method,
                            "route": route,
                            "status": status,
                            "duration_ms": round(elapsed * 1000, 2),
                        }
                    },
                )
            request_id_var.reset(rid_token)
            synthetic_var.reset(syn_token)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/health")


def outbound_headers() -> dict[str, str]:
    """Headers forwarded on service-to-service calls (trace context is added by
    the httpx instrumentation)."""
    headers: dict[str, str] = {}
    rid = request_id_var.get()
    if rid:
        headers[REQUEST_ID_HEADER] = rid
    if synthetic_var.get():
        headers[SYNTHETIC_HEADER] = "1"
    return headers
