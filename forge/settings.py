"""Control-plane settings, read once from the environment (see docs/configuration.md)."""

from __future__ import annotations

import os
from dataclasses import dataclass


class SettingsError(RuntimeError):
    pass


def _req(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SettingsError(f"environment variable {name} is required")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


@dataclass(frozen=True)
class ForgeSettings:
    database_url: str
    reader_database_url: str
    remediator_database_url: str
    sandbox_database_url: str
    sandbox_admin_token: str
    jwt_secret: str
    prometheus_url: str
    loki_url: str
    jaeger_url: str
    service_urls: dict[str, str]
    sandbox_urls: dict[str, str]
    default_mode: str
    gemini_api_key: str
    gemini_model: str
    llm_input_usd_per_mtok: float
    llm_output_usd_per_mtok: float
    detector_enabled: bool
    detector_min_failures: float
    bootstrap_users: str

    @classmethod
    def from_env(cls) -> ForgeSettings:
        secret = _req("FORGE_JWT_SECRET")
        if len(secret) < 32:
            raise SettingsError("FORGE_JWT_SECRET must be at least 32 characters")
        mode = _opt("FORGE_DEFAULT_MODE", "runbook")
        if mode not in ("runbook", "llm"):
            raise SettingsError("FORGE_DEFAULT_MODE must be 'runbook' or 'llm'")
        return cls(
            database_url=_req("FORGE_DATABASE_URL"),
            reader_database_url=_req("FORGE_READER_DATABASE_URL"),
            remediator_database_url=_req("FORGE_REMEDIATOR_DATABASE_URL"),
            sandbox_database_url=_req("SANDBOX_DATABASE_URL"),
            sandbox_admin_token=_req("SANDBOX_ADMIN_TOKEN"),
            jwt_secret=secret,
            prometheus_url=_opt("PROMETHEUS_URL", "http://prometheus:9090"),
            loki_url=_opt("LOKI_URL", "http://loki:3100"),
            jaeger_url=_opt("JAEGER_URL", "http://jaeger:16686"),
            service_urls={
                "checkout": _opt("CHECKOUT_URL", "http://checkout:8000"),
                "inventory": _opt("INVENTORY_URL", "http://inventory:8001"),
                "payment": _opt("PAYMENT_URL", "http://payment:8002"),
            },
            sandbox_urls={
                "checkout": _opt("SANDBOX_CHECKOUT_URL", "http://sandbox-checkout:8000"),
                "inventory": _opt("SANDBOX_INVENTORY_URL", "http://sandbox-inventory:8001"),
                "payment": _opt("SANDBOX_PAYMENT_URL", "http://sandbox-payment:8002"),
            },
            default_mode=mode,
            gemini_api_key=_opt("GEMINI_API_KEY"),
            gemini_model=_opt("GEMINI_MODEL", "gemini-2.5-flash"),
            # Used only for the *estimated* cost shown in the UI and the benchmark report.
            llm_input_usd_per_mtok=float(_opt("LLM_INPUT_USD_PER_MTOK", "0.30")),
            llm_output_usd_per_mtok=float(_opt("LLM_OUTPUT_USD_PER_MTOK", "2.50")),
            detector_enabled=_opt("DETECTOR_ENABLED", "true").lower() == "true",
            detector_min_failures=float(_opt("DETECTOR_MIN_FAILURES", "5")),
            bootstrap_users=_opt("FORGE_BOOTSTRAP_USERS"),
        )
