"""Laya typed-decision service, tuned for CPU-only hosting.

Design notes that matter on CPU:

* Threads are capped. Torch defaults to one thread per core, and on this model
  oversubscription measured 2.5x *slower* than 8 threads. `LAYA_CPU_THREADS`
  overrides the cap.
* The checkpoint is loaded at startup, not on first request, so the ~45 s load
  never lands on a user. `/health` stays up while `/ready` reports the load.
* A batch endpoint answers many questions in one call, which avoids per-request
  overhead for context-gating workloads.
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

MODEL = os.getenv("LAYA_MODEL", "convaiinnovations/laya-typed-decisions")
DEVICE = os.getenv("LAYA_DEVICE", "cpu")
SUBFOLDER = os.environ.get("LAYA_SUBFOLDER", "") or None

_state: dict[str, Any] = {
    "agent": None,
    "ready": False,
    "load_seconds": None,
    "threads": None,
}


def _configure_threads() -> int:
    import torch

    configured = os.getenv("LAYA_CPU_THREADS")
    threads = int(configured) if configured else min(8, os.cpu_count() or 8)
    torch.set_num_threads(max(1, threads))
    return torch.get_num_threads()


def _load() -> None:
    import laya

    started = time.perf_counter()
    _state["threads"] = _configure_threads()
    _state["agent"] = laya.load(MODEL, subfolder=SUBFOLDER, device=DEVICE)
    _state["load_seconds"] = round(time.perf_counter() - started, 1)
    _state["ready"] = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio

    await asyncio.to_thread(_load)
    yield


app = FastAPI(title="Laya typed-decision service", lifespan=lifespan)


class DecisionRequest(BaseModel):
    state: str | dict[str, Any] | list[Any]
    model: str = MODEL
    questions: dict[str, dict[str, Any]]


class GateRequest(BaseModel):
    """Score many context lines against one task in a single call."""

    task: str
    lines: list[str]
    threshold: float = 0.5
    top_k: int | None = None
    keep_fraction: float | None = None
    instructions: str = (
        "Is this context line required to answer the operator task? Answer only "
        "about this single line."
    )
    # Criteria are the model's only semantic anchor, and they carry most of the
    # accuracy. Measured on the same 16-line stream: these specific criteria
    # ranked vibration, bearing temperature and the operator report top, while a
    # vague "evidence that changes the answer" wording ranked an unrelated VPN
    # maintenance notice above all three. Keep these in sync with
    # asset_triage.firewall.KEEP_QUESTION and re-measure whenever they change.
    criteria_true: str = (
        "The line carries asset condition, measurement, history, threshold, "
        "timing, safety, or resource evidence that changes the answer."
    )
    criteria_false: str = (
        "The line is administrative, social, or unrelated background that "
        "cannot change the answer."
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ready": _state["ready"]}


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {
        "ready": _state["ready"],
        "model": MODEL,
        "device": DEVICE,
        "torch_threads": _state["threads"],
        "load_seconds": _state["load_seconds"],
    }


@app.post("/v1/systemone")
def system_one(request: DecisionRequest) -> dict[str, Any]:
    started = time.perf_counter()
    result = _state["agent"].predict(request.state, request.questions)
    result["model"] = request.model
    result.setdefault("usage", {}).setdefault("output_tokens", 0)
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


@app.post("/v1/gate")
def gate(request: GateRequest) -> dict[str, Any]:
    """Context firewall in one round trip instead of one request per line.

    Each line is scored against its own state. Folding every line into a single
    state and asking N questions was measured to be both slower (2054 ms vs
    946 ms per line, because each question then encodes the whole stream) and
    wrong, because a question could no longer tell which line it was judging
    and kept all of them.
    """
    question = {
        "context_is_required": {
            "type": "noul",
            "instructions": request.instructions,
            "criteria": {
                "true": request.criteria_true,
                "false": request.criteria_false,
            },
        }
    }
    started = time.perf_counter()
    scored = []
    for index, text in enumerate(request.lines):
        answers = _state["agent"].predict(
            {"task": request.task, "context_line": text}, question
        )["answers"]
        scored.append((index, text, float(answers["context_is_required"]["noul"])))

    # Rank-based selection is the safer default. Absolute probabilities from an
    # uncalibrated checkpoint shift with question wording -- the same stream
    # scored 0.30-0.62 under one phrasing and 0.12-0.30 under another -- so a
    # fixed threshold can silently keep everything or nothing. The ordering
    # stayed stable across both phrasings.
    budget = request.top_k
    if budget is None and request.keep_fraction is not None:
        budget = max(1, round(len(request.lines) * request.keep_fraction))
    if budget is not None:
        keep_indices = {
            index
            for index, _, _ in sorted(scored, key=lambda row: row[2], reverse=True)[:budget]
        }
        mode = f"top_{budget}"
    else:
        keep_indices = {index for index, _, score in scored if score >= request.threshold}
        mode = f"threshold_{request.threshold}"

    items = [
        {
            "index": index,
            "text": text,
            "keep_probability": score,
            "keep": index in keep_indices,
        }
        for index, text, score in scored
    ]
    probabilities = [score for _, _, score in scored]
    return {
        "model": MODEL,
        "selection_mode": mode,
        "threshold": request.threshold,
        "probability_range": [min(probabilities), max(probabilities)],
        "kept": len(keep_indices),
        "total": len(items),
        "items": items,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
