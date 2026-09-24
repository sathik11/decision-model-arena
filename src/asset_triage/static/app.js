const $ = (id) => document.getElementById(id);
const state = { contract: null, providers: [], includeJev: false, comparison: null };

/* ---------- utilities ---------- */

const num = (value) => (value ?? 0).toLocaleString();
const ms = (value) => (value == null ? "—" : `${Math.round(value)} ms`);
const titleCase = (key) => key.replaceAll("_", " ");

function highlightJson(value) {
  return JSON.stringify(value, null, 2)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"([^"]+)":/g, '<span class="k">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="s">"$1"</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="n">$1</span>');
}

/* ---------- provider strip and Jev toggle ---------- */

function renderProviders() {
  const strip = $("status-strip");
  const jev = state.providers.find((provider) => provider.provider === "jev");
  const chips = state.providers
    .filter((provider) => provider.provider !== "jev")
    .map(
      (provider) => `<span class="chip" title="${provider.detail}">
        <i class="dot ${provider.available ? "on" : "off"}"></i>${provider.label}
        ${provider.model ? `<code style="color:var(--dim);font-size:10.5px">${provider.model.split("/").pop()}</code>` : ""}
      </span>`
    )
    .join("");

  const enabled = state.includeJev && jev?.available;
  strip.innerHTML = `${chips}
    <button class="toggle ${enabled ? "on" : ""}" id="jev-toggle"
      aria-disabled="${!jev?.available}" title="${jev?.detail || ""}">
      <i class="switch"></i>Jev lane${jev?.available ? "" : " · no key"}
    </button>`;

  $("jev-toggle").addEventListener("click", () => {
    if (!jev?.available) {
      $("triage-note").textContent = jev.detail;
      $("triage-note").classList.add("err");
      return;
    }
    state.includeJev = !state.includeJev;
    localStorage.setItem("includeJev", state.includeJev ? "1" : "0");
    renderProviders();
  });
}

/* ---------- contract rendering ---------- */

function renderContract() {
  const questions = state.contract.triage_questions;
  $("contract-list").innerHTML = Object.entries(questions)
    .map(([id, question], index) => {
      const criteria = Array.isArray(question.criteria)
        ? question.criteria.map((text, level) => [`level ${level}`, text])
        : Object.entries(question.criteria || {});
      return `<div class="q-row" data-q="${id}">
        <div class="q-idx">${String(index + 1).padStart(2, "0")}</div>
        <div class="kind ${question.type}">${question.type}</div>
        <div>
          <div class="q-name">${titleCase(id)}</div>
          <div class="q-instr">${question.instructions}</div>
          <div class="q-criteria">${criteria
            .map(([key, text]) => `<div class="criterion"><b>${key}</b><span>${text}</span></div>`)
            .join("")}</div>
          <button class="q-toggle">Show criteria sent to the model</button>
        </div>
      </div>`;
    })
    .join("");

  document.querySelectorAll(".q-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const row = button.closest(".q-row");
      row.classList.toggle("open");
      button.textContent = row.classList.contains("open")
        ? "Hide criteria"
        : "Show criteria sent to the model";
    });
  });

  $("fw-question").innerHTML = highlightJson(state.contract.firewall_question);
}

function renderPayload(incident) {
  const payload = { state: incident, questions: state.contract.triage_questions };
  $("payload").innerHTML = highlightJson(payload);
  $("payload-size").textContent = `${num(JSON.stringify(payload).length)} chars`;
}

function renderPolicyRules(fired = []) {
  $("policy-rules").innerHTML = state.contract.policy_rules
    .map(
      (rule, index) =>
        `<li class="${fired.includes(index) ? "fired" : ""}">${rule}</li>`
    )
    .join("");
}

/* ---------- use case 1 ---------- */

function readIncident() {
  let sensors;
  try {
    sensors = JSON.parse($("sensors").value);
  } catch {
    throw new Error("Sensor summary must be valid JSON.");
  }
  return {
    asset_id: $("asset_id").value,
    asset_type: $("asset_type").value,
    location: $("location").value,
    report: $("report").value,
    sensor_summary: sensors,
    recent_work: $("work").value.split("\n").map((line) => line.trim()).filter(Boolean),
  };
}

