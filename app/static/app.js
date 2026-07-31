const $ = (id) => document.getElementById(id);
const number = (value, maximumFractionDigits = 2) =>
  Number(value || 0).toLocaleString(undefined, {maximumFractionDigits});
let currentBriefId = null;
let refreshCount = 0;

async function json(url) {
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    throw new Error(`${url}: ${error.message}`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string"
      ? body.detail
      : body.detail?.reason || body.detail?.code;
    throw new Error(`${url}: ${detail || `request failed (${response.status})`}`);
  }
  return response.json();
}

function appendChat(kind, text) {
  const node = document.createElement("div");
  node.className = `chat-message ${kind}`;
  node.textContent = text;
  $("chat-messages").appendChild(node);
  node.scrollIntoView({behavior: "smooth", block: "nearest"});
}

async function askChat(event) {
  event.preventDefault();
  const input = $("chat-question");
  const question = input.value.trim();
  if (!question) return;
  appendChat("user", question);
  input.value = "";
  $("chat-send").disabled = true;
  $("chat-state").textContent = "thinking";
  try {
    const response = await fetch("/api/v0/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-BitAgent-Role": "operator"
      },
      body: JSON.stringify({question})
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.detail?.message || body.detail?.code || `Chat failed (${response.status})`);
    }
    appendChat("assistant", body.answer);
    $("chat-meta").textContent = `${body.model} · ${body.confidence} confidence · ${body.citations.length} citations · audit ${body.audit.id}`;
    $("chat-state").textContent = "read only";
    $("chat-state").className = "pill good";
  } catch (error) {
    appendChat("assistant error", error.message);
    $("chat-state").textContent = "unavailable";
    $("chat-state").className = "pill warn";
  } finally {
    $("chat-send").disabled = false;
    input.focus();
  }
}

function setMode(status) {
  $("version").textContent = status.version;
  $("mode-pill").textContent = `${status.mode} mode`;
  $("mode-pill").className = `pill ${status.mode === "live" ? "good" : "warn"}`;
  $("system-state").textContent = status.mode === "live" ? "Live API" : "Safe preview";
}

function renderReadiness(payload) {
  $("replay-summary").textContent = `${payload.replay.passed}/${payload.replay.total} cases · ${payload.replay.accuracy_percent}%`;
  $("security-summary").textContent = `${payload.security.passed}/${payload.security.total} checks · ${payload.security.refusal_percent}% refusal`;
  $("readiness-summary").textContent = `${payload.uat.passed}/${payload.uat.total} gates · ${payload.uat.decision.replaceAll("_", " ")}`;
  $("readiness-summary").className = payload.uat.decision === "ready_for_controlled_uat" ? "" : "error";
}

