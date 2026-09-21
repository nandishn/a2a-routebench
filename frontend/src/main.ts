import "./styles.css";

const API = "http://127.0.0.1:8000/api";

type ProjectSummary = { name: string };
type Agent = {
  id: string;
  name: string;
  url: string;
  auth_env_name?: string | null;
  status?: string;
  error?: string | null;
  last_fetched_at?: string;
  agent_card?: AgentCard | null;
};
type AgentCard = {
  name?: string;
  description?: string;
  version?: string;
  skills?: Array<{ id?: string; name?: string; description?: string; tags?: string[] }>;
};
type EvalItem = { id: string; name: string; prompt: string; expected_agent: string };
type RunResult = {
  eval_id: string;
  name: string;
  prompt: string;
  expected_agent: string;
  selected_agent?: string | null;
  correct: boolean;
  confidence: number;
  reason: string;
};
type Run = {
  id: string;
  created_at: string;
  summary: { total: number; correct: number; accuracy: number };
  results: RunResult[];
};
type Project = { name: string; agents: Agent[]; evals: EvalItem[]; runs: Run[] };
type Settings = { provider?: string; key_env_name?: string | null; masked_api_key?: string | null };

let projects: ProjectSummary[] = [];
let current: Project | null = null;
let settings: Settings = {};
let selectedAgentId: string | null = null;
let activeTab: "agents" | "evals" | "runs" = "agents";
let selectedRunId: string | null = null;
let notice = "";

const app = document.querySelector<HTMLDivElement>("#app")!;

void boot();

async function boot() {
  await Promise.all([loadProjects(), loadSettings()]);
  render();
}

async function loadProjects() {
  projects = (await api<{ projects: ProjectSummary[] }>("/projects")).projects;
  if (!current && projects[0]) await selectProject(projects[0].name);
}

async function selectProject(name: string) {
  current = await api<Project>(`/projects/${encodeURIComponent(name)}`);
  selectedAgentId = current.agents[0]?.id ?? null;
  selectedRunId = current.runs[0]?.id ?? null;
}

async function loadSettings() {
  settings = (await api<{ settings: Settings }>("/settings/llm")).settings || {};
}

function render() {
  app.innerHTML = `
    <div class="app-shell">
      <aside class="rail">
        <div class="brand">
          <div class="mark">A2A</div>
          <div>
            <strong>RouteBench</strong>
            <span>Agent routing QA</span>
          </div>
        </div>

        <section class="rail-section">
          <div class="section-label">Projects</div>
          <form id="create-project" class="create-project">
            <input name="name" placeholder="new_project" pattern="[A-Za-z0-9_]+" required />
            <button title="Create project">+</button>
          </form>
          <nav class="project-nav">
            ${projects.map(projectButton).join("") || `<p class="empty-copy">No projects yet</p>`}
          </nav>
        </section>

        <section class="rail-section">
          <div class="section-label">LLM Settings</div>
          ${settingsPanel()}
        </section>
      </aside>

      <main class="main">
        ${topbar()}
        ${notice ? `<div class="notice">${esc(notice)}</div>` : ""}
        ${current ? projectWorkspace(current) : emptyState()}
      </main>
    </div>
  `;
  bindEvents();
}

function projectButton(project: ProjectSummary) {
  return `
    <button class="project-link ${current?.name === project.name ? "active" : ""}" data-project="${esc(project.name)}">
      <span>${esc(project.name)}</span>
      <small>${current?.name === project.name ? "open" : "project"}</small>
    </button>
  `;
}

function settingsPanel() {
  return `
    <form id="settings-form" class="settings-form">
      <label>
        Provider
        <select name="provider">
          ${["gemini", "openai", "anthropic", "grok"].map((provider) => `
            <option value="${provider}" ${settings.provider === provider ? "selected" : ""}>${provider}</option>
          `).join("")}
        </select>
      </label>
      <label>
        Backend env variable
        <input name="key_env_name" placeholder="env variable if configured in backend" value="${esc(settings.key_env_name || "")}" />
      </label>
      <label>
        Actual key
        <input name="api_key" type="password" placeholder="${settings.masked_api_key || "not stored raw"}" />
      </label>
      <button>Save settings</button>
    </form>
    <p class="help-text">Use an env var or enter a key. Raw keys are not written to disk.</p>
  `;
}