function laneCard(run) {
  if (run.status !== "completed") {
    return `<div class="lane">
      <div class="lane-kind">${run.provider === "foundry" ? "Generative" : "Typed"}</div>
      <h4>${run.label}</h4>
      <div class="model">unavailable</div>
      <div class="lane-error">${run.error || run.status}</div>
    </div>`;
  }
  const route = run.result.route;
  return `<div class="lane">
    <div class="lane-kind">${run.provider === "foundry" ? "Generative baseline" : "Typed decisions"}</div>
    <h4>${run.provider === "foundry" ? "Foundry &middot; LLM only" : run.provider === "jev" ? "Foundry + Jev" : "Foundry + Laya"}</h4>
    <div class="model">${run.result.model}</div>
    <div class="figure">${num(run.generated_tokens)}</div>
    <div class="figure-label">generated tokens</div>
    <div class="route-tag route-${route}">${route}</div>
    <div class="stat"><span>Latency</span><b>${ms(run.latency_ms)}</b></div>
    <div class="stat"><span>Input tokens</span><b>${num(run.input_tokens)}</b></div>
    <div class="stat"><span>JSON parsing</span><b>${run.provider === "foundry" ? "required" : "none"}</b></div>
    <div class="stat"><span>Per 100k incidents</span><b class="${run.generated_tokens ? "" : "zero"}">${num(run.projected_100k_generated_tokens)}</b></div>
    <div class="stat"><span>Human approval</span><b>${run.result.human_approval_required ? "yes" : "no"}</b></div>
  </div>`;
}

function hybridLaneCard(hybrid) {
  if (!hybrid) return "";
  const generated = hybrid.llm_generated_tokens;
  return `<div class="lane hybrid">
    <div class="lane-kind">Typed + generative</div>
    <h4>Laya → LLM</h4>
    <div class="model">gated escalation</div>
    <div class="figure">${num(generated)}</div>
    <div class="figure-label">generated tokens</div>
    <div class="route-tag route-${hybrid.route}">${hybrid.route}</div>
    <div class="stat"><span>Gate latency</span><b>${ms(hybrid.gate_latency_ms)}</b></div>
    <div class="stat"><span>LLM latency</span><b>${hybrid.escalated ? ms(hybrid.llm_latency_ms) : "skipped"}</b></div>
    <div class="stat"><span>Escalated</span><b class="${hybrid.escalated ? "" : "zero"}">${hybrid.escalated ? "yes" : "no"}</b></div>
    <div class="stat"><span>Triggers fired</span><b>${hybrid.gate_triggers.length} / ${hybrid.gate_rules.length - 1}</b></div>
    <div class="stat"><span>Role of the LLM</span><b>${hybrid.escalated ? "explain" : "none"}</b></div>
  </div>`;
}

function renderFlows(data) {
  const foundry = data.runs.find((run) => run.provider === "foundry" && run.status === "completed");
  const typed = data.runs.find((run) => run.provider === "laya" && run.status === "completed");
  const hybrid = data.hybrid;
  const arrow = '<i class="link"></i>';
  const rows = [];

  if (foundry) {
    rows.push(`<div class="flow"><div class="flow-name">Foundry &middot; LLM only</div>
      <span class="node">state + 7 questions</span>${arrow}
      <span class="node">prompt ${num(foundry.input_tokens)} tok</span>${arrow}
      <span class="node gen">generate JSON ${num(foundry.generated_tokens)} tok</span>${arrow}
      <span class="node">parse + validate</span>${arrow}
      <span class="node">policy → ${foundry.result.route}</span></div>`);
  }
  if (typed) {
    rows.push(`<div class="flow"><div class="flow-name">Foundry + typed</div>
      <span class="node">state + 7 questions</span>${arrow}
      <span class="node">encode ${num(typed.input_tokens)} units</span>${arrow}
      <span class="node free">decision heads · 0 generated</span>${arrow}
      <span class="node skip">no parsing needed</span>${arrow}
      <span class="node">policy → ${typed.result.route}</span></div>`);
  }
  if (hybrid) {
    rows.push(`<div class="flow"><div class="flow-name">Foundry + typed + LLM</div>
      <span class="node">state + 7 questions</span>${arrow}
      <span class="node free">decision heads · 0 generated</span>${arrow}
      <span class="node">gate</span>${arrow}
      ${
        hybrid.escalated
          ? `<span class="node gen">explain ${num(hybrid.llm_generated_tokens)} tok</span>${arrow}`
          : `<span class="node skip">LLM skipped</span>${arrow}`
      }
      <span class="node">policy → ${hybrid.route}</span></div>`);
  }
  $("flows").innerHTML = rows.join("");
}

