import asyncio
import os
import time

from .decision_engines import (
    DecisionEngine,
    DecisionEngineError,
    comparison_engines_from_environment,
)
from .foundry_engine import foundry_engine_from_environment
from .hybrid import HybridTriage
from .orchestrator import TriageOrchestrator
from .questions import QUESTIONS
from .schemas import ComparisonResult, ComparisonRun, Incident, ProviderStatus

POLICY_RULES = [
    "If safety or environmental probability is at least 0.75, or severity is at least 2.7/3: escalate.",
    "Else if immediate-isolation probability is at least 0.70: contain.",
    "Else if evidence is below 1.2/2, route confidence is below 0.60, or the model recommends engineering: investigate.",
    "Else if the model recommends emergency: escalate.",
    "Else if the model recommends maintenance: investigate.",
    "Otherwise: monitor.",
    "Contain/escalate and route confidence below 0.75 always require human approval.",
]


class ComparisonService:
    async def compare(
        self, incident: Incident, include_jev: bool = False, hybrid_provider: str = "laya"
    ) -> ComparisonResult:
        typed = comparison_engines_from_environment()
        engines: list[tuple[str, str, DecisionEngine | None]] = [
            (
                "foundry",
                "Foundry - LLM only",
                foundry_engine_from_environment(),
            ),
            ("jev", "Foundry + Jev", typed["jev"] if include_jev else None),
            ("laya", "Foundry + Laya", typed["laya"]),
        ]
        lanes = asyncio.gather(
            *(self._run(provider, label, engine, incident) for provider, label, engine in engines)
        )
        hybrid_engine = typed.get(hybrid_provider)
        hybrid_task = (
            HybridTriage(hybrid_engine).run(incident)
            if hybrid_engine is not None
            else None
        )
        runs, hybrid = await asyncio.gather(
            lanes,
            hybrid_task if hybrid_task is not None else _none(),
            return_exceptions=False,
        )
        return ComparisonResult(
            incident_id=incident.asset_id,
            runs=list(runs),
            questions=QUESTIONS,
            policy_rules=POLICY_RULES,
            hybrid=hybrid,
            hybrid_error=(
                None if hybrid_engine is not None else f"{hybrid_provider} is not configured."
            ),
            model_input={"state": incident.model_dump(), "questions": QUESTIONS},
        )

    @staticmethod
    def provider_status(include_jev: bool = False) -> list[ProviderStatus]:
        typed = comparison_engines_from_environment()
        foundry = foundry_engine_from_environment()
        jev_engine = typed["jev"]
        return [
            ProviderStatus(
                provider="foundry",
                label="Foundry - LLM only",
                available=foundry is not None,
                detail=(
                    "The model generates the decision JSON token by token."
                    if foundry
                    else "Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME."
                ),
                model=getattr(foundry, "model", None),
            ),
            ProviderStatus(
                provider="laya",
                label="Foundry + Laya",
                available=True,
                detail=(
                    "Foundry orchestrates; an open-weight typed model on a remote "
                    "GPU service returns the decision directly."
                    if os.getenv("LAYA_ENDPOINT")
                    else "Foundry orchestrates; an open-weight typed model on the "
                    "local GPU returns the decision directly."
                ),
                model=getattr(typed["laya"], "model", None),
            ),
            ProviderStatus(
                provider="jev",
                label="Foundry + Jev",
                available=jev_engine is not None,
                detail=(
                    "Foundry orchestrates; TypeSafe returns the typed decision."
                    if jev_engine
                    else "Waiting for a TypeSafe API key. Set TYPESAFE_API_KEY to enable this lane."
                ),
                model=getattr(jev_engine, "model", None),
            ),
        ]

    async def _run(
        self,
        provider: str,
        label: str,
        engine: DecisionEngine | None,
        incident: Incident,
    ) -> ComparisonRun:
        if engine is None:
            reason = (
                "Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME."
                if provider == "foundry"
                else "Jev is disabled. Add TYPESAFE_API_KEY and enable the lane."
            )
            return ComparisonRun(
                provider=provider,
                label=label,
                status="unavailable",
                error=reason,
            )
        started = time.perf_counter()
        try:
            result = await TriageOrchestrator(engine).triage(incident)
        except DecisionEngineError as exc:
            return ComparisonRun(
                provider=provider,
                label=label,
                status="failed",
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )

        latency_ms = (time.perf_counter() - started) * 1000
        input_tokens = result.input_tokens
        output_tokens = result.output_tokens
        cost = self._cost(provider, input_tokens, output_tokens)
        return ComparisonRun(
            provider=provider,
            label=label,
            status="completed",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            generated_tokens=output_tokens,
            estimated_cost_usd=cost,
            projected_100k_cost_usd=cost * 100_000 if cost is not None else None,
            projected_100k_generated_tokens=output_tokens * 100_000,
            result=result,
        )

    @staticmethod
    def _cost(provider: str, input_tokens: int, output_tokens: int) -> float | None:
        if provider == "laya":
            return 0.0
        if provider == "jev":
            return input_tokens * 0.042 / 1_000_000
        input_rate = float(os.getenv("FOUNDRY_INPUT_USD_PER_1M", "0"))
        output_rate = float(os.getenv("FOUNDRY_OUTPUT_USD_PER_1M", "0"))
        if input_rate == 0 and output_rate == 0:
            return None
        return (
            input_tokens * input_rate / 1_000_000
            + output_tokens * output_rate / 1_000_000
        )


async def _none() -> None:
    return None
