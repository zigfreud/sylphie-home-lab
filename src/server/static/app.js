const scenes = ["focus", "movie", "night", "reading", "cyberpunk", "deepblue", "red", "green", "blue", "white", "off"];
const sceneRgb = {
  focus: "FFFFFF",
  movie: "202060",
  night: "300000",
  reading: "FFC080",
  cyberpunk: "FF0080",
  deepblue: "0000FF",
  red: "FF0000",
  green: "00FF00",
  blue: "0000FF",
  white: "FFFFFF",
  off: "000000",
};
const markers = [
  "SERVICE_STOPPED",
  "SERVICE_STARTED",
  "STACK_STOPPED",
  "ARMOURY_LAUNCHED",
  "UAC_ACCEPTED_BY_USER",
  "FIRST_LIGHT",
  "MOUSE_COLOR_SELECTED",
  "OK_CLICKED",
  "APPLY_CLICKED",
  "WHITE",
  "RED",
  "GREEN",
  "BLUE",
  "OTHER",
];

const statusText = document.getElementById("statusText");
const colorInput = document.getElementById("colorInput");
const lastRgb = document.getElementById("lastRgb");
const coldStartMode = document.getElementById("coldStartMode");
const conflictAlert = document.getElementById("conflictAlert");
const results = {
  lights: document.getElementById("lightsResult"),
  agent: document.getElementById("agentResult"),
  takeover: document.getElementById("takeoverResult"),
  recovery: document.getElementById("recoveryResult"),
  capture: document.getElementById("captureTail"),
  logs: document.getElementById("logsResult"),
};
const agentSummary = document.getElementById("agentSummary");
const serviceTable = document.getElementById("serviceTable");
const captureSummary = document.getElementById("captureSummary");

let busy = false;
let lastRequestedRgb = "FF0000";

function activePanelName() {
  return document.querySelector(".tab-panel.active")?.id || "lights";
}

function setBusy(value, text = "Running...") {
  busy = value;
  statusText.textContent = value ? text : "Idle";
  document.querySelectorAll("button[data-action]").forEach((button) => {
    button.disabled = value;
  });
}

function pretty(payload) {
  return JSON.stringify(trimPayload(payload), null, 2);
}

function trimPayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  const copy = Array.isArray(payload) ? payload.map(trimPayload) : {...payload};
  for (const key of ["stdout", "stderr", "text", "raw"]) {
    if (typeof copy[key] === "string" && copy[key].length > 2500) {
      copy[key] = `${copy[key].slice(0, 2500)}\n... truncated ...`;
    }
  }
  if (copy.response) copy.response = trimPayload(copy.response);
  if (copy.last_result) copy.last_result = trimPayload(copy.last_result);
  if (copy.state) copy.state = trimPayload(copy.state);
  return copy;
}

function show(panel, payload) {
  if (results[panel]) results[panel].textContent = pretty(payload);
  updateConflictAlert(payload);
  updateAgentSummary(payload);
  updateServices(payload);
  updateCaptureSummary(payload);
}

function updateConflictAlert(payload) {
  const state = payload?.response?.state || payload?.state || payload?.agent_status?.response?.state;
  const blockers = state?.blocking_conflicts || payload?.blocking_conflicts || payload?.response?.state?.last_result?.blocking_conflicts;
  const warnings = state?.warnings || payload?.warnings || payload?.response?.state?.last_result?.warnings;
  if ((blockers && blockers.length) || payload?.error === "controller conflict detected") {
    conflictAlert.hidden = false;
    conflictAlert.textContent = `Blocking conflicts: ${(blockers || []).join(", ") || payload.error}. Run takeover first.`;
    return;
  }
  if (warnings && warnings.length) {
    conflictAlert.hidden = false;
    conflictAlert.textContent = `Warnings only: ${warnings.join(", ")}`;
    return;
  }
  conflictAlert.hidden = true;
  conflictAlert.textContent = "";
}