function topbar() {
  const projectName = current?.name || "No project selected";
  return `
    <header class="topbar">
      <div>
        <div class="eyebrow">Workspace</div>
        <h1>${esc(projectName)}</h1>
      </div>
      <div class="topbar-actions">
        ${current ? `
          <form id="rename-project" class="rename-form">
            <input name="name" value="${esc(current.name)}" pattern="[A-Za-z0-9_]+" required />
            <button>Rename</button>
          </form>
        ` : ""}
        <button class="secondary" id="refresh">Refresh</button>
      </div>
    </header>
  `;
}

function projectWorkspace(project: Project) {
  const okAgents = project.agents.filter((agent) => agent.status === "ok").length;
  const erroredAgents = project.agents.filter((agent) => agent.status === "error").length;
  const latestRun = project.runs[0];
  return `
    <section class="summary-grid">
      ${metric("Agents", project.agents.length)}
      ${metric("Healthy cards", okAgents)}
      ${metric("Fetch errors", erroredAgents)}
      ${metric("Evals", project.evals.length)}
      ${metric("Latest accuracy", latestRun ? `${latestRun.summary.accuracy}%` : "No runs")}
    </section>

    <section class="workspace-card">
      <div class="workspace-card-header">
        <div>
          <h2>Project Registry</h2>
          <p>Data path: <code>data/${esc(project.name)}/agents.json</code> and <code>evals.json</code></p>
        </div>
        <div class="header-actions">
          <button class="secondary" id="evaluate-agents">Evaluate Agent Cards</button>
          <button id="run-evals">Run Evals</button>
        </div>
      </div>

      <div class="tabs">
        <button class="${activeTab === "agents" ? "active" : ""}" data-tab="agents">Agent Cards</button>
        <button class="${activeTab === "evals" ? "active" : ""}" data-tab="evals">Evals</button>
        <button class="${activeTab === "runs" ? "active" : ""}" data-tab="runs">Runs</button>
      </div>

      ${activeTab === "agents" ? agentsView(project) : activeTab === "evals" ? evalsView(project) : runsView(project)}
    </section>
  `;
}

function metric(label: string, value: string | number) {
  return `
    <article class="metric">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
    </article>
  `;
}

function agentsView(project: Project) {
  const selected = project.agents.find((agent) => agent.id === selectedAgentId) || project.agents[0];
  return `
    <div class="split">
      <div>
        <form id="agent-form" class="toolbar-form">
          <input name="name" placeholder="Agent display name" required />
          <input name="url" placeholder="https://host/.well-known/agent-card.json" required />
          <input name="auth_env_name" placeholder="Auth env var, optional" />
          <button>Add agent</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Skills</th>
                <th>Auth</th>
                <th>Last fetched</th>
              </tr>
            </thead>
            <tbody>
              ${project.agents.map(agentRow).join("") || tableEmpty("No agents have been added.")}
            </tbody>
          </table>
        </div>
      </div>
      <aside class="detail-pane">
        ${selected ? agentDetail(selected) : `<div class="empty-panel">Select an agent to inspect its card.</div>`}
      </aside>
    </div>
  `;
}

function agentRow(agent: Agent) {
  const card = agent.agent_card;
  return `
    <tr class="${selectedAgentId === agent.id ? "selected" : ""}" data-select-agent="${esc(agent.id)}">
      <td>
        <strong>${esc(agent.name)}</strong>
        <small>${esc(card?.name || "No fetched card name")}</small>
      </td>
      <td>${statusBadge(agent.status || "unknown")}</td>
      <td>${esc(card?.skills?.length ?? 0)}</td>
      <td>${agent.auth_env_name ? `<code>${esc(agent.auth_env_name)}</code>` : `<span class="muted">None</span>`}</td>
      <td>${esc(formatDate(agent.last_fetched_at))}</td>
    </tr>
  `;
}

