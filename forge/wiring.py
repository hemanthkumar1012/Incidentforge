"""Composition root: builds adapters and investigators from settings.

This is the only module that knows which concrete adapter backs each port.
The scripted test provider is intentionally not reachable from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from sqlalchemy.orm import Session, sessionmaker

from forge.api.throttle import LoginThrottle
from forge.investigation.engine import LLMInvestigator
from forge.investigation.providers.gemini import GeminiProvider
from forge.investigation.runbook import RunbookInvestigator
from forge.investigation.summary_baseline import SummaryBaselineInvestigator
from forge.investigation.tool_catalog import INVESTIGATOR_SCOPES, build_registry
from forge.investigation.toolkit import ToolContext, ToolRegistry
from forge.services.common import PreconditionFailed
from forge.services.investigations import Investigator, Mode
from forge.services.proposals import PlannerInputs
from forge.settings import ForgeSettings
from forge.telemetry.http_backends import JaegerBackend, LokiBackend, PrometheusBackend
from forge.telemetry.shop_adapters import (
    HttpDiagnostics,
    JourneyVerifier,
    ShopConfigHistory,
    ShopConfigWriter,
)
from forge.validation.sandbox_adapter import SANDBOX_HOSTS, ShopSandbox
from shop.db import make_sync_engine


@dataclass
class Container:
    settings: ForgeSettings

    @cached_property
    def login_throttle(self) -> LoginThrottle:
        return LoginThrottle()

    @cached_property
    def sessions(self) -> sessionmaker[Session]:
        return sessionmaker(make_sync_engine(self.settings.database_url), expire_on_commit=False)

    @cached_property
    def config_history(self) -> ShopConfigHistory:
        return ShopConfigHistory(self.settings.reader_database_url)

    @cached_property
    def config_writer(self) -> ShopConfigWriter:
        return ShopConfigWriter(self.settings.remediator_database_url)

    @cached_property
    def prometheus(self) -> PrometheusBackend:
        return PrometheusBackend(self.settings.prometheus_url)

    @cached_property
    def tools(self) -> ToolRegistry:
        s = self.settings
        return build_registry(
            self.prometheus,
            LokiBackend(s.loki_url),
            JaegerBackend(s.jaeger_url),
            self.config_history,
            HttpDiagnostics(s.service_urls),
        )

    @cached_property
    def sandbox(self) -> ShopSandbox:
        s = self.settings
        return ShopSandbox(s.sandbox_database_url, s.sandbox_urls, s.sandbox_admin_token)

    @cached_property
    def verifier(self) -> JourneyVerifier:
        return JourneyVerifier(self.settings.service_urls["checkout"])

    sandbox_hosts = SANDBOX_HOSTS

    def planner_inputs(self) -> PlannerInputs:
        return PlannerInputs(self.config_history)

    def provider_info(self, mode: Mode) -> tuple[str, str]:
        if mode == "runbook":
            return "runbook", "none"
        if not self.settings.gemini_api_key:
            raise PreconditionFailed("LLM mode needs GEMINI_API_KEY; use runbook mode or configure the key")
        return "gemini", self.settings.gemini_model

    def investigator(self, mode: Mode) -> tuple[Investigator, str, str]:
        ctx = ToolContext(INVESTIGATOR_SCOPES)
        provider, model = self.provider_info(mode)
        if mode == "runbook":
            return RunbookInvestigator(self.tools, ctx), provider, model
        gemini = GeminiProvider(self.settings.gemini_api_key, self.settings.gemini_model)
        if mode == "llm_summary":
            return SummaryBaselineInvestigator(gemini, self.tools, ctx), provider, model
        return LLMInvestigator(gemini, self.tools, ctx), provider, model
