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

async function load() {
  $("refresh").disabled = true;
  try {
    const market = $("market").value.trim().toUpperCase();
    const days = $("days").value;
    const [status, dashboard, features] = await Promise.all([
      json("/api/v0/status"),
      json(`/api/v0/dashboard?market=${encodeURIComponent(market)}&days=${days}`),
      json("/api/v0/features")
    ]);
    setMode(status);
    renderDashboard(dashboard);
    renderFeatures(features);
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
