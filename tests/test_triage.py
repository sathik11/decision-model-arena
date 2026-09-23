import pytest

from asset_triage.decision_engines import RulesDecisionEngine
from asset_triage.orchestrator import TriageOrchestrator
from asset_triage.schemas import Incident


@pytest.mark.asyncio
async def test_serious_mechanical_incident_requires_human_approval() -> None:
    incident = Incident(
        asset_id="ASSET-042",
        asset_type="rotating equipment",
        location="North area",
        report=(
            "Metallic grinding noise, rapidly rising vibration, and a hot bearing smell."
        ),
        sensor_summary={"vibration": "above trip advisory", "temperature": "94 C"},
        recent_work=["Alignment inspection deferred"],
    )

    result = await TriageOrchestrator(RulesDecisionEngine()).triage(incident)

    assert result.route in {"contain", "escalate"}
    assert result.human_approval_required is True
    assert result.decisions["event_type"].value == "mechanical"


@pytest.mark.asyncio
async def test_stable_observation_routes_to_monitoring() -> None:
    incident = Incident(
        asset_id="ASSET-007",
        asset_type="pump",
        location="Utility area",
        report="Routine inspection notes a faint noise. Readings are stable and normal.",
        sensor_summary={"vibration": "normal", "temperature": "normal"},
        recent_work=["Preventive service completed yesterday"],
    )

    result = await TriageOrchestrator(RulesDecisionEngine()).triage(incident)

    assert result.route in {"monitor", "investigate"}
    assert result.route != "escalate"


@pytest.mark.asyncio
async def test_hybrid_gate_skips_llm_when_signals_are_clear() -> None:
    from asset_triage.hybrid import HybridTriage
    from asset_triage.schemas import Decision, EngineResult

    class ClearEngine(RulesDecisionEngine):
        async def evaluate(self, incident: Incident) -> EngineResult:
            return EngineResult(
                engine="stub",
                model="stub",
                input_tokens=120,
                decisions={
                    "event_type": Decision(kind="choice", value="mechanical", confidence=0.95),
                    "operational_severity": Decision(kind="score", value=0.6, confidence=0.9),
                    "evidence_sufficiency": Decision(kind="score", value=1.9, confidence=0.9),
                    "requires_immediate_isolation": Decision(kind="noul", value=0.05),
                    "likely_safety_impact": Decision(kind="noul", value=0.04),
                    "likely_environmental_impact": Decision(kind="noul", value=0.03),
                    "recommended_route": Decision(
                        kind="choice", value="monitor", confidence=0.93
                    ),
                },
            )

    result = await HybridTriage(ClearEngine()).run(
        Incident(
            asset_id="ASSET-007",
            asset_type="pump",
            location="Utility area",
            report="Routine inspection notes stable readings within normal limits.",
            sensor_summary={"vibration": "normal"},
            recent_work=["Preventive service completed yesterday"],
        )
    )

    assert result.escalated is False
    assert result.gate_triggers == []
    assert result.llm_generated_tokens == 0
    assert result.route == "monitor"


@pytest.mark.asyncio
async def test_hybrid_gate_escalates_on_weak_evidence() -> None:
    from asset_triage.hybrid import HybridTriage

    result = await HybridTriage(RulesDecisionEngine()).run(
        Incident(
            asset_id="ASSET-042",
            asset_type="rotating equipment",
            location="North area",
            report="Metallic grinding noise, rapidly rising vibration, hot bearing smell.",
            sensor_summary={"vibration": "above trip advisory"},
            recent_work=["Alignment inspection deferred"],
        )
    )

    assert result.escalated is True
    assert result.gate_triggers


def test_firewall_keep_question_is_a_single_noul() -> None:
    from asset_triage.firewall import KEEP_QUESTION

    assert list(KEEP_QUESTION) == ["context_is_required"]
    assert KEEP_QUESTION["context_is_required"]["type"] == "noul"


def test_contract_endpoint_exposes_questions_and_samples() -> None:
    from fastapi.testclient import TestClient

    from asset_triage.api import app

    with TestClient(app) as client:
        body = client.get("/api/contract").json()
        assert len(body["triage_questions"]) == 7
        assert body["samples"]["firewall"]["items"]
        assert set(body["primitives"]) == {"choice", "score", "noul"}

        providers = client.get("/api/providers").json()
        assert {entry["provider"] for entry in providers} == {"foundry", "laya", "jev"}
        assert client.get("/").status_code == 200
