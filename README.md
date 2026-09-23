# Decision Model Arena: Foundry vs Jev vs Laya

A neutral operations demo showing where non-autoregressive typed decision models reduce generated tokens, latency, parsing risk, and variable cost relative to a generative Foundry model doing the same classification work.

- **Foundry baseline:** a deployed generative model is forced to return the seven decisions as JSON.
- **Jev:** hosted typed decisions with zero generated output tokens. Optional — the lane stays disabled until `TYPESAFE_API_KEY` is set, then it can be switched on from the header toggle.
- **Laya:** Apache-2.0 open-weight typed decisions with zero generated output tokens.
- **Typed + LLM:** the typed model answers first and a deterministic gate calls the LLM only for ambiguous or high-stakes cases, where it writes an explanation instead of the decisions.
- **Application policy:** owns thresholds, escalation, and every consequential action.

The scenario is intentionally generic. It can represent a rotating machine, vehicle subsystem, processing unit, refrigeration plant, or other critical asset without identifying a company.

## The two use cases

**01 · Decide the route** (`POST /api/compare`) — seven typed judgements on a critical-asset
incident across four lanes: pure LLM, Jev, Laya, and Laya/Jev + LLM. The saving is *generated*
output tokens, because the typed lanes never write the JSON.

**02 · Decide what the LLM sees** (`POST /api/firewall`) — a context firewall. The typed model
answers a single `noul` question per context line (*is this required to answer the task?*) and
only the kept lines enter the prompt. The saving here is *input* tokens, measured from real
Foundry usage on both the full and the gated prompt. The keep threshold is adjustable in the UI.

## What the typed models actually receive

Jev and Laya are not prompted. Each request is a **state** object plus a **question contract**,
where every question declares one primitive:

| Primitive | Returns |
|-----------|---------|
| `choice`  | One label from a closed set, with a probability for every option. |
| `score`   | An ordinal level, returned as an expected value over the levels. |
| `noul`    | A single probability between 0 and 1 for a yes/no proposition. |

The criteria attached to each option are semantic anchors, not few-shot examples. The model
encodes the state against each question and reads the answer off a decision head, so there is no
generation step and nothing to parse. `GET /api/contract` returns the exact payload, and the UI
renders it verbatim.

## Run locally

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn asset_triage.api:app --reload
```

Open <http://localhost:8000>. Each unavailable lane explains which configuration is missing.
The typed model is preloaded at startup, so the first request is not a cold start.

To use Jev:

```bash
cp .env.example .env
# Set TYPESAFE_API_KEY in .env, restart, then enable the Jev lane from the header toggle.
```

To use Laya:

```bash
.venv/bin/pip install -e ".[laya]"
# The first request downloads convaiinnovations/laya-typed-decisions (~843 MB).
```

For production or a Linux server without a suitable local GPU, deploy Laya separately and
set `LAYA_ENDPOINT` to a `POST /v1/systemone`-compatible endpoint accepting
`{"state", "model", "questions"}` and returning `{"model", "answers", "usage"}`.

## CPU deployment

Laya runs on CPU with no CUDA — it is plain fp32 PyTorch, 421M parameters, ~2.5 GB RSS.
`deploy/Dockerfile` builds a CPU-only image (2.95 GB) with the checkpoint baked in, which cuts
startup from 47 s to 29 s and keeps scale-to-zero viable.

```bash
docker build -f deploy/Dockerfile -t laya-cpu .
docker run -d --cpus 4 -e LAYA_CPU_THREADS=4 -p 8080:8080 laya-cpu
curl localhost:8080/ready
```

Measured on an i7-13800H (AVX2, no AMX):

| Workload | GPU (RTX 4060) | CPU, 6–8 threads | CPU container, 4 vCPU |
|---|---|---|---|
| 7-question triage | 121 ms | 5,940 ms | 7,877 ms |
| Context gate, per line | ~15 ms | 946 ms | 430 ms |

**CPU removes the latency advantage.** At ~6 s, a CPU decision is no faster than the `gpt-5.4`
baseline it is meant to beat. The zero-generated-token and no-per-token-bill arguments survive;
"fast System One decisions" does not. Choose CPU when cost, data boundary, or GPU scarcity
outweighs latency — not to win a latency demo.

Two CPU traps worth knowing:

* **Do not oversubscribe threads.** Torch defaults to one thread per core, which is the slow
  case: 20 threads measured 2.5x slower than 8 on a hybrid P/E-core CPU. `LAYA_CPU_THREADS`
  defaults to `min(8, cpu_count)`.
* **int8 dynamic quantization does not work** on this checkpoint — PyTorch's TransformerEncoder
  fast path rejects quantized linears. bf16 autocast gains nothing without AMX. An AMX-capable
  host (Intel Sapphire/Emerald Rapids, Azure Dsv6/Esv6) is the real CPU lever; older Ice Lake
  v5 and earlier have no AMX.

### Criteria carry the accuracy

The `criteria` strings are the model's only semantic anchor, and they matter more than any other
knob. On the same 16-line stream, gating with a vague *"evidence that changes the answer"* ranked
an unrelated VPN maintenance notice **above** the vibration trend and bearing temperature. The
specific criteria in `asset_triage.firewall.KEEP_QUESTION` ranked bearing temperature, vibration
and the operator report as the top three. With typed models, criteria engineering replaces prompt
engineering — re-measure whenever you edit them.

Absolute probabilities also shift with wording (0.30–0.62 under one phrasing, 0.12–0.30 under
another) while the *ordering* stays stable. Prefer rank-based selection: `/v1/gate` accepts
`top_k` or `keep_fraction` instead of a fixed `threshold`.

To use the Foundry baseline:

```bash
.venv/bin/pip install -e ".[foundry]"
az login
# Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME in .env
```

The API is also directly callable:

```bash
curl -s http://localhost:8000/api/triage \
  -H 'content-type: application/json' \
  -d @data/sample-incident.json

# The typed-question contract, policy rules, and both sample payloads
curl -s http://localhost:8000/api/contract

# Which lanes are configured, used by the header toggle
curl -s http://localhost:8000/api/providers
```

## Foundry hosted-agent path

`hosted_agent.py` exposes the same triage service as a Microsoft Agent Framework tool and uses the Foundry Responses protocol. Install the optional dependencies and configure the two Foundry variables:

```bash
.venv/bin/pip install -e ".[foundry]"
.venv/bin/python hosted_agent.py
```

The comparison reports actual usage returned by each configured provider. Foundry price assumptions are supplied through `FOUNDRY_INPUT_USD_PER_1M` and `FOUNDRY_OUTPUT_USD_PER_1M`; the app does not hard-code model pricing.

See [docs/plan.md](docs/plan.md) for the architecture, rollout, evaluation plan, and the reasons this use case demonstrates the combination clearly.