function renderHybrid(hybrid, error) {
  if (!hybrid) {
    $("hybrid").innerHTML = `<div class="empty">${error || "Hybrid lane unavailable."}</div>`;
    return;
  }
  const triggers = hybrid.gate_triggers;
  $("hybrid").innerHTML = `
    <ol class="rules">${hybrid.gate_rules
      .map((rule, index) => {
        const fired = index < triggers.length && triggers.length > 0 && index < 4
          ? triggers.some((trigger) => matchesRule(rule, trigger))
          : false;
        return `<li class="${fired ? "fired" : ""}">${rule}</li>`;
      })
      .join("")}</ol>
    <div class="answers" style="margin-top:30px">
      <div class="answer">
        <div class="lane-kind">Gate outcome</div>
        <h4 style="margin:0 0 12px;font-weight:450;letter-spacing:-.02em">${
          hybrid.escalated ? "Escalated to the LLM" : "Closed without generation"
        }</h4>
        ${
          triggers.length
            ? `<ul style="margin:0;padding-left:18px;color:var(--muted);font-size:.87rem">${triggers
                .map((trigger) => `<li>${trigger}</li>`)
                .join("")}</ul>`
            : '<p style="color:var(--muted);font-size:.87rem;margin:0">No gate rule fired. The typed decisions were sufficient on their own.</p>'
        }
        <div class="stat" style="margin-top:18px"><span>Typed input tokens</span><b>${num(hybrid.typed_input_tokens)}</b></div>
        <div class="stat"><span>LLM input tokens</span><b>${num(hybrid.llm_input_tokens)}</b></div>
        <div class="stat"><span>LLM generated tokens</span><b class="${hybrid.llm_generated_tokens ? "" : "zero"}">${num(hybrid.llm_generated_tokens)}</b></div>
        <div class="stat"><span>Total latency</span><b>${ms(hybrid.total_latency_ms)}</b></div>
      </div>
      <div class="answer">
        <div class="lane-kind">Final output to the duty engineer</div>
        <div class="route-tag route-${hybrid.route}" style="margin-top:12px">${hybrid.route}</div>
        <p class="body">${hybrid.narrative || hybrid.error || "—"}</p>
        <div class="stat"><span>Typed summary</span><b style="font-family:inherit;font-weight:400;text-align:right">${hybrid.typed_result.summary}</b></div>
      </div>
    </div>`;
}

function matchesRule(rule, trigger) {
  const key = rule.toLowerCase();
  const text = trigger.toLowerCase();
  if (key.includes("evidence")) return text.includes("evidence");
  if (key.includes("confidence")) return text.includes("confidence");
  if (key.includes("safety")) return text.includes("safety");
  if (key.includes("emergency")) return text.includes("recommends");
  return false;
}

function decisionBlock(id, decision, other) {
  const probs = Object.entries(decision.probabilities || {}).sort((a, b) => b[1] - a[1]);
  const top = probs[0]?.[0];
  const value = typeof decision.value === "number" ? decision.value.toFixed(2) : decision.value;
  const disagrees =
    other &&
    (typeof decision.value === "number"
      ? Math.abs(decision.value - Number(other.value)) >= 0.25
      : decision.value !== other.value);
  return `<div class="dec ${disagrees ? "disagree" : ""}">
    <div class="dec-top">
      <span class="dec-name">${titleCase(id)}${
        disagrees ? ' <span class="disagree-flag">· disagrees</span>' : ""
      }</span>
      <span><span class="dec-val">${value}</span>${
        decision.confidence == null
          ? ""
          : `<span class="dec-conf">${(decision.confidence * 100).toFixed(0)}%</span>`
      }</span>
    </div>
    ${
      probs.length
        ? `<div class="probs">${probs
            .map(
              ([name, probability]) => `<div class="prob ${name === top ? "top" : ""}">
                <span>${name}</span>
                <span class="track"><i style="width:${Math.min(100, probability * 100).toFixed(1)}%"></i></span>
                <span class="pct">${(probability * 100).toFixed(1)}</span>
              </div>`
            )
            .join("")}</div>`
        : ""
    }
  </div>`;
}

function renderDetail(data) {
  const completed = data.runs.filter((run) => run.status === "completed");
  if (!completed.length) {
    $("detail").innerHTML = '<div class="empty">No lane produced decisions.</div>';
    return;
  }
  const reference = completed.find((run) => run.provider === "laya") || completed[0];
  $("detail").innerHTML = completed
    .map((run) => {
      const other = run === reference ? null : reference.result.decisions;
      return `<div class="detail-col">
        <h4>${run.provider === "foundry" ? "Foundry &middot; LLM only" : run.provider === "jev" ? "Foundry + Jev" : "Foundry + Laya"}</h4>
        <div class="model">${run.result.model} · route ${run.result.route}</div>
        ${Object.entries(run.result.decisions)
          .map(([id, decision]) => decisionBlock(id, decision, other?.[id]))
          .join("")}
        <div class="dec"><div class="dec-name" style="margin-bottom:6px">Why policy chose ${run.result.route}</div>
          <ul style="margin:0;padding-left:16px;color:var(--dim);font-size:.8rem">${run.result.reasons
            .map((reason) => `<li>${reason}</li>`)
            .join("")}</ul></div>
      </div>`;
    })
    .join("");
}