function updateAgentSummary(payload) {
  const state = payload?.response?.state || payload?.agent_status?.response?.state;
  if (!state) return;
  const uptime = state.start_time ? Math.max(0, Math.floor(Date.now() / 1000 - state.start_time)) : null;
  const items = [
    ["Agent status", state.current_owner_status || "unknown"],
    ["is_elevated", String(state.is_elevated)],
    ["PID", state.pid || "unknown"],
    ["uptime", uptime === null ? "unknown" : `${uptime}s`],
    ["pipe", "\\\\.\\pipe\\sylphie-hw"],
    ["blocking_conflicts", (state.blocking_conflicts || []).join(", ") || "none"],
    ["warnings", (state.warnings || []).join(", ") || "none"],
  ];
  agentSummary.innerHTML = items.map(([label, value]) => `<div><strong>${label}</strong><span>${escapeHtml(String(value))}</span></div>`).join("");
}

function updateServices(payload) {
  const services = payload?.response?.state?.last_result?.services || payload?.response?.services || payload?.services;
  if (!Array.isArray(services)) return;
  serviceTable.innerHTML = `
    <table>
      <thead><tr><th>Name</th><th>State</th><th>Tier</th><th>PID</th><th>Action</th></tr></thead>
      <tbody>
        ${services.map((svc) => `
          <tr>
            <td>${escapeHtml(svc.name || "")}</td>
            <td>${escapeHtml(svc.state || "unknown")}</td>
            <td>${escapeHtml(svc.tier || "")}</td>
            <td>${escapeHtml(String(svc.pid || (svc.process_pids || []).join(", ") || ""))}</td>
            <td>${svc.allowed_to_stop ? "stop allowed" : "warning only"}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function updateCaptureSummary(payload) {
  if (!("running" in (payload || {})) && !payload?.log && !payload?.marker_log) return;
  captureSummary.textContent = `Capture running: ${payload.running} | type: ${payload.type || "none"} | log: ${payload.log || "none"}`;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok && !payload.error) payload.error = `HTTP ${response.status}`;
  return payload;
}

async function post(path, body = undefined) {
  const options = {method: "POST"};
  if (body !== undefined) {
    options.headers = {"Content-Type": "application/json"};
    options.body = JSON.stringify(body);
  }
  return request(path, options);
}

async function run(panel, label, fn) {
  if (busy) return;
  setBusy(true, label);
  try {
    const payload = await fn();
    show(panel, payload);
    statusText.textContent = payload.ok ? "Done" : "Error";
    return payload;
  } catch (error) {
    const payload = {ok: false, error: String(error)};
    show(panel, payload);
    statusText.textContent = "Error";
    return payload;
  } finally {
    setBusy(false);
  }
}

function wireTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.tab).classList.add("active");
    });
  });
}

function buildSceneButtons() {
  const root = document.getElementById("sceneButtons");
  root.innerHTML = "";
  scenes.forEach((scene) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = `scene:${scene}`;
    button.textContent = scene;
    button.addEventListener("click", () => setScene(scene));
    root.appendChild(button);
  });
}

function buildMarkerButtons() {
  const root = document.getElementById("markerButtons");
  root.innerHTML = "";
  markers.forEach((marker) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = `marker:${marker}`;
    button.textContent = marker;
    button.addEventListener("click", () => run("capture", "Marking...", () => post("/api/capture/marker", {marker})));
    root.appendChild(button);
  });
}

async function setScene(name) {
  if (sceneRgb[name]) {
    lastRequestedRgb = sceneRgb[name];
    lastRgb.textContent = `Last RGB: ${lastRequestedRgb}`;
  }
  if (name === "off") {
    return run("lights", "Applying off...", () => post("/api/off"));
  }
  return run("lights", `Applying ${name}...`, () => post("/api/scene", {name}));
}

