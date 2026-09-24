from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .comparison import POLICY_RULES, ComparisonService
from .decision_engines import (
    DecisionEngineError,
    LayaDecisionEngine,
    RemoteLayaDecisionEngine,
    comparison_engines_from_environment,
)
from .firewall import KEEP_QUESTION, ContextFirewall
from .orchestrator import TriageOrchestrator
from .questions import QUESTIONS
from .scenarios import FIREWALL_SAMPLE, INCIDENT_SAMPLE
from .schemas import (
    ComparisonResult,
    FirewallRequest,
    FirewallResult,
    Incident,
    ProviderStatus,
    TriageResult,
)

load_dotenv(override=False)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the typed model so the first user request is not a cold start."""
    import asyncio

    engine = comparison_engines_from_environment().get("laya")
    if isinstance(engine, LayaDecisionEngine):
        try:
            await asyncio.to_thread(engine.agent)
        except Exception as exc:  # pragma: no cover - optional dependency
            print(f"Laya preload skipped: {exc}")
    elif isinstance(engine, RemoteLayaDecisionEngine):
        # Scale-to-zero means the GPU container is cold until something asks.
        # Do it at startup rather than leaving the first visitor to wait ~90 s.
        try:
            where = await engine.warm()
            print(f"Remote Laya warm: {where}")
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"Remote Laya warm failed: {exc}")
    yield


app = FastAPI(title="Critical Asset Triage", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CompareRequest(BaseModel):
    incident: Incident
    include_jev: bool = False
    hybrid_provider: str = "laya"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/providers", response_model=list[ProviderStatus])
async def providers() -> list[ProviderStatus]:
    return ComparisonService.provider_status()


@app.get("/api/contract")
async def contract() -> dict:
    """The exact typed-question payload that is sent to Jev or Laya."""
    return {
        "triage_questions": QUESTIONS,
        "firewall_question": KEEP_QUESTION,
        "policy_rules": POLICY_RULES,
        "samples": {"incident": INCIDENT_SAMPLE, "firewall": FIREWALL_SAMPLE},
        "primitives": {
            "choice": "One label from a closed set, with a probability for every option.",
            "score": "An ordinal level, returned as an expected value over the levels.",
            "noul": "A single probability between 0 and 1 for a yes/no proposition.",
        },
    }


@app.post("/api/triage", response_model=TriageResult)
async def triage(incident: Incident) -> TriageResult:
    try:
        return await TriageOrchestrator.from_environment().triage(incident)
    except DecisionEngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/compare", response_model=ComparisonResult)
async def compare(request: CompareRequest) -> ComparisonResult:
    return await ComparisonService().compare(
        request.incident,
        include_jev=request.include_jev,
        hybrid_provider=request.hybrid_provider,
    )


@app.post("/api/firewall", response_model=FirewallResult)
async def firewall(request: FirewallRequest) -> FirewallResult:
    try:
        return await ContextFirewall().run(request)
    except DecisionEngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