function renderLedger(data) {
  const foundry = data.runs.find((run) => run.provider === "foundry" && run.status === "completed");
  const typed = data.runs.find((run) => run.provider === "laya" && run.status === "completed");
  const hybrid = data.hybrid;
  if (!foundry || !typed) {
    $("ledger").innerHTML = '<div><div class="big">—</div><div class="cap">need both lanes</div></div>';
    return;
  }
  const saved = foundry.generated_tokens - typed.generated_tokens;
  const hybridSaved = hybrid ? foundry.generated_tokens - hybrid.llm_generated_tokens : null;
  const speed = foundry.latency_ms / typed.latency_ms;
  $("ledger").innerHTML = `
    <div><div class="big">${num(saved)}</div><div class="cap">generated tokens removed</div>
      <div class="fine">The LLM wrote ${num(foundry.generated_tokens)} tokens of JSON. The typed model wrote none.</div></div>
    <div><div class="big">${num(saved * 100000)}</div><div class="cap">per 100,000 incidents</div>
      <div class="fine">Generation is the only part that disappears. Input still costs compute.</div></div>
    <div><div class="big">${speed.toFixed(1)}×</div><div class="cap">faster warm decision</div>
      <div class="fine">${ms(foundry.latency_ms)} versus ${ms(typed.latency_ms)} end to end.</div></div>
    ${
      hybridSaved == null
        ? ""
        : `<div><div class="big">${num(hybridSaved)}</div><div class="cap">removed by the hybrid</div>
      <div class="fine">${
        hybrid.escalated
          ? `Escalated, so the LLM still wrote ${num(hybrid.llm_generated_tokens)} tokens of explanation instead of ${num(foundry.generated_tokens)} tokens of JSON.`
          : "The gate closed the case, so no generation happened at all."
      }</div></div>`
    }`;
}

async function runTriage() {
  const button = $("run-triage");
  const note = $("triage-note");
  note.classList.remove("err");
  let incident;
  try {
    incident = readIncident();
  } catch (error) {
    note.textContent = error.message;
    note.classList.add("err");
    return;
  }
  renderPayload(incident);
  button.disabled = true;
  note.textContent = "Running lanes…";
  try {
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        incident,
        include_jev: state.includeJev,
        hybrid_provider: $("hybrid_provider").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Comparison failed");
    state.comparison = data;
    $("lanes").innerHTML =
      data.runs
        .filter((run) => !(run.provider === "jev" && !state.includeJev))
        .map(laneCard)
        .join("") + hybridLaneCard(data.hybrid);
    renderFlows(data);
    renderHybrid(data.hybrid, data.hybrid_error);
    renderDetail(data);
    renderLedger(data);
    renderPolicyRules(firedPolicyRules(data));
    note.textContent = "Complete.";
  } catch (error) {
    note.textContent = error.message;
    note.classList.add("err");
  } finally {
    button.disabled = false;
  }
}

function firedPolicyRules(data) {
  const typed = data.runs.find((run) => run.provider === "laya" && run.status === "completed");
  if (!typed) return [];
  const route = typed.result.route;
  const map = { escalate: [0], contain: [1], investigate: [2], monitor: [5] };
  const fired = map[route] ? [...map[route]] : [];
  if (typed.result.human_approval_required) fired.push(6);
  return fired;
}

/* ---------- use case 2 ---------- */

