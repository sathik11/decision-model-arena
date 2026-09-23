import asyncio
import json
import os
from typing import Any

from .decision_engines import DecisionEngine, DecisionEngineError, JevDecisionEngine
from .questions import QUESTIONS
from .schemas import EngineResult, Incident


class FoundryDecisionEngine(DecisionEngine):
    """Generative LLM baseline forced to produce the same typed decisions."""

    def __init__(self, endpoint: str, model: str) -> None:
        self.endpoint = endpoint
        self.model = model

    async def evaluate(self, incident: Incident) -> EngineResult:
        try:
            return await asyncio.to_thread(self._evaluate_sync, incident)
        except (ImportError, ModuleNotFoundError) as exc:
            raise DecisionEngineError(
                "Foundry SDK dependencies are not installed. Install the project with .[foundry]."
            ) from exc
        except DecisionEngineError:
            raise
        except Exception as exc:
            raise DecisionEngineError(f"Foundry decision call failed: {exc}") from exc

    def _evaluate_sync(self, incident: Incident) -> EngineResult:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=self.endpoint,
            credential=DefaultAzureCredential(),
        ).get_openai_client()
        response = client.responses.create(
            model=self.model,
            instructions=(
                "You are the generative-model baseline in a decision benchmark. "
                "Evaluate every supplied question. Return JSON only with one `answers` "
                "object. Choice answers require type, choice, confidence, probabilities. "
                "Score answers require type, score, confidence, probabilities. Noul "
                "answers require type and noul. Score levels and probability keys are "
                "zero-based: a four-level score ranges from 0 through 3. Do not add prose."
            ),
            input=json.dumps(
                {"state": incident.model_dump(), "questions": QUESTIONS},
                separators=(",", ":"),
            ),
            store=False,
        )
        try:
            body = json.loads(response.output_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DecisionEngineError(
                f"Foundry returned non-JSON output: {response.output_text[:300]}"
            ) from exc
        answers = body.get("answers", {})
        decisions = {
            key: JevDecisionEngine._parse_answer(answer)
            for key, answer in answers.items()
        }
        missing = sorted(set(QUESTIONS) - set(decisions))
        if missing:
            raise DecisionEngineError(
                f"Foundry response omitted decisions: {', '.join(missing)}"
            )
        usage = getattr(response, "usage", None)
        return EngineResult(
            engine="foundry",
            model=self.model,
            decisions=decisions,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


def foundry_engine_from_environment() -> FoundryDecisionEngine | None:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not endpoint or not model:
        return None
    return FoundryDecisionEngine(endpoint=endpoint, model=model)