const actions = {
  health: () => run(activePanelName(), "Checking...", () => request("/api/health")),
  setColor: () => {
    const rgb = colorInput.value.replace("#", "").toUpperCase();
    lastRequestedRgb = rgb;
    lastRgb.textContent = `Last RGB: ${rgb}`;
    return run("lights", "Applying color...", () => post("/api/set", {rgb}));
  },
  off: () => setScene("off"),
  agentPing: () => run("agent", "Pinging agent...", () => post("/api/agent/ping")),
  agentStatus: () => run("agent", "Loading agent status...", () => request("/api/agent/status")),
  startAgent: () => run("agent", "Starting agent...", () => post("/api/lifecycle/start-agent")),
  stopAgent: () => run("agent", "Stopping agent...", () => post("/api/lifecycle/stop-agent")),
  restartAgent: () => run("agent", "Restarting agent...", () => post("/api/lifecycle/restart-agent")),
  serviceStatus: () => run("takeover", "Loading services...", () => request("/api/services/status")),
  takeoverCheck: () => run("takeover", "Checking takeover...", () => post("/api/agent/takeover-check")),
  takeoverDryRun: () => run("takeover", "Planning takeover...", () => post("/api/agent/takeover-dry-run", {})),
  takeoverExecute: () => {
    if (!window.confirm("Stop ASUS lighting services and take ownership? LightingService will be stopped first.")) return;
    return run("takeover", "Executing takeover...", () => post("/api/agent/takeover-execute", {i_accept_stopping_lighting_services: true}));
  },
  restoreServices: () => run("takeover", "Restoring services...", () => post("/api/agent/restore-services")),
  busStatus: () => run("recovery", "Reading bus status...", () => post("/api/agent/bus-status")),
  recover: () => run("recovery", "Recovering...", () => post("/api/agent/recover")),
  recoverWhite: () => run("recovery", "Recovering white...", () => post("/api/agent/recover-set", {rgb: "FFFFFF"})),
  recoverRed: () => run("recovery", "Recovering red...", () => post("/api/agent/recover-set", {rgb: "FF0000"})),
  recoverLast: () => run("recovery", "Recovering last color...", () => post("/api/agent/recover-set", {rgb: lastRequestedRgb || "FFFFFF"})),
  experimentalArmouryFe: () => run("recovery", "Experimental command unavailable...", async () => ({ok: false, error: "Not wired yet. Use CLI experimental command manually for now."})),
  experimentalClearMode: () => run("recovery", "Experimental command unavailable...", async () => ({ok: false, error: "Not wired yet. Use CLI experimental command manually for now."})),
  startBroadCapture: () => run("capture", "Starting broad capture...", () => post("/api/capture/start", {type: "broad", capture_block_payload: true})),
  startArmouryCapture: () => run("capture", "Starting Armoury UI capture...", () => post("/api/capture/start", {type: "armoury-ui", capture_block_payload: true})),
  startColdStartCapture: () => {
    const accepted = window.confirm("This launches an elevated cold-start capture and may stop the Sylphie server/dashboard. Continue?");
    if (!accepted) return;
    const mode = coldStartMode ? coldStartMode.value : "gui-cold-launch";
    return run("capture", "Launching cold-start capture...", () => post("/api/capture/cold-start", {mode}));
  },
  stopCapture: () => run("capture", "Stopping capture...", () => post("/api/capture/stop")),
  captureStatus: () => run("capture", "Loading capture status...", () => request("/api/capture/status")),
  tailServerLog: () => run("logs", "Loading server log...", () => request("/api/logs/tail?name=server&lines=200")),
  tailAgentLog: () => run("logs", "Loading agent log...", () => request("/api/logs/tail?name=agent&lines=200")),
  tailCommandsLog: () => run("logs", "Loading command log...", () => request("/api/logs/tail?name=commands&lines=200")),
  tailCaptureLog: () => run("logs", "Loading capture tail...", () => request("/api/capture/tail?lines=200")),
};

function wireActions() {
  document.querySelectorAll("button[data-action]").forEach((button) => {
    const action = button.dataset.action;
    if (action.startsWith("scene:") || action.startsWith("marker:")) return;
    button.addEventListener("click", () => {
      if (actions[action]) actions[action]();
    });
  });
}

colorInput.addEventListener("input", () => {
  lastRequestedRgb = colorInput.value.replace("#", "").toUpperCase();
  lastRgb.textContent = `Last RGB: ${lastRequestedRgb} (preview)`;
});

wireTabs();
buildSceneButtons();
buildMarkerButtons();
wireActions();
actions.agentStatus();