function agentDetail(agent: Agent) {
  const card = agent.agent_card;
  return `
    <div class="detail-head">
      <div>
        <div class="eyebrow">Agent</div>
        <h3>${esc(agent.name)}</h3>
      </div>
      ${statusBadge(agent.status || "unknown")}
    </div>

    <form class="agent-edit detail-form" data-agent-id="${esc(agent.id)}">
      <label>Name<input name="name" value="${esc(agent.name)}" required /></label>
      <label>URL<input name="url" value="${esc(agent.url)}" required /></label>
      <label>Auth env<input name="auth_env_name" value="${esc(agent.auth_env_name || "")}" placeholder="Optional" /></label>
      <div class="button-row">
        <button>Save agent</button>
        <button type="button" class="danger" data-delete-agent="${esc(agent.id)}">Delete</button>
      </div>
    </form>

    ${agent.error ? `<div class="error-box">${esc(agent.error)}</div>` : ""}

    <section class="card-summary">
      <h4>${esc(card?.name || "No Agent Card fetched")}</h4>
      <p>${esc(card?.description || "Evaluate this agent to fetch its Agent Card.")}</p>
      <dl>
        <div><dt>Version</dt><dd>${esc(card?.version || "Unknown")}</dd></div>
        <div><dt>Skills</dt><dd>${esc(card?.skills?.length ?? 0)}</dd></div>
      </dl>
    </section>

    <details class="json-viewer">
      <summary>Agent Card JSON</summary>
      <pre>${esc(JSON.stringify(card || {}, null, 2))}</pre>
    </details>
  `;
}

function evalsView(project: Project) {
  return `
    <form id="eval-form" class="toolbar-form eval-form">
      <input name="name" placeholder="Eval name" required />
      <input name="prompt" placeholder="Prompt" required />
      <select name="expected_agent" required>
        <option value="">Expected agent</option>
        ${project.agents.map((agent) => `<option value="${esc(agent.name)}">${esc(agent.name)}</option>`).join("")}
      </select>
      <button>Add eval</button>
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Prompt</th>
            <th>Expected agent</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${project.evals.map(evalRow).join("") || tableEmpty("No evals have been added.")}
        </tbody>
      </table>
    </div>
  `;
}

function evalRow(item: EvalItem) {
  return `
    <tr>
      <td><strong>${esc(item.name)}</strong></td>
      <td>${esc(item.prompt)}</td>
      <td>${esc(item.expected_agent)}</td>
      <td class="right"><button class="danger compact" data-delete-eval="${esc(item.id)}">Delete</button></td>
    </tr>
  `;
}

function runsView(project: Project) {
  const selected = project.runs.find((run) => run.id === selectedRunId) || project.runs[0];
  return `
    <div class="split runs-split">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Created</th>
              <th>Accuracy</th>
              <th>Correct</th>
            </tr>
          </thead>
          <tbody>
            ${project.runs.map(runRow).join("") || tableEmpty("No runs yet. Click Run Evals to create one.")}
          </tbody>
        </table>
      </div>
      <aside class="detail-pane">
        ${selected ? runDetail(selected) : `<div class="empty-panel">Run evals to see results.</div>`}
      </aside>
    </div>
  `;
}

function runRow(run: Run) {
  return `
    <tr class="${selectedRunId === run.id ? "selected" : ""}" data-select-run="${esc(run.id)}">
      <td><strong>${esc(run.id.slice(0, 8))}</strong></td>
      <td>${esc(formatDate(run.created_at))}</td>
      <td>${esc(run.summary.accuracy)}%</td>
      <td>${esc(run.summary.correct)}/${esc(run.summary.total)}</td>
    </tr>
  `;
}

function runDetail(run: Run) {
  return `
    <div class="detail-head">
      <div>
        <div class="eyebrow">Run</div>
        <h3>${esc(run.summary.accuracy)}% accuracy</h3>
        <p>${esc(formatDate(run.created_at))}</p>
      </div>
      ${statusBadge(run.summary.correct === run.summary.total ? "ok" : "error")}
    </div>
    <div class="result-list">
      ${run.results.map(resultCard).join("")}
    </div>
  `;
}

function resultCard(result: RunResult) {
  return `
    <article class="result-card ${result.correct ? "pass" : "fail"}">
      <div class="result-head">
        <strong>${esc(result.name)}</strong>
        ${result.correct ? `<span class="status ok">pass</span>` : `<span class="status bad">fail</span>`}
      </div>
      <p>${esc(result.prompt)}</p>
      <dl>
        <div><dt>Expected</dt><dd>${esc(result.expected_agent)}</dd></div>
        <div><dt>Selected</dt><dd>${esc(result.selected_agent || "No match")}</dd></div>
      </dl>
      <p class="muted">${esc(result.reason)}</p>
    </article>
  `;
}

function statusBadge(status: string) {
  const cls = status === "ok" ? "ok" : status === "error" ? "bad" : "neutral";
  return `<span class="status ${cls}">${esc(status)}</span>`;
}

function tableEmpty(message: string) {
  return `<tr><td colspan="5" class="table-empty">${esc(message)}</td></tr>`;
}

