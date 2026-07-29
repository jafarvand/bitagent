const $ = (id) => document.getElementById(id);
const number = (value, maximumFractionDigits = 2) =>
  Number(value || 0).toLocaleString(undefined, {maximumFractionDigits});

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function setMode(status) {
  $("version").textContent = status.version;
  $("mode-pill").textContent = `${status.mode} mode`;
  $("mode-pill").className = `pill ${status.mode === "live" ? "good" : "warn"}`;
  $("system-state").textContent = status.mode === "live" ? "Live API" : "Safe preview";
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
  $("audit-summary").textContent = payload.valid
    ? `${payload.records} records · chain valid`
    : `Integrity failure at record ${payload.failed_at_id}`;
  $("audit-summary").className = payload.valid ? "" : "error";
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

async function load() {
  $("refresh").disabled = true;
  try {
    const market = $("market").value.trim().toUpperCase();
    const days = $("days").value;
    const [status, dashboard, features, audit, trends] = await Promise.all([
      json("/api/v0/status"),
      json(`/api/v0/dashboard?market=${encodeURIComponent(market)}&days=${days}`),
      json("/api/v0/features"),
      json("/api/v0/audit/verify"),
      json("/api/v0/trends?limit=30")
    ]);
    setMode(status);
    renderDashboard(dashboard);
    renderFeatures(features);
    renderAudit(audit);
    renderTrends(trends);
  } catch (error) {
    $("system-state").textContent = "Connection error";
    $("system-state").className = "error";
    $("updated").textContent = error.message;
    $("updated").className = "error";
  } finally {
    $("refresh").disabled = false;
  }
}

$("refresh").addEventListener("click", load);
load();