function renderFirewall(data) {
  state.firewall = data;
  const kept = data.items.filter((item) => item.keep);
  const dropped = data.items.length - kept.length;
  $("fw-summary").innerHTML = `The typed model kept <b>${kept.length}</b> of
    <b>${data.items.length}</b> lines and dropped <b>${dropped}</b> at a threshold of
    p ≥ ${data.threshold.toFixed(2)}.`;
  $("fw-calibration").textContent = data.calibration_note || "";
  $("fw-list").innerHTML = data.items
    .map(
      (item) => `<div class="fw-item ${item.keep ? "keep" : "drop"}">
        <span class="n">${String(item.index + 1).padStart(2, "0")}</span>
        <span class="text">${item.text}</span>
        <span class="p">p(keep) ${item.keep_probability.toFixed(3)} · ~${item.approx_tokens} tok</span>
        <span class="badge">${item.keep ? "KEEP" : "DROP"}</span>
      </div>`
    )
    .join("");

  const baseline = data.runs.find((run) => run.lane === "llm_only");
  const gated = data.runs.find((run) => run.lane === "typed_plus_llm");
  const savedInput =
    baseline?.status === "completed" && gated?.status === "completed"
      ? baseline.input_tokens - gated.input_tokens
      : null;

  $("fw-answers").innerHTML = data.runs
    .map((run) => {
      if (run.status !== "completed") {
        return `<div class="answer"><div class="lane-kind">${run.label}</div>
          <div class="lane-error">${run.error}</div></div>`;
      }
      const isGated = run.lane === "typed_plus_llm";
      return `<div class="answer">
        <div class="lane-kind">${isGated ? "Foundry + typed firewall" : "Foundry &middot; LLM only"}</div>
        <div class="figure">${num(run.input_tokens)}</div>
        <div class="figure-label">input tokens</div>
        <p class="body">${run.answer}</p>
        <div class="stat"><span>Context lines in prompt</span><b>${run.context_lines}</b></div>
        <div class="stat"><span>Generated tokens</span><b>${num(run.output_tokens)}</b></div>
        <div class="stat"><span>Gate latency</span><b>${isGated ? ms(run.gate_latency_ms) : "n/a"}</b></div>
        <div class="stat"><span>Gate model</span><b style="font-size:.72rem">${
          isGated ? (run.gate_model || "").split("/").pop() : "none"
        }</b></div>
        ${
          isGated && savedInput != null
            ? `<div class="stat"><span>Input tokens avoided</span><b class="zero">${num(savedInput)}</b></div>`
            : ""
        }
      </div>`;
    })
    .join("");
}

async function runFirewall() {
  const button = $("run-firewall");
  const note = $("fw-note");
  note.classList.remove("err");
  button.disabled = true;
  note.textContent = "Scoring each line, then answering twice…";
  try {
    const response = await fetch("/api/firewall", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        task: $("fw_task").value,
        items: $("fw_items").value.split("\n").map((line) => line.trim()).filter(Boolean),
        provider: state.includeJev ? "jev" : "laya",
        threshold: Number($("fw_threshold").value),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Firewall run failed");
    renderFirewall(data);
    note.textContent = "Complete.";
  } catch (error) {
    note.textContent = error.message;
    note.classList.add("err");
  } finally {
    button.disabled = false;
  }
}

/* ---------- boot ---------- */

document.querySelectorAll(".scenario-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".scenario-tab").forEach((other) =>
      other.setAttribute("aria-selected", String(other === tab))
    );
    const scenario = tab.dataset.scenario;
    $("view-triage").classList.toggle("hidden", scenario !== "triage");
    $("view-firewall").classList.toggle("hidden", scenario !== "firewall");
    window.scrollTo({ top: 260, behavior: "smooth" });
  });
});

$("run-triage").addEventListener("click", runTriage);
$("run-firewall").addEventListener("click", runFirewall);

$("fw_threshold").addEventListener("input", (event) => {
  const threshold = Number(event.target.value);
  $("fw_threshold_value").textContent = threshold.toFixed(2);
  if (!state.firewall) return;
  const preview = {
    ...state.firewall,
    threshold,
    items: state.firewall.items.map((item) => ({
      ...item,
      keep: item.keep_probability >= threshold,
    })),
  };
  const kept = preview.items.filter((item) => item.keep).length;
  renderFirewall(preview);
  $("fw-note").classList.remove("err");
  $("fw-note").textContent = `Preview only · ${kept} lines would be kept. Re-run to answer with this threshold.`;
});

(async function boot() {
  state.includeJev = localStorage.getItem("includeJev") === "1";
  const [providers, contract] = await Promise.all([
    fetch("/api/providers").then((response) => response.json()),
    fetch("/api/contract").then((response) => response.json()),
  ]);
  state.providers = providers;
  state.contract = contract;
  renderProviders();
  renderContract();
  renderPolicyRules();

  const incident = contract.samples.incident;
  $("asset_id").value = incident.asset_id;
  $("asset_type").value = incident.asset_type;
  $("location").value = incident.location;
  $("report").value = incident.report;
  $("sensors").value = JSON.stringify(incident.sensor_summary, null, 2);
  $("work").value = incident.recent_work.join("\n");
  renderPayload(incident);

  $("fw_task").value = contract.samples.firewall.task;
  $("fw_items").value = contract.samples.firewall.items.join("\n");
})();
