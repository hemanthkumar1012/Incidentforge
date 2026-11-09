"""httpx implementations of the inventory and payment client protocols.

Each call: bounded timeout, at most one retry for retryable outcomes
(connect error, timeout, 5xx), an outcome-labelled metric, and a structured
log line naming the dependency, operation, target host:port and outcome. The
target is logged deliberately: it is the evidence that separates "payment is
down" from "checkout is pointed at the wrong place".
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from shop.checkout.orchestrator import (
    Charge,
    DependencyError,
    LineItem,
    OutOfStock,
    PaymentDeclined,
    Reservation,
    ReservedLine,
)
from shop.common.outcomes import Outcome, classify_status, is_retryable
from shop.common.telemetry import DEPENDENCY_LATENCY, DEPENDENCY_REQUESTS, outbound_headers

log = logging.getLogger("shop.checkout.deps")

SERVICE = "checkout"
MAX_ATTEMPTS = 2
RETRY_BACKOFF_S = 0.1


def _target(base_url: str) -> str:
    parts = urlsplit(base_url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.hostname}:{port}"


class _DependencyCaller:
    def __init__(self, http: httpx.AsyncClient, dependency: str, base_url: str, timeout_s: float):
        self.http = http
        self.dependency = dependency
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.target = _target(base_url)

    async def call(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        handled_statuses: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        """Perform the call; returns responses that are 2xx or in ``handled_statuses``.

        Raises ``DependencyError`` for every other outcome after retries.
        """
        url = self.base_url + path
        last_error: DependencyError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            start = time.perf_counter()
            outcome: Outcome
            status: int | None = None
            detail = ""
            response: httpx.Response | None = None
            try:
                response = await self.http.request(
                    method,
                    url,
                    json=json,
                    headers={**outbound_headers(), **(headers or {})},
                    timeout=self.timeout_s,
                )
                status = response.status_code
                outcome = Outcome.SUCCESS if status in handled_statuses else classify_status(status)
                if outcome != Outcome.SUCCESS:
                    detail = response.text[:200]
            except httpx.TimeoutException as exc:
                outcome, detail = Outcome.TIMEOUT, type(exc).__name__
            except httpx.ConnectError as exc:
                outcome, detail = Outcome.CONNECT_ERROR, str(exc)[:200] or type(exc).__name__
            except httpx.HTTPError as exc:
                outcome, detail = Outcome.BAD_RESPONSE, type(exc).__name__

            elapsed = time.perf_counter() - start
            DEPENDENCY_REQUESTS.labels(SERVICE, self.dependency, operation, outcome.value).inc()
            DEPENDENCY_LATENCY.labels(SERVICE, self.dependency, operation).observe(elapsed)

            if outcome == Outcome.SUCCESS and response is not None:
                return response

            fields = {
                "dependency": self.dependency,
                "operation": operation,
                "target": self.target,
                "outcome": outcome.value,
                "status_code": status,
                "attempt": attempt,
                "duration_ms": round(elapsed * 1000, 1),
                "detail": detail,
            }
            log.warning("dependency call failed", extra={"fields": fields})
            last_error = DependencyError(
                dependency=self.dependency,
                operation=operation,
                outcome=outcome,
                target=self.target,
                detail=detail,
                status_code=status,
            )
            if attempt < MAX_ATTEMPTS and is_retryable(outcome):
                await asyncio.sleep(RETRY_BACKOFF_S * attempt)
                continue
            break
        assert last_error is not None
        raise last_error


def _parse_json(resp: httpx.Response, caller: _DependencyCaller, operation: str) -> dict[str, Any]:
    try:
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("expected object")
        return data
    except ValueError as exc:
        raise DependencyError(
            dependency=caller.dependency,
            operation=operation,
            outcome=Outcome.BAD_RESPONSE,
            target=caller.target,
            detail="response was not a JSON object",
            status_code=resp.status_code,
        ) from exc


class HttpInventoryClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout_s: float) -> None:
        self._c = _DependencyCaller(http, "inventory", base_url, timeout_s)

    async def reserve(self, order_ref: str, items: tuple[LineItem, ...]) -> Reservation:
        resp = await self._c.call(
            "reserve",
            "POST",
            "/api/reservations",
            json={"order_ref": order_ref, "items": [{"sku": i.sku, "qty": i.qty} for i in items]},
            handled_statuses=frozenset({409}),
        )
        data = _parse_json(resp, self._c, "reserve")
        if resp.status_code == 409:
            raise OutOfStock(data.get("error", {}).get("message", "insufficient stock"))
        try:
            return Reservation(
                reservation_id=str(data["reservation_id"]),
                lines=tuple(
                    ReservedLine(str(x["sku"]), int(x["qty"]), int(x["unit_price_cents"])) for x in data["lines"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DependencyError(
                "inventory", "reserve", Outcome.BAD_RESPONSE, self._c.target, "malformed reservation"
            ) from exc

    async def release(self, reservation_id: str) -> None:
        await self._c.call("release", "POST", f"/api/reservations/{reservation_id}/release")

    async def release_for_order(self, order_ref: str) -> None:
        # 404 means no hold exists for this order, which is the outcome we want.
        await self._c.call(
            "release_for_order",
            "POST",
            f"/api/orders/{order_ref}/reservation/release",
            handled_statuses=frozenset({404}),
        )

    async def confirm(self, reservation_id: str) -> None:
        await self._c.call("confirm", "POST", f"/api/reservations/{reservation_id}/confirm")


class HttpPaymentClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, timeout_s: float) -> None:
        self._c = _DependencyCaller(http, "payment", base_url, timeout_s)

    async def charge(self, order_ref: str, amount_cents: int, currency: str, card_token: str) -> Charge:
        resp = await self._c.call(
            "charge",
            "POST",
            "/api/charges",
            json={
                "order_ref": order_ref,
                "amount_cents": amount_cents,
                "currency": currency,
                "card_token": card_token,
            },
            # The order ref doubles as the idempotency key, which makes the
            # retry in _DependencyCaller safe for a non-idempotent operation.
            headers={"Idempotency-Key": order_ref},
            handled_statuses=frozenset({402}),
        )
        data = _parse_json(resp, self._c, "charge")
        if resp.status_code == 402:
            raise PaymentDeclined(data.get("error", {}).get("message", "card declined"))
        try:
            return Charge(charge_id=str(data["charge_id"]), status=str(data["status"]))
        except KeyError as exc:
            raise DependencyError(
                "payment", "charge", Outcome.BAD_RESPONSE, self._c.target, "malformed charge"
            ) from exc
