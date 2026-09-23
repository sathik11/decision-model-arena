from .decision_engines import DecisionEngine, engine_from_environment
from .schemas import EngineResult, Incident, TriageResult


class TriageOrchestrator:
    def __init__(self, engine: DecisionEngine) -> None:
        self.engine = engine

    @classmethod
    def from_environment(cls) -> "TriageOrchestrator":
        return cls(engine_from_environment())

    async def triage(self, incident: Incident) -> TriageResult:
        result = await self.engine.evaluate(incident)
        decisions = result.decisions
        severity = float(decisions["operational_severity"].value)
        evidence = float(decisions["evidence_sufficiency"].value)
        isolation = float(decisions["requires_immediate_isolation"].value)
        safety = float(decisions["likely_safety_impact"].value)
        environmental = float(decisions["likely_environmental_impact"].value)
        recommendation = str(decisions["recommended_route"].value)
        confidence = decisions["recommended_route"].confidence or 0

        reasons: list[str] = []
        missing: list[str] = []
        if evidence < 1.2:
            missing.extend(
                ["Confirm current operating state", "Capture corroborating sensor readings"]
            )
        if safety >= 0.55:
            reasons.append(f"Safety-impact signal is elevated ({safety:.0%}).")
        if environmental >= 0.55:
            reasons.append(
                f"Environmental-impact signal is elevated ({environmental:.0%})."
            )
        if isolation >= 0.65:
            reasons.append(f"Immediate-isolation signal is elevated ({isolation:.0%}).")
        if severity >= 2:
            reasons.append(f"Operational severity is serious or higher ({severity:.1f}/3).")
        if confidence < 0.6:
            reasons.append(
                f"Routing confidence is low ({confidence:.0%}); do not automate the action."
            )

        if max(safety, environmental) >= 0.75 or severity >= 2.7:
            route = "escalate"
        elif isolation >= 0.7:
            route = "contain"
        elif evidence < 1.2 or confidence < 0.6 or recommendation == "engineering":
            route = "investigate"
        elif recommendation == "emergency":
            route = "escalate"
        elif recommendation == "maintenance":
            route = "investigate"
        else:
            route = "monitor"

        human_required = route in {"contain", "escalate"} or confidence < 0.75
        event_type = decisions["event_type"].value
        summary = (
            f"{incident.asset_id} is assessed as a {event_type} event. "
            f"Policy route: {route}. "
            + (
                "Human approval is required before any operational action."
                if human_required
                else "Continue with the approved monitoring workflow."
            )
        )
        if not reasons:
            reasons.append("No high-risk threshold was crossed.")

        return TriageResult(
            incident_id=incident.asset_id,
            engine=result.engine,
            model=result.model,
            route=route,
            human_approval_required=human_required,
            summary=summary,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            reasons=reasons,
            missing_evidence=missing,
            decisions=decisions,
            warnings=result.warnings,
        )
