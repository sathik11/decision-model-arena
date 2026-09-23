# Plan: critical asset incident triage

## Why this demo

This scenario makes the division of labor visible in one short workflow:

1. An operator submits a messy incident report plus structured sensor and maintenance context.
2. A typed decision engine evaluates atomic questions in parallel: event type, severity, evidence sufficiency, isolation need, safety/environmental signals, and routing.
3. Deterministic policy converts those probabilities into `monitor`, `investigate`, `contain`, or `escalate`.
4. A Foundry agent explains the result, retrieves relevant procedures, asks for missing evidence, and drafts a work order.
5. A human remains the approver for safety-critical or destructive actions.

The same pattern transfers to engineering services, transport operations, grocery cold-chain/store assets, and energy operations without copying any customer's processes or data.

## Capability boundary

| Layer | Responsibility | Must not own |
|---|---|---|
| Jev / local decision model | Fast semantic choice, score, detection, probability, confidence | Arithmetic, final side effects, long-form generation |
| Policy code | Thresholds, precedence, approvals, allowed actions, audit fields | Unstructured interpretation |
| Foundry model/agent | Conversation, synthesis, grounded explanation, procedure retrieval, tool orchestration | Ungated shutdown, dispatch, or safety decisions |
| Human operator | Confirmation, exception handling, accountable action | Repetitive first-pass triage |

## MVP architecture

```text
Web UI / API
    |
    v
Triage Orchestrator
    |---- DecisionEngine interface
    |       |---- Foundry generative JSON baseline
    |       |---- Jev hosted typed decisions
    |       |---- Laya open-weight typed decisions
    |       `---- transparent rules (offline functional fallback)
    |
    |---- deterministic risk policy
    `---- explanation builder

Foundry hosted agent
    `---- triage_incident tool -> same orchestrator
```

The MVP deliberately does not execute operational actions. It emits a proposed route and `human_approval_required`.

## Foundry coexistence

- **Hosted agent:** packages the workflow behind the Responses protocol.
- **Foundry IQ / Azure AI Search:** grounds explanations in operating procedures, manuals, prior incidents, and safety controls.
- **Toolbox/OpenAPI:** later connects read-only asset history and approved work-management actions.
- **Observability:** records model calls, decision-engine calls, selected routes, latency, and human overrides.
- **Evaluation:** tests explanation quality separately from decision calibration and policy correctness.
- **Guardrails/control plane:** governs agent versions, tools, identity, network access, and runtime policies.

Jev remains an external HTTPS dependency. In production, place the call behind a small internal decision service so credentials, retries, timeouts, data minimization, and provider replacement remain centralized.

## Decision questions

Each question is atomic and receives only incident-relevant state:

- `event_type`: mechanical, electrical, process, instrumentation, environmental, unknown.
- `operational_severity`: observation, degraded, serious, critical.
- `evidence_sufficiency`: insufficient, partial, sufficient.
- `requires_immediate_isolation`: yes probability.
- `likely_safety_impact`: yes probability.
- `likely_environmental_impact`: yes probability.
- `recommended_route`: monitor, maintenance, engineering, emergency.

Code performs all numeric comparisons and applies conservative thresholds. Low confidence never becomes automatic action.

## Delivery phases

1. **Local MVP (implemented):** synthetic scenarios, Foundry/Jev/Laya comparison lanes, policy routing, token/latency UI, tests.
2. **Foundry integration:** deploy hosted agent, add Foundry model, connect procedure knowledge, trace both model layers.
3. **Evaluation:** create 100-300 labeled synthetic incidents, measure route accuracy, critical-event recall, calibration, abstention, latency, explanation groundedness, and override rate.
4. **Read-only pilot:** ingest de-identified incidents and manuals; no operational writes.
5. **Controlled actions:** add approved work-order creation behind identity, confirmation, idempotency, and full audit.

## Success measures

| Measure | Initial gate |
|---|---:|
| Critical-event recall | >= 95% on labeled evaluation set |
| Unsafe auto-action rate | 0% |
| Low-confidence cases routed to review | 100% |
| Route accuracy | >= 85% |
| P95 decision latency | < 1 second |
| Grounded explanation score | >= 4/5 |
| Human override rate after tuning | < 20% |

Thresholds are hypotheses, not production claims. They must be tuned against domain-reviewed data.

## Comparison methodology

The arena sends the same state and seven questions to three implementations:

- **Foundry generative baseline:** produces JSON token by token. Measure input tokens,
  generated output tokens, end-to-end latency, schema success, and configured model cost.
- **Jev:** returns typed decision heads. Measure input tokens reported by the API, zero
  generated output tokens, network latency, and Jev input-token cost.
- **Laya:** returns typed decision heads in a forward pass. Measure tokenizer input count,
  zero generated output tokens, inference latency, and separately account for hosting cost.

Do not describe Jev or Laya as consuming "zero tokens." They tokenize their inputs. Their
advantage is zero autoregressive output tokens, no prose-to-JSON conversion, batchable
decision heads, and a smaller/specialized inference path.

## Key risks and controls

- **External data handling:** minimize the state sent to Jev; remove identifiers and secrets.
- **Prompt injection in incident text:** treat reports as data, use precise questions, screen retrieved passages, and never let text alter policy code.
- **Provider outage:** expose the engine used and fallback reason; fail to human review for high-stakes cases.
- **Calibration drift:** pin model versions, log distributions, and rerun regression suites before upgrades.
- **False precision:** display probability/confidence with evidence gaps; do not present them as guaranteed risk likelihood.
