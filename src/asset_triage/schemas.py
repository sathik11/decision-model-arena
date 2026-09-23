from typing import Any, Literal

from pydantic import BaseModel, Field


class Incident(BaseModel):
    asset_id: str = Field(min_length=1)
    asset_type: str = Field(min_length=1)
    location: str = Field(min_length=1)
    report: str = Field(min_length=10)
    sensor_summary: dict[str, Any] = Field(default_factory=dict)
    recent_work: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    kind: Literal["choice", "score", "noul"]
    value: str | float
    confidence: float | None = Field(default=None, ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict)


class EngineResult(BaseModel):
    engine: str
    model: str
    decisions: dict[str, Decision]
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class TriageResult(BaseModel):
    incident_id: str
    engine: str
    model: str
    route: Literal["monitor", "investigate", "contain", "escalate"]
    human_approval_required: bool
    summary: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasons: list[str]
    missing_evidence: list[str]
    decisions: dict[str, Decision]
    warnings: list[str] = Field(default_factory=list)


class HybridResult(BaseModel):
    typed_result: TriageResult
    gate_rules: list[str]
    gate_triggers: list[str]
    escalated: bool
    route: str
    narrative: str | None = None
    llm_model: str | None = None
    gate_latency_ms: float = 0
    llm_latency_ms: float = 0
    total_latency_ms: float = 0
    typed_input_tokens: int = 0
    llm_input_tokens: int = 0
    llm_generated_tokens: int = 0
    error: str | None = None


class FirewallRequest(BaseModel):
    task: str = Field(min_length=10)
    items: list[str] = Field(min_length=1)
    provider: Literal["jev", "laya"] = "laya"
    threshold: float = Field(default=0.5, ge=0, le=1)


class FirewallItem(BaseModel):
    index: int
    text: str
    keep_probability: float
    keep: bool
    approx_tokens: int


class FirewallRun(BaseModel):
    lane: Literal["llm_only", "typed_plus_llm"]
    label: str
    status: Literal["completed", "failed"]
    answer: str | None = None
    model: str | None = None
    gate_model: str | None = None
    context_lines: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    gate_latency_ms: float = 0
    llm_latency_ms: float = 0
    error: str | None = None


class FirewallResult(BaseModel):
    task: str
    threshold: float
    gate_question: dict[str, Any]
    items: list[FirewallItem]
    runs: list[FirewallRun]
    calibration_note: str | None = None


class ProviderStatus(BaseModel):
    provider: str
    label: str
    available: bool
    detail: str
    model: str | None = None


class ComparisonRun(BaseModel):
    provider: Literal["foundry", "jev", "laya"]
    label: str
    status: Literal["completed", "unavailable", "failed"]
    latency_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    generated_tokens: int = 0
    estimated_cost_usd: float | None = None
    projected_100k_cost_usd: float | None = None
    projected_100k_generated_tokens: int = 0
    result: TriageResult | None = None
    error: str | None = None


class ComparisonResult(BaseModel):
    incident_id: str
    runs: list[ComparisonRun]
    questions: dict[str, dict[str, Any]]
    policy_rules: list[str]
    hybrid: HybridResult | None = None
    hybrid_error: str | None = None
    model_input: dict[str, Any] | None = None
    note: str = (
        "Token counts are measured from each provider response when available. "
        "Laya is self-hosted, so its input tokens are compute units rather than billed API tokens."
    )
