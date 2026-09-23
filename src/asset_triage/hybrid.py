"""Use case 1 lane: typed decision model gated with an LLM second opinion.

The typed model answers all seven questions first. A deterministic gate decides
whether the case is clear enough to close without the LLM. Only ambiguous or
high-stakes cases pay for generated tokens.
"""

import asyncio
import json
import os
import time
from typing import Any

from .decision_engines import DecisionEngine, DecisionEngineError
from .orchestrator import TriageOrchestrator
from .questions import QUESTIONS
from .schemas import HybridResult, Incident

GATE_RULES = [
    "Escalate to the LLM when evidence sufficiency is below 1.2 of 2.",
    "Escalate when routing confidence is below 0.75.",
    "Escalate when safety or environmental probability is at least 0.50.",
    "Escalate when the typed model recommends emergency or engineering.",
    "Otherwise close on typed decisions alone and generate nothing.",
]


class HybridTriage:
    """Typed decisions first, LLM only for the cases that need language."""

    def __init__(self, engine: DecisionEngine) -> None:
        self.engine = engine

    async def run(self, incident: Incident) -> HybridResult:
        started = time.perf_counter()
        typed = await TriageOrchestrator(self.engine).triage(incident)
        gate_latency_ms = (time.perf_counter() - started) * 1000

        decisions = typed.decisions
        evidence = float(decisions["evidence_sufficiency"].value)
        confidence = decisions["recommended_route"].confidence or 0.0
        safety = float(decisions["likely_safety_impact"].value)
        environmental = float(decisions["likely_environmental_impact"].value)
        recommendation = str(decisions["recommended_route"].value)

        triggers: list[str] = []
        if evidence < 1.2:
            triggers.append(f"Evidence sufficiency {evidence:.2f} is below 1.2.")
        if confidence < 0.75:
            triggers.append(f"Routing confidence {confidence:.0%} is below 75%.")
        if max(safety, environmental) >= 0.50:
            triggers.append(
                f"Safety/environmental signal {max(safety, environmental):.0%} needs a written justification."
            )
        if recommendation in {"emergency", "engineering"}:
            triggers.append(f"Typed model recommends {recommendation}.")

        result = HybridResult(
            typed_result=typed,
            gate_rules=GATE_RULES,
            gate_triggers=triggers,
            escalated=bool(triggers),
            gate_latency_ms=gate_latency_ms,
            typed_input_tokens=typed.input_tokens,
            route=typed.route,
        )
        if not triggers:
            result.narrative = (
                "Closed on typed decisions alone. No generated tokens were spent "
                "because every gate threshold was satisfied."
            )
            result.total_latency_ms = gate_latency_ms
            return result

        try:
            llm_started = time.perf_counter()
            body = await asyncio.to_thread(self._second_opinion, incident, typed, triggers)
            result.llm_latency_ms = (time.perf_counter() - llm_started) * 1000
            result.narrative = body["narrative"]
            result.llm_input_tokens = body["input_tokens"]
            result.llm_generated_tokens = body["output_tokens"]
            result.llm_model = body["model"]
        except DecisionEngineError as exc:
            result.error = str(exc)
        except Exception as exc:  # pragma: no cover - transport failures
            result.error = f"LLM second opinion failed: {exc}"

        result.total_latency_ms = (time.perf_counter() - started) * 1000
        return result

    @staticmethod
    def _second_opinion(
        incident: Incident, typed: Any, triggers: list[str]
    ) -> dict[str, Any]:
        endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if not endpoint or not model:
            raise DecisionEngineError(
                "Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME."
            )
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=endpoint, credential=DefaultAzureCredential()
        ).get_openai_client()
        decisions = {
            key: {
                "value": decision.value,
                "confidence": decision.confidence,
            }
            for key, decision in typed.decisions.items()
        }
        response = client.responses.create(
            model=model,
            instructions=(
                "The typed decision model has already scored every field. Do not "
                "re-score them and do not return JSON. Write at most four "
                "sentences for the duty engineer explaining the situation, the "
                "reason this case was escalated, and what to verify first."
            ),
            input=json.dumps(
                {
                    "state": incident.model_dump(),
                    "typed_decisions": decisions,
                    "policy_route": typed.route,
                    "escalation_triggers": triggers,
                    "question_catalogue": list(QUESTIONS),
                },
                separators=(",", ":"),
            ),
            store=False,
        )
        usage = getattr(response, "usage", None)
        return {
            "narrative": response.output_text,
            "model": model,
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }
