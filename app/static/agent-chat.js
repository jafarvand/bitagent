const el = id => document.getElementById(id);
const uiLanguage = () => window.bitAgentI18n?.language || "en";
let activeAgent = null;
let sessionId = crypto.randomUUID();

function addMessage(kind, text) {
  const node = document.createElement("div");
  node.className = `chat-message ${kind}`;
  node.textContent = text;
  el("agent-messages").appendChild(node);
  node.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function selectedAgentId(agents) {
  const parts = location.pathname.split("/").filter(Boolean);
  const requested = parts[0] === "agents" ? parts[1] : null;
  return agents.some(agent => agent.id === requested) ? requested : agents[0].id;
}

function renderAgent(agent, agents) {
  activeAgent = agent;
  document.title = `bitAgent · ${agent.name}`;
  el("agent-name").textContent = agent.name;
  el("agent-eyebrow").textContent = `${agent.id.toUpperCase()} WORKSPACE`;
  el("agent-description").textContent = agent.description;
  el("agent-question").placeholder = agent.samples[0];
  el("agent-nav").innerHTML = agents.map(item => `<a href="${item.path}" class="${item.id === agent.id ? "active" : ""}"><strong>${item.name}</strong><small>${item.description}</small></a>`).join("");
  el("agent-sample-list").innerHTML = agent.samples.map((sample, index) => `<button type="button" data-sample="${index}">${sample}</button>`).join("");
  document.querySelectorAll("[data-sample]").forEach(button => button.addEventListener("click", () => { el("agent-question").value = agent.samples[Number(button.dataset.sample)]; el("agent-question").focus(); }));
}

async function loadAgents() {
  const response = await fetch(`/api/v0/agents?language=${uiLanguage()}`, {headers: {"X-BitAgent-Role": "operator"}});
  const payload = await response.json();
  if (!response.ok) throw new Error(`Agent catalog failed (${response.status})`);
  const agentId = selectedAgentId(payload.agents);
  renderAgent(payload.agents.find(agent => agent.id === agentId), payload.agents);
}

el("agent-form").addEventListener("submit", async event => {
  event.preventDefault();
  const input = el("agent-question");
  const question = input.value.trim();
  if (!question || !activeAgent) return;
  addMessage("user", question);
  input.value = "";
  el("agent-send").disabled = true;
  el("agent-state").textContent = "thinking";
  try {
    const response = await fetch("/api/v0/chat", {method: "POST", headers: {"Content-Type": "application/json", "X-BitAgent-Role": "operator"}, body: JSON.stringify({question, session_id: sessionId, agent: activeAgent.id, language: uiLanguage()})});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail?.message || payload.detail?.code || `Chat failed (${response.status})`);
    addMessage("assistant", payload.answer);
    el("agent-meta").textContent = `${payload.agent} · ${payload.model} · ${payload.confidence} confidence · ${payload.citations.length} citations · audit ${payload.audit.id}`;
    el("agent-state").textContent = "read only";
    el("agent-state").className = "pill good";
  } catch (error) {
    addMessage("assistant error", error.message);
    el("agent-state").textContent = "unavailable";
    el("agent-state").className = "pill warn";
  } finally { el("agent-send").disabled = false; input.focus(); }
});

loadAgents().catch(error => { el("agent-name").textContent = "Agent catalog unavailable"; el("agent-description").textContent = error.message; });