function emptyState() {
  return `
    <section class="empty-state">
      <h2>Create a project to begin</h2>
      <p>Projects create isolated files under <code>data/&lt;project&gt;/</code> for agents and evals.</p>
    </section>
  `;
}

function bindEvents() {
  document.querySelector("#refresh")?.addEventListener("click", () => boot());
  document.querySelectorAll<HTMLButtonElement>("[data-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      await selectProject(button.dataset.project!);
      notice = "";
      render();
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab as "agents" | "evals" | "runs";
      render();
    });
  });
  document.querySelectorAll<HTMLElement>("[data-select-agent]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedAgentId = row.dataset.selectAgent!;
      render();
    });
  });
  document.querySelectorAll<HTMLElement>("[data-select-run]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedRunId = row.dataset.selectRun!;
      render();
    });
  });
  document.querySelector<HTMLFormElement>("#create-project")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withNotice("Project created", async () => {
      current = await api<Project>("/projects", { method: "POST", body: JSON.stringify(formData(event.currentTarget as HTMLFormElement)) });
      await loadProjects();
    });
  });
  document.querySelector<HTMLFormElement>("#rename-project")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withNotice("Project renamed", async () => {
      current = await api<Project>(`/projects/${current!.name}`, { method: "PATCH", body: JSON.stringify(formData(event.currentTarget as HTMLFormElement)) });
      await loadProjects();
    });
  });
  document.querySelector<HTMLFormElement>("#agent-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withNotice("Agent added", async () => {
      await api(`/projects/${current!.name}/agents`, { method: "POST", body: JSON.stringify(formData(event.currentTarget as HTMLFormElement)) });
      await selectProject(current!.name);
    });
  });
  document.querySelector("#evaluate-agents")?.addEventListener("click", async () => {
    await withNotice("Agent Cards evaluated", async () => {
      await api(`/projects/${current!.name}/agents/evaluate`, { method: "POST" });
      await selectProject(current!.name);
    });
  });
  document.querySelector("#run-evals")?.addEventListener("click", async () => {
    await withNotice("Eval run completed", async () => {
      const body = await api<{ run: Run; runs: Run[] }>(`/projects/${current!.name}/runs`, { method: "POST" });
      current = { ...current!, runs: body.runs };
      selectedRunId = body.run.id;
      activeTab = "runs";
    });
  });
  document.querySelector<HTMLFormElement>(".agent-edit")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    await withNotice("Agent updated", async () => {
      await api(`/projects/${current!.name}/agents/${form.dataset.agentId}`, { method: "PATCH", body: JSON.stringify(formData(form)) });
      await selectProject(current!.name);
    });
  });
  document.querySelector<HTMLButtonElement>("[data-delete-agent]")?.addEventListener("click", async (event) => {
    event.preventDefault();
    const id = (event.currentTarget as HTMLButtonElement).dataset.deleteAgent!;
    await withNotice("Agent deleted", async () => {
      await api(`/projects/${current!.name}/agents/${id}`, { method: "DELETE" });
      await selectProject(current!.name);
    });
  });
  document.querySelector<HTMLFormElement>("#eval-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withNotice("Eval added", async () => {
      await api(`/projects/${current!.name}/evals`, { method: "POST", body: JSON.stringify(formData(event.currentTarget as HTMLFormElement)) });
      await selectProject(current!.name);
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-delete-eval]").forEach((button) => {
    button.addEventListener("click", async () => {
      await withNotice("Eval deleted", async () => {
        await api(`/projects/${current!.name}/evals/${button.dataset.deleteEval}`, { method: "DELETE" });
        await selectProject(current!.name);
      });
    });
  });
  document.querySelector<HTMLFormElement>("#settings-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withNotice("Settings saved", async () => {
      settings = (await api<{ settings: Settings }>("/settings/llm", { method: "PUT", body: JSON.stringify(formData(event.currentTarget as HTMLFormElement)) })).settings;
    });
  });
}

async function withNotice(message: string, action: () => Promise<void>) {
  try {
    await action();
    notice = message;
  } catch (error) {
    notice = error instanceof Error ? error.message : "Request failed";
  }
  render();
}

function formData(form: HTMLFormElement): Record<string, string> {
  return Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    headers: { "content-type": "application/json", ...(init.headers || {}) },
    ...init,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "Request failed");
  return body;
}

function formatDate(value?: string) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function esc(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
