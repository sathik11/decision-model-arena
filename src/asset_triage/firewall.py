"""Use case 2: a typed decision model acting as a context firewall for an LLM.

The typed model scores every candidate context item with a single `noul`
question. Only items above the keep threshold are placed in the LLM prompt, so
the saving here is *input* tokens rather than generated tokens.
"""

import asyncio
import json
import os
import time
from typing import Any

from .decision_engines import (
    DecisionEngine,
    DecisionEngineError,
    LayaDecisionEngine,
    comparison_engines_from_environment,
)
from .schemas import (
    FirewallItem,
    FirewallRequest,
    FirewallResult,
    FirewallRun,
)

KEEP_QUESTION = {
    "context_is_required": {
        "type": "noul",
        "instructions": (
            "Is this context line required to answer the operator task? Answer "
            "only about this single line."
        ),
        "criteria": {
            "true": (
                "The line carries asset condition, measurement, history, threshold, "
                "timing, safety, or resource evidence that changes the answer."
            ),
            "false": (
                "The line is administrative, social, or unrelated background that "
                "cannot change the answer."
            ),
        },
    }
}


def approx_tokens(text: str) -> int:
    """Rough shared-basis estimate used only for per-item bars."""
    return max(1, round(len(text) / 4))


class ContextFirewall:
    """Score context items with a typed model, then answer with and without gating."""

    async def run(self, request: FirewallRequest) -> FirewallResult:
        threshold = request.threshold
        engine = self._typed_engine(request.provider)
        started = time.perf_counter()
        scores = await self._score_items(engine, request)
        gate_latency_ms = (time.perf_counter() - started) * 1000

        items = [
            FirewallItem(
                index=index,
                text=text,
                keep_probability=score,
                keep=score >= threshold,
                approx_tokens=approx_tokens(text),
            )
            for index, (text, score) in enumerate(zip(request.items, scores))
        ]
        kept = [item for item in items if item.keep]

        baseline, gated = await asyncio.gather(
            self._answer(request.task, [item.text for item in items], "Full context"),
            self._answer(request.task, [item.text for item in kept], "Firewalled context"),
            return_exceptions=True,
        )
        baseline_run = self._as_run(baseline, "llm_only", "Pure LLM · every line in the prompt")
        gated_run = self._as_run(
            gated, "typed_plus_llm", "Typed firewall + LLM · only kept lines"
        )
        gated_run.gate_latency_ms = gate_latency_ms
        gated_run.gate_model = self._engine_name(engine, request.provider)

        return FirewallResult(
            task=request.task,
            threshold=threshold,
            gate_question=KEEP_QUESTION,
            items=items,
            runs=[baseline_run, gated_run],
            calibration_note=self._calibration_note(scores),
        )

    @staticmethod
    def _calibration_note(scores: list[float]) -> str:
        if not scores:
            return ""
        spread = max(scores) - min(scores)
        band = f"{min(scores):.2f} to {max(scores):.2f}"
        if spread < 0.45:
            return (
                f"These probabilities span only {band}. This open-weight checkpoint was not "
                "trained on this gate question, so its absolute values are compressed and the "
                "ranking is more trustworthy than the raw number. Move the threshold to see the "
                "effect, and calibrate on your own labelled context before trusting a fixed cut."
            )
        return (
            f"Probabilities span {band}, a usable separation at this threshold. Still validate "
            "against labelled context before production use."
        )

    def _typed_engine(self, provider: str) -> DecisionEngine:
        engines = comparison_engines_from_environment()
        engine = engines.get(provider)
        if engine is None:
            raise DecisionEngineError(
                f"The {provider} decision model is not configured."
            )
        return engine

    @staticmethod
    def _engine_name(engine: DecisionEngine, provider: str) -> str:
        return getattr(engine, "model", provider)

    async def _score_items(
        self, engine: DecisionEngine, request: FirewallRequest
    ) -> list[float]:
        if isinstance(engine, LayaDecisionEngine):
            return await asyncio.to_thread(self._score_local, engine, request)
        return await asyncio.gather(
            *(self._score_remote(engine, request.task, text) for text in request.items)
        )

    @staticmethod
    def _score_local(engine: LayaDecisionEngine, request: FirewallRequest) -> list[float]:
        agent = engine.agent()
        scores: list[float] = []
        for text in request.items:
            state = {"task": request.task, "context_line": text}
            answer = agent.predict(state, KEEP_QUESTION)["answers"][
                "context_is_required"
            ]
            scores.append(float(answer.get("noul", 0.0)))
        return scores

    @staticmethod
    async def _score_remote(engine: DecisionEngine, task: str, text: str) -> float:
        import httpx

        api_key = getattr(engine, "api_key", None)
        timeout = getattr(engine, "timeout", 60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                engine.endpoint,
                headers=(
                    {"Authorization": f"Bearer {api_key}"} if api_key else {}
                ),
                json={
                    "state": {"task": task, "context_line": text},
                    "model": engine.model,
                    "questions": KEEP_QUESTION,
                },
            )
        if response.status_code >= 400:
            raise DecisionEngineError(
                f"Context gate returned HTTP {response.status_code}: {response.text[:200]}"
            )
        answer = response.json()["answers"]["context_is_required"]
        return float(answer.get("noul", 0.0))

    async def _answer(self, task: str, lines: list[str], label: str) -> dict[str, Any]:
        endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if not endpoint or not model:
            raise DecisionEngineError(
                "Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME."
            )
        started = time.perf_counter()
        body = await asyncio.to_thread(self._call_foundry, endpoint, model, task, lines)
        body["latency_ms"] = (time.perf_counter() - started) * 1000
        body["label"] = label
        body["lines"] = len(lines)
        body["model"] = model
        return body

    @staticmethod
    def _call_foundry(
        endpoint: str, model: str, task: str, lines: list[str]
    ) -> dict[str, Any]:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=endpoint, credential=DefaultAzureCredential()
        ).get_openai_client()
        response = client.responses.create(
            model=model,
            instructions=(
                "You are an operations assistant. Use only the supplied context. "
                "Answer the task in at most three sentences and state the "
                "recommended action explicitly."
            ),
            input=json.dumps({"task": task, "context": lines}, separators=(",", ":")),
            store=False,
        )
        usage = getattr(response, "usage", None)
        return {
            "answer": response.output_text,
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }

    @staticmethod
    def _as_run(payload: Any, lane: str, label: str) -> FirewallRun:
        if isinstance(payload, BaseException):
            return FirewallRun(lane=lane, label=label, status="failed", error=str(payload))
        return FirewallRun(
            lane=lane,
            label=label,
            status="completed",
            answer=payload["answer"],
            model=payload["model"],
            context_lines=payload["lines"],
            input_tokens=payload["input_tokens"],
            output_tokens=payload["output_tokens"],
            llm_latency_ms=payload["latency_ms"],
        )
