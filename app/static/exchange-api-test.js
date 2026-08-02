const byId = id => document.getElementById(id);
let catalog = [];

function inputs() {
  return {market: byId("api-market").value.trim().toUpperCase(), case_id: byId("api-case-id").value.trim() || "test-case"};
}

async function runTest(test, button) {
  const output = document.querySelector(`[data-result="${CSS.escape(test.id)}"]`);
  button.disabled = true;
  output.className = "api-result running";
  output.textContent = "Running signed GET request…";
  try {
    const response = await fetch("/api/v0/exchange-tests/run", {method: "POST", headers: {"Content-Type": "application/json", "X-BitAgent-Role": "operator"}, body: JSON.stringify({test_id: test.id, ...inputs()})});
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `bitAgent HTTP ${response.status}`);
    output.className = `api-result ${payload.ok ? "passed" : "failed"}`;
    output.textContent = JSON.stringify(payload, null, 2);
    return payload.ok;
  } catch (error) {
    output.className = "api-result failed";
    output.textContent = error.message;
    return false;
  } finally { button.disabled = false; }
}

function render() {
  byId("api-tests").innerHTML = catalog.map(test => `<article class="api-test-row"><div class="api-test-heading"><span class="pill neutral">${test.group}</span><code>${test.method} ${test.path}</code><button type="button" data-run="${test.id}">Run</button></div><pre class="api-result" data-result="${test.id}">Not run</pre></article>`).join("");
  document.querySelectorAll("[data-run]").forEach(button => button.addEventListener("click", () => runTest(catalog.find(test => test.id === button.dataset.run), button)));
}

async function loadCatalog() {
  const response = await fetch("/api/v0/exchange-tests", {headers: {"X-BitAgent-Role": "operator"}});
  const payload = await response.json();
  if (!response.ok) throw new Error(`Catalog HTTP ${response.status}`);
  catalog = payload.tests;
  byId("api-mode").textContent = `${payload.mode} mode`;
  byId("api-mode").className = `pill ${payload.mode === "live" ? "good" : "warn"}`;
  byId("api-base-url").textContent = `Exchange: ${payload.exchange_base_url} · credentials exposed: ${payload.credentials_exposed}`;
  byId("api-summary").textContent = `${catalog.length} read-only API checks available`;
  render();
}

byId("api-run-all").addEventListener("click", async event => {
  event.currentTarget.disabled = true;
  let passed = 0;
  for (let index = 0; index < catalog.length; index += 1) {
    const test = catalog[index];
    const button = document.querySelector(`[data-run="${CSS.escape(test.id)}"]`);
    if (await runTest(test, button)) passed += 1;
    byId("api-summary").textContent = `${passed} passed · ${index + 1 - passed} failed · ${catalog.length} total`;
  }
  event.currentTarget.disabled = false;
});

loadCatalog().catch(error => { byId("api-summary").textContent = error.message; byId("api-summary").className = "error"; });
