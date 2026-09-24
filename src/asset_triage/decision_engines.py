import asyncio
import json
import math
import os
import threading
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .questions import QUESTIONS
from .schemas import Decision, EngineResult, Incident


class DecisionEngineError(RuntimeError):
    pass


class DecisionEngine(ABC):
    @abstractmethod
    async def evaluate(self, incident: Incident) -> EngineResult:
        raise NotImplementedError


class JevDecisionEngine(DecisionEngine):
    def __init__(self, api_key: str, endpoint: str, model: str) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.timeout = float(os.getenv("JEV_HTTP_TIMEOUT", "60"))

    async def evaluate(self, incident: Incident) -> EngineResult:
        payload = {
            "state": incident.model_dump(),
            "model": self.model,
            "questions": QUESTIONS,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise DecisionEngineError(
                f"Jev returned HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        decisions = {
            key: self._parse_answer(answer)
            for key, answer in body.get("answers", {}).items()
        }
        missing = sorted(set(QUESTIONS) - set(decisions))
        if missing:
            raise DecisionEngineError(f"Jev response omitted decisions: {', '.join(missing)}")
        usage = body.get("usage", {})
        return EngineResult(
            engine="jev",
            model=body.get("model", self.model),
            decisions=decisions,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    @staticmethod
    def _parse_answer(answer: dict[str, Any]) -> Decision:
        kind = answer["type"]
        if kind == "choice":
            return Decision(
                kind=kind,
                value=answer["choice"],
                confidence=answer["confidence"],
                probabilities=answer["probabilities"],
            )
        if kind == "score":
            return Decision(
                kind=kind,
                value=float(answer["score"]),
                confidence=answer["confidence"],
                probabilities=answer["probabilities"],
            )
        return Decision(kind=kind, value=float(answer["noul"]))


class LayaDecisionEngine(DecisionEngine):
    _agents: dict[tuple[str, str | None, str | None], Any] = {}
    _load_lock = threading.Lock()

    def __init__(
        self,
        model: str,
        subfolder: str | None = None,
        device: str | None = None,
    ) -> None:
        self.model = model
        self.subfolder = subfolder
        self.device = device

    @classmethod
    def get_agent(cls, model: str, subfolder: str | None, device: str | None) -> Any:
        """Load the checkpoint once, even when several lanes start together."""
        import laya

        key = (model, subfolder, device)
        with cls._load_lock:
            if key not in cls._agents:
                cls._configure_cpu_threads(device)
                kwargs: dict[str, Any] = {}
                if subfolder:
                    kwargs["subfolder"] = subfolder
                if device:
                    kwargs["device"] = device
                cls._agents[key] = laya.load(model, **kwargs)
        return cls._agents[key]

    @staticmethod
    def _configure_cpu_threads(device: str | None) -> None:
        """Cap CPU threads.

        Oversubscribing this model is actively harmful: on a hybrid
        performance/efficiency core CPU, 20 threads measured 2.5x slower than 8
        because the efficiency cores stall the matmul. Torch defaults to one
        thread per core, so the default is the slow case.
        """
        if device not in (None, "cpu"):
            return
        configured = os.getenv("LAYA_CPU_THREADS")
        try:
            import torch

            if device == "cpu" or not torch.cuda.is_available():
                threads = int(configured) if configured else min(8, os.cpu_count() or 8)
                torch.set_num_threads(max(1, threads))
        except ImportError:
            pass

    def agent(self) -> Any:
        return self.get_agent(self.model, self.subfolder, self.device)

    async def evaluate(self, incident: Incident) -> EngineResult:
        try:
            body = await asyncio.to_thread(self._predict, incident)
        except (ImportError, ModuleNotFoundError) as exc:
            raise DecisionEngineError(
                "Laya is not installed. Install the project with .[laya]."
            ) from exc
        except Exception as exc:
            raise DecisionEngineError(f"Laya inference failed: {exc}") from exc

        answers = body.get("answers", {})
        decisions = {
            key: JevDecisionEngine._parse_answer(answer)
            for key, answer in answers.items()
        }
        missing = sorted(set(QUESTIONS) - set(decisions))
        if missing:
            raise DecisionEngineError(f"Laya response omitted decisions: {', '.join(missing)}")
        usage = body.get("usage", {})
        return EngineResult(
            engine="laya",
            model=self._model_name(),
            decisions=decisions,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=0,
        )

    def _predict(self, incident: Incident) -> dict[str, Any]:
        return self.agent().predict(incident.model_dump(), QUESTIONS)

    def _model_name(self) -> str:
        return f"{self.model}/{self.subfolder}" if self.subfolder else self.model


class RemoteLayaDecisionEngine(DecisionEngine):
    """Call a remotely hosted Laya service using the Jev-compatible request shape."""

    def __init__(self, endpoint: str, model: str) -> None:
        self.endpoint = endpoint
        self.model = model
        # A scale-to-zero GPU container takes 54-86 s to answer its first
        # request: image pull, CUDA init, then model load. A 30 s timeout turns
        # a normal cold start into a failed lane.
        self.timeout = float(os.getenv("LAYA_HTTP_TIMEOUT", "180"))

    async def warm(self) -> str:
        """Ask the remote service to spin up before a user is waiting on it."""
        base = self.endpoint.rsplit("/v1/", 1)[0]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{base}/ready")
            response.raise_for_status()
            body = response.json()
        return f"{body.get('device')} {body.get('gpu') or ''}".strip()

    async def evaluate(self, incident: Incident) -> EngineResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.endpoint,
                json={
                    "state": incident.model_dump(),
                    "model": self.model,
                    "questions": QUESTIONS,
                },
            )
        if response.status_code >= 400:
            raise DecisionEngineError(
                f"Remote Laya returned HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        decisions = {
            key: JevDecisionEngine._parse_answer(answer)
            for key, answer in body.get("answers", {}).items()
        }
        missing = sorted(set(QUESTIONS) - set(decisions))
        if missing:
            raise DecisionEngineError(
                f"Remote Laya response omitted decisions: {', '.join(missing)}"
            )
        usage = body.get("usage", {})
        return EngineResult(
            engine="laya",
            model=body.get("model", self.model),
            decisions=decisions,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=0,
        )


class RulesDecisionEngine(DecisionEngine):
    """Transparent offline baseline, not a substitute for a calibrated semantic model."""

    async def evaluate(self, incident: Incident) -> EngineResult:
        text = " ".join(
            [
                incident.report,
                json.dumps(incident.sensor_summary),
                " ".join(incident.recent_work),
            ]
        ).lower()
        groups = {
            "mechanical": ["vibration", "grinding", "bearing", "alignment", "noise", "crack"],
            "electrical": ["arc", "short", "voltage", "current", "breaker", "electrical"],
            "process": ["pressure", "flow", "temperature", "overheat", "quality", "process"],
            "instrumentation": ["sensor", "calibration", "signal", "controller", "instrument"],
            "environmental": ["leak", "spill", "emission", "contamination", "discharge"],
        }
        counts = {name: sum(term in text for term in terms) for name, terms in groups.items()}
        event_type = max(counts, key=counts.get)
        if counts[event_type] == 0:
            event_type = "unknown"
        choice_probs = self._choice_probabilities(counts, event_type)

        critical_terms = ["fire", "explosion", "injury", "smoke", "rapidly", "trip", "rupture"]
        serious_terms = ["rising", "hot", "grinding", "above", "alarm", "failed", "worsen"]
        severity = min(
            3.0,
            0.4
            + 0.65 * sum(term in text for term in serious_terms)
            + 1.0 * sum(term in text for term in critical_terms),
        )
        evidence_items = bool(incident.sensor_summary) + bool(incident.recent_work)
        evidence = min(2.0, 0.5 + 0.7 * evidence_items)
        safety = self._bounded_probability(text, ["injury", "fire", "smoke", "explosion", "hot"])
        environmental = self._bounded_probability(
            text, ["leak", "spill", "emission", "contamination", "discharge"]
        )
        isolation = min(0.98, 0.15 + severity * 0.22 + max(safety, environmental) * 0.35)

        if max(safety, environmental) >= 0.7 or severity >= 2.7:
            recommended = "emergency"
        elif event_type == "unknown" or evidence < 1.1:
            recommended = "engineering"
        elif event_type in {"mechanical", "electrical", "instrumentation"}:
            recommended = "maintenance"
        else:
            recommended = "monitor"

        confidence = min(0.92, 0.45 + 0.08 * sum(counts.values()) + 0.1 * evidence_items)
        return EngineResult(
            engine="rules",
            model="transparent-keyword-baseline",
            warnings=[
                "Using the offline rules baseline; probabilities are illustrative and not calibrated."
            ],
            decisions={
                "event_type": Decision(
                    kind="choice",
                    value=event_type,
                    confidence=confidence,
                    probabilities=choice_probs,
                ),
                "operational_severity": Decision(
                    kind="score",
                    value=severity,
                    confidence=confidence,
                    probabilities=self._score_probabilities(severity, 4),
                ),
                "evidence_sufficiency": Decision(
                    kind="score",
                    value=evidence,
                    confidence=0.8,
                    probabilities=self._score_probabilities(evidence, 3),
                ),
                "requires_immediate_isolation": Decision(kind="noul", value=isolation),
                "likely_safety_impact": Decision(kind="noul", value=safety),
                "likely_environmental_impact": Decision(kind="noul", value=environmental),
                "recommended_route": Decision(
                    kind="choice",
                    value=recommended,
                    confidence=confidence,
                    probabilities={
                        key: 0.7 if key == recommended else 0.1
                        for key in ["monitor", "maintenance", "engineering", "emergency"]
                    },
                ),
            },
        )

    @staticmethod
    def _bounded_probability(text: str, terms: list[str]) -> float:
        matches = sum(term in text for term in terms)
        return min(0.95, 0.08 + matches * 0.29)

    @staticmethod
    def _choice_probabilities(
        counts: dict[str, int], winner: str
    ) -> dict[str, float]:
        names = [*counts, "unknown"]
        weights = {name: float(counts.get(name, 0) + 1) for name in names}
        if winner == "unknown":
            weights["unknown"] += 3
        total = sum(weights.values())
        return {name: round(weight / total, 4) for name, weight in weights.items()}

    @staticmethod
    def _score_probabilities(value: float, levels: int) -> dict[str, float]:
        weights = [math.exp(-2 * abs(index - value)) for index in range(levels)]
        total = sum(weights)
        return {str(index): round(weight / total, 4) for index, weight in enumerate(weights)}


class FallbackDecisionEngine(DecisionEngine):
    def __init__(self, engines: list[DecisionEngine]) -> None:
        self.engines = engines

    async def evaluate(self, incident: Incident) -> EngineResult:
        failures: list[str] = []
        for engine in self.engines:
            try:
                result = await engine.evaluate(incident)
                result.warnings = [*failures, *result.warnings]
                return result
            except (DecisionEngineError, httpx.HTTPError) as exc:
                failures.append(f"{engine.__class__.__name__} unavailable: {exc}")
        raise DecisionEngineError("; ".join(failures))


def engine_from_environment() -> DecisionEngine:
    mode = os.getenv("DECISION_ENGINE", "auto").lower()
    # TYPESAFE_KEY is accepted as an alias: it is the name most people reach
    # for first, and a silently disabled Jev lane is hard to diagnose.
    jev_key = os.getenv("TYPESAFE_API_KEY") or os.getenv("TYPESAFE_KEY")
    jev = (
        JevDecisionEngine(
            api_key=jev_key,
            endpoint=os.getenv(
                "TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone"
            ),
            model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
        )
        if jev_key
        else None
    )
    laya_endpoint = os.getenv("LAYA_ENDPOINT")
    laya = (
        RemoteLayaDecisionEngine(
            endpoint=laya_endpoint,
            model=os.getenv(
                "LAYA_MODEL", "convaiinnovations/laya-typed-decisions"
            ),
        )
        if laya_endpoint
        else LayaDecisionEngine(
            model=os.getenv(
                "LAYA_MODEL", "convaiinnovations/laya-typed-decisions"
            ),
            subfolder=os.environ.get("LAYA_SUBFOLDER", "") or None,
            device=os.getenv("LAYA_DEVICE") or None,
        )
    )
    rules = RulesDecisionEngine()

    if mode == "jev":
        if not jev:
            raise DecisionEngineError("DECISION_ENGINE=jev requires TYPESAFE_API_KEY")
        return jev
    if mode == "laya":
        return laya
    if mode == "rules":
        return rules
    return FallbackDecisionEngine([engine for engine in [jev, laya, rules] if engine])


def comparison_engines_from_environment() -> dict[str, DecisionEngine | None]:
    # TYPESAFE_KEY is accepted as an alias: it is the name most people reach
    # for first, and a silently disabled Jev lane is hard to diagnose.
    jev_key = os.getenv("TYPESAFE_API_KEY") or os.getenv("TYPESAFE_KEY")
    laya_endpoint = os.getenv("LAYA_ENDPOINT")
    return {
        "jev": JevDecisionEngine(
            api_key=jev_key,
            endpoint=os.getenv(
                "TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone"
            ),
            model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
        )
        if jev_key
        else None,
        "laya": (
            RemoteLayaDecisionEngine(
                endpoint=laya_endpoint,
                model=os.getenv(
                    "LAYA_MODEL", "convaiinnovations/laya-typed-decisions"
                ),
            )
            if laya_endpoint
            else LayaDecisionEngine(
                model=os.getenv(
                    "LAYA_MODEL", "convaiinnovations/laya-typed-decisions"
                ),
                subfolder=os.environ.get("LAYA_SUBFOLDER", "") or None,
                device=os.getenv("LAYA_DEVICE") or None,
            )
        ),
    }