function renderDashboard(payload) {
  const op = payload.operations.data;
  const market = payload.market.data;
  const values = [op.orders, op.deposits, op.withdrawals, op.pending_withdrawals];
  document.querySelectorAll("#metrics strong").forEach((node, i) => node.textContent = number(values[i], 0));
  $("market-name").textContent = `${market.base_asset} / ${market.quote_asset}`;
  $("market-active").textContent = market.is_active ? "Active" : "Inactive";
  $("market-active").className = `pill ${market.is_active ? "good" : "warn"}`;
  $("last-price").textContent = number(market.last);
  $("quote").textContent = market.quote_asset;
  ["open", "high", "low", "volume"].forEach(key => $(key).textContent = number(market[key]));
  const signal = payload.signals[0];
  $("pending-large").textContent = number(signal.value, 0);
  $("signal-text").textContent = signal.explanation;
  $("severity").textContent = signal.severity;
  $("severity").className = `pill ${signal.severity === "healthy" ? "good" : "warn"}`;
  const incident = payload.incident;
  $("incident-title").textContent = incident.title;
  $("incident-state").textContent = `${incident.severity} · ${incident.state}`;
  $("incident-state").className = `pill ${incident.severity === "healthy" ? "good" : "warn"}`;
  $("incident-observed").textContent = number(incident.observed.pending_count, 0);
  $("incident-warning").textContent = number(incident.thresholds.warning_pending_count, 0);
  $("incident-critical").textContent = number(incident.thresholds.critical_pending_count, 0);
  $("incident-rule").textContent = `${incident.rule.id} @ ${incident.rule.version}`;
  $("incident-confidence").textContent = incident.confidence;
  const evidence = incident.evidence[0];
  $("incident-evidence").textContent = `${new Date(evidence.generated_at).toLocaleString()} · freshness ${evidence.data_freshness_seconds ?? "unknown"}s`;
  $("incident-timeline").innerHTML = incident.timeline.map(item =>
    `<li><time>${new Date(item.at).toLocaleTimeString()}</time><span>${item.event}</span></li>`
  ).join("");
  $("incident-guidance").textContent = incident.recommended_investigation;
  const risk = payload.market_risk;
  $("risk-market").textContent = `${risk.market} evidence window`;
  $("risk-severity").textContent = risk.severity;
  $("risk-severity").className = `pill ${risk.severity === "healthy" ? "good" : "warn"}`;
  $("range-percent").textContent = risk.metrics.range_percent === null ? "Unavailable" : `${risk.metrics.range_percent}%`;
  $("range-position").textContent = risk.metrics.last_position_percent === null ? "Unavailable" : `${risk.metrics.last_position_percent}%`;
  $("risk-confidence").textContent = risk.confidence;
  $("range-thresholds").textContent = `warning ${risk.thresholds.warning_range_percent}% · critical ${risk.thresholds.critical_range_percent}%`;
  $("updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

function renderFeatures(payload) {
  $("coverage-counts").innerHTML = Object.entries(payload.counts)
    .map(([key, value]) => `<span>${value} ${key}</span>`).join("");
  $("features").innerHTML = payload.items.map(item => `
    <div class="feature">
      <span class="dot ${item.status}"></span>
      <div><strong>${item.name}</strong><small>${item.description}</small></div>
      <code>${item.source}</code>
    </div>`).join("");
}

function renderAudit(payload) {
  const node = $("audit-summary");
  if (!node) return;
  node.textContent = payload.valid
    ? `${payload.records} records · chain valid`
    : `Integrity failure at record ${payload.failed_at_id}`;
  node.className = payload.valid ? "" : "error";
}

function renderTrends(payload) {
  $("trend-status").textContent = `${payload.status} · ${payload.records} records`;
  $("trend-status").className = `pill ${payload.status === "ready" ? "good" : "warn"}`;
  if (payload.records < 1) return;
  $("trend-pending").textContent = number(payload.deltas.pending_withdrawals, 0);
  $("trend-orders").textContent = number(payload.deltas.orders, 0);
  $("trend-price").textContent = payload.market.last_price_change_percent === null
    ? "Unavailable" : `${payload.market.last_price_change_percent}%`;
  $("trend-window").textContent = `records ${payload.window.from_record_id} → ${payload.window.to_record_id}`;
  const freshness = payload.freshness.operations_seconds;
  $("freshness-summary").textContent = payload.alerts.length
    ? `${freshness ?? "unknown"}s · warning`
    : `${freshness ?? "unknown"}s · within threshold`;
  $("freshness-summary").className = payload.alerts.length ? "error" : "";
}

function renderInvestigation(payload) {
  if (payload.status !== "ready") {
    $("brief-conclusion").textContent = payload.conclusion;
    $("brief-severity").textContent = payload.status;
    return;
  }
  $("brief-severity").textContent = payload.severity;
  $("brief-severity").className = `pill ${payload.severity === "healthy" ? "good" : "warn"}`;
  $("brief-conclusion").textContent = payload.conclusion;
  const evidence = payload.supporting_evidence;
  $("brief-evidence").innerHTML = [
    `${evidence.pending_withdrawals} pending withdrawals`,
    `Source: ${evidence.source}`,
    `Generated: ${new Date(evidence.source_timestamp).toLocaleString()}`,
    `Rule: ${evidence.rule.id} @ ${evidence.rule.version}`,
    `Confidence: ${payload.confidence}`
  ].map(item => `<li>${item}</li>`).join("");
  $("brief-runbook").textContent = payload.runbook.section;
  $("brief-guidance").textContent = payload.recommended_investigation;
}

function renderExecutiveBrief(payload) {
  if (payload.status !== "ready") return;
  currentBriefId = payload.brief_id;
  $("executive-headline").textContent = payload.headline;
  $("executive-severity").textContent = payload.overall_severity;
  $("executive-severity").className = `pill ${payload.overall_severity === "healthy" ? "good" : "warn"}`;
  $("executive-priorities").innerHTML = payload.priorities
    .map(item => `<li><strong>${item.title}</strong><span>${item.reason}</span></li>`)
    .join("");
}

async function submitFeedback(rating) {
  if (!currentBriefId) return;
  const response = await fetch("/api/v0/feedback", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({report_id: currentBriefId, rating, comment: ""})
  });
  if (!response.ok) throw new Error(`Feedback failed (${response.status})`);
  $("feedback-status").textContent = "Feedback recorded locally. No exchange write performed.";
}

async function load() {
  const refreshButtons = [$("refresh"), $("refresh-live")];
  refreshButtons.forEach(button => button.disabled = true);
  $("refresh-live").textContent = "Refreshing…";
  $("updated").textContent = "Refreshing live data…";
  $("updated").className = "";
  $("system-state").className = "";
  try {
    const market = $("market").value.trim().toUpperCase();
    const days = $("days").value;
    const [status, dashboard, features, audit, trends, investigation, brief, readiness] = await Promise.all([
      json("/api/v0/status"),
      json(`/api/v0/dashboard?market=${encodeURIComponent(market)}&days=${days}`),
      json("/api/v0/features"),
      json("/api/v0/audit/verify"),
      json("/api/v0/trends?limit=30"),
      json("/api/v0/investigations/withdrawal-slowdown"),
      json("/api/v0/briefs/daily"),
      json("/api/v0/readiness")
    ]);
    setMode(status);
    renderDashboard(dashboard);
    renderFeatures(features);
    renderAudit(audit);
    renderTrends(trends);
    renderInvestigation(investigation);
    renderExecutiveBrief(brief);
    renderReadiness(readiness);
    refreshCount += 1;
    $("updated").textContent = `Live refresh #${refreshCount} completed at ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $("system-state").textContent = "Data unavailable";
    $("system-state").className = "error";
    $("updated").textContent = error.message;
    $("updated").className = "error";
  } finally {
    refreshButtons.forEach(button => button.disabled = false);
    $("refresh-live").textContent = "Refresh live data";
  }
}

$("refresh").addEventListener("click", load);
$("refresh-live").addEventListener("click", load);
$("feedback-useful").addEventListener("click", () => submitFeedback("useful").catch(error => $("feedback-status").textContent = error.message));
$("feedback-correction").addEventListener("click", () => submitFeedback("needs_correction").catch(error => $("feedback-status").textContent = error.message));
$("chat-form").addEventListener("submit", askChat);
load();
