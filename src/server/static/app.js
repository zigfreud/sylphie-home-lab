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
  "STACK_ALREADY_STOPPED_AT_CAPTURE_START",
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
  "RED_STUCK_STATE",
  "COLOR_PICKER_CHANGED_RED",
  "COLOR_PICKER_CHANGED_GREEN",
  "COLOR_PICKER_CHANGED_BLUE",
  "COLOR_VISUALLY_CHANGED",
  "POPUP_OK_CLICKED",
  "OTHER",
];

const statusText = document.getElementById("statusText");
const colorInput = document.getElementById("colorInput");
const lastRgb = document.getElementById("lastRgb");
const coldStartMode = document.getElementById("coldStartMode");
const captureMode = document.getElementById("captureMode");
const stackAlreadyStopped = document.getElementById("stackAlreadyStopped");
const highRateCapture = document.getElementById("highRateCapture");
const captureModeHint = document.getElementById("captureModeHint");
const conflictAlert = document.getElementById("conflictAlert");
const ownerBanner = document.getElementById("ownerBanner");
const ownerText = document.getElementById("ownerText");
const ownerReasons = document.getElementById("ownerReasons");
const returnDisableAutostart = document.getElementById("returnDisableAutostart");
const returnLaunchArmoury = document.getElementById("returnLaunchArmoury");
const takeoverIncludeArmouryCore = document.getElementById("takeoverIncludeArmouryCore");
const results = {
  lights: document.getElementById("lightsResult"),
  agent: document.getElementById("agentResult"),
  takeover: document.getElementById("takeoverResult"),
  diagnostics: document.getElementById("diagnosticsResult"),
  recovery: document.getElementById("recoveryResult"),
  capture: document.getElementById("captureTail"),
  logs: document.getElementById("logsResult"),
};
const agentSummary = document.getElementById("agentSummary");
const serviceTable = document.getElementById("serviceTable");
const audioServiceTable = document.getElementById("audioServiceTable");
const audioProcessTable = document.getElementById("audioProcessTable");
const captureSummary = document.getElementById("captureSummary");

let busy = false;
let lastRequestedRgb = "FF0000";
let currentOwnerMode = "unknown";
let currentWriteAllowed = false;

function activePanelName() {
  return document.querySelector(".tab-panel.active")?.id || "lights";
}

function setBusy(value, text = "Running...") {
  busy = value;
  statusText.textContent = value ? text : "Idle";
  document.querySelectorAll("button[data-action]").forEach((button) => {
    button.disabled = value;
  });
  colorInput.disabled = value || !currentWriteAllowed;
  if (!value) applyOwnerGuards();
}

function applyOwnerGuards() {
  document.querySelectorAll("[data-owner-required='sylphie']").forEach((item) => {
    item.disabled = busy || !currentWriteAllowed;
    item.title = currentWriteAllowed ? "" : "RGB writes are enabled only after Takeover for Sylphie completes without blocking conflicts.";
  });
  colorInput.disabled = busy || !currentWriteAllowed;
}

function pretty(payload) {
  return JSON.stringify(trimPayload(payload), null, 2);
}

function trimPayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  const copy = Array.isArray(payload) ? payload.map(trimPayload) : {...payload};
  for (const key of ["stdout", "stderr", "text", "raw", "command_line", "executable_path"]) {
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
  updateAudioReactiveHealth(payload);
  updateOwnershipBanner(payload);
  updateAgentTaskSummary(payload);
  updateCaptureSummary(payload);
}

function updateConflictAlert(payload) {
  const state = payload?.response?.state || payload?.state || payload?.agent_status?.response?.state;
  const lastResult = payload?.response?.state?.last_result || payload?.response || payload;
  const manual = lastResult?.manual_action_required || payload?.manual_action_required || [];
  const blockers = state?.blocking_conflicts || payload?.blocking_conflicts || payload?.response?.state?.last_result?.blocking_conflicts;
  const warnings = state?.warnings || payload?.warnings || payload?.response?.state?.last_result?.warnings;
  if (manual && manual.length) {
    conflictAlert.hidden = false;
    conflictAlert.textContent = `Takeover cannot complete automatically because some blocking conflicts require manual action: ${manual.join(", ")}`;
    return;
  }
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

function updateAgentTaskSummary(payload) {
  if (!("task_exists" in (payload || {}))) return;
  const items = [
    ["Task exists", String(payload.task_exists)],
    ["Task enabled", String(payload.task_enabled)],
    ["Task state", payload.task_state || "unknown"],
    ["Agent process running", String(payload.agent_process_running ?? payload.running)],
    ["Pipe responding", String(payload.pipe_responding ?? payload.agent_ping)],
    ["PID", (payload.pids || []).join(", ") || "none"],
    ["Elevated", String(payload.elevated)],
    ["Agent owner status", payload.agent_state?.current_owner_status || "unknown"],
  ];
  agentSummary.innerHTML = items.map(([label, value]) => `<div><strong>${label}</strong><span>${escapeHtml(String(value))}</span></div>`).join("");
}

function updateOwnershipBanner(payload) {
  if (!payload || !("mode" in payload)) return;
  currentOwnerMode = payload.mode || "unknown";
  currentWriteAllowed = Boolean(payload.write_allowed);
  const label = {
    armoury: "Armoury",
    sylphie: "Sylphie",
    "sylphie-warning": "Sylphie Warning",
    ready: "Ready",
    "ready-warning": "Ready Warning",
    research: "Research",
    conflict: "Conflict",
    unknown: "Unknown",
  }[currentOwnerMode] || currentOwnerMode;
  ownerText.textContent = label;
  const parts = [];
  if (payload.blocking_conflicts?.length) parts.push(`Blocking conflicts: ${payload.blocking_conflicts.join(", ")}`);
  if (payload.warnings?.length) parts.push(`Warnings: ${payload.warnings.join(", ")}`);
  if (payload.informational_processes?.length) parts.push(`Informational processes: ${payload.informational_processes.join(", ")}`);
  if (payload.reasons?.length) parts.push(payload.reasons.join(" | "));
  parts.push(`RGB writes: ${payload.write_allowed ? "enabled" : "blocked"}`);
  ownerReasons.textContent = parts.join(" | ") || "No ownership details loaded.";
  ownerBanner.className = `owner-banner owner-${currentOwnerMode}`;
  applyOwnerGuards();
}

function updateServices(payload) {
  if (payload?.process_patterns) return;
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

function updateAudioReactiveHealth(payload) {
  const services = payload?.services;
  const processes = payload?.processes;
  if (!Array.isArray(services) && !Array.isArray(processes)) return;

  if (Array.isArray(services) && audioServiceTable) {
    audioServiceTable.innerHTML = `
      <table>
        <thead><tr><th>Name</th><th>State</th><th>Startup</th><th>PID</th><th>Account</th></tr></thead>
        <tbody>
          ${services.map((svc) => `
            <tr>
              <td>${escapeHtml(svc.name || "")}${svc.optional ? " <span class=\"muted\">optional</span>" : ""}</td>
              <td>${escapeHtml(svc.state || "unknown")}</td>
              <td>${escapeHtml(svc.start_mode || "")}</td>
              <td>${escapeHtml(String(svc.process_id || ""))}</td>
              <td>${escapeHtml(svc.account || "")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }

  if (Array.isArray(processes) && audioProcessTable) {
    if (processes.length === 0) {
      audioProcessTable.innerHTML = `<div class="empty-state">No related processes found.</div>`;
      return;
    }
    audioProcessTable.innerHTML = `
      <table>
        <thead><tr><th>Name</th><th>PID</th><th>Matched</th><th>Command Line</th></tr></thead>
        <tbody>
          ${processes.map((process) => `
            <tr>
              <td>${escapeHtml(process.name || "")}</td>
              <td>${escapeHtml(String(process.pid || ""))}</td>
              <td>${escapeHtml((process.matched_rules || []).join(", "))}</td>
              <td>${escapeHtml(process.command_line || process.executable_path || "")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }
}

function updateCaptureSummary(payload) {
  if (!("running" in (payload || {})) && !payload?.log && !payload?.marker_log) return;
  const alreadyStopped = payload.stack_already_stopped ? " | stack already stopped mode" : "";
  captureSummary.textContent = `Capture running: ${payload.running} | type: ${payload.type || "none"} | log: ${payload.log || "none"}${alreadyStopped}`;
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
    button.dataset.ownerRequired = "sylphie";
    button.textContent = scene;
    button.addEventListener("click", () => setScene(scene));
    root.appendChild(button);
  });
}

function selectTab(name) {
  const button = document.querySelector(`.tab-button[data-tab="${name}"]`);
  const panel = document.getElementById(name);
  if (!button || !panel) return;
  document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  panel.classList.add("active");
}

async function refreshOwnership() {
  const payload = await request("/api/ownership/status");
  updateOwnershipBanner(payload);
  return payload;
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

function captureStartPayload(type) {
  const alreadyStopped = Boolean(stackAlreadyStopped?.checked || captureMode?.value === "stack-already-stopped");
  return {
    type,
    capture_block_payload: true,
    stack_already_stopped: alreadyStopped,
    high_rate: Boolean(highRateCapture?.checked),
    priority_high: Boolean(highRateCapture?.checked),
  };
}

function redStuckGreenCapturePayload() {
  return {
    type: "armoury-ui",
    capture_block_payload: true,
    stack_already_stopped: Boolean(stackAlreadyStopped?.checked || captureMode?.value === "stack-already-stopped"),
    high_rate: true,
    priority_high: true,
    scenario: "RED_STUCK_TO_GREEN_CAPTURE",
  };
}

function updateCaptureModeHint() {
  const mode = captureMode?.value || "full-automated";
  if (mode === "stack-already-stopped") {
    if (stackAlreadyStopped) stackAlreadyStopped.checked = true;
    captureModeHint.textContent = "Use this only if LightingService and Armoury/Aura processes are already stopped. Capture start records STACK_ALREADY_STOPPED_AT_CAPTURE_START and a service/process snapshot.";
    return;
  }
  if (mode === "manual-research") {
    captureModeHint.textContent = "Manual research mode starts the probe and leaves stack control to you. Add markers while performing Armoury actions.";
    return;
  }
  if (stackAlreadyStopped) stackAlreadyStopped.checked = false;
  captureModeHint.textContent = "Full automated stop/start launches the elevated cold-start workflow. It stops LightingService first, then whitelisted leftovers.";
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
  ownershipStatus: () => run(activePanelName(), "Checking owner...", () => request("/api/ownership/status")),
  returnToArmoury: () => {
    const accepted = window.confirm("Return to Armoury Mode now? Sylphie agent will be stopped and no SMBus writes will be sent.");
    if (!accepted) return;
    return run("agent", "Returning to Armoury...", () => post("/api/ownership/return-to-armoury", {
      disable_autostart: Boolean(returnDisableAutostart?.checked),
      launch_armoury: Boolean(returnLaunchArmoury?.checked),
    })).then(() => setTimeout(refreshOwnership, 3000));
  },
  takeoverForSylphie: () => {
    const includeArmouryCore = Boolean(takeoverIncludeArmouryCore?.checked);
    const message = includeArmouryCore
      ? "Take over for Sylphie Mode and close Armoury UI/helpers? LightingService will be stopped first."
      : "Take over for Sylphie Mode now? LightingService will be stopped first. Armoury UI/helper warnings are not closed by default.";
    const accepted = window.confirm(message);
    if (!accepted) return;
    return run("takeover", "Taking over for Sylphie...", () => post("/api/ownership/takeover-for-sylphie", {include_armoury_core: includeArmouryCore})).then(() => setTimeout(refreshOwnership, 5000));
  },
  goCapture: () => selectTab("capture"),
  emergencyStopSylphie: () => {
    const accepted = window.confirm("Emergency stop Sylphie agent now?");
    if (!accepted) return;
    return run("agent", "Stopping Sylphie...", () => post("/api/agent/task/stop", {})).then(() => setTimeout(refreshOwnership, 2000));
  },
  setColor: () => {
    const rgb = colorInput.value.replace("#", "").toUpperCase();
    lastRequestedRgb = rgb;
    lastRgb.textContent = `Last RGB: ${rgb}`;
    return run("lights", "Applying color...", () => post("/api/set", {rgb}));
  },
  off: () => setScene("off"),
  agentPing: () => run("agent", "Pinging agent...", () => post("/api/agent/ping")),
  agentStatus: () => run("agent", "Loading agent status...", () => request("/api/agent/status")),
  agentTaskStatus: () => run("agent", "Loading task status...", () => request("/api/agent/task/status")),
  installAgentTask: () => {
    const accepted = window.confirm("Install SylphieAgent Scheduled Task disabled by default?");
    if (!accepted) return;
    return run("agent", "Installing task...", () => post("/api/agent/task/install", {enable_autostart: false})).then(() => setTimeout(() => actions.agentTaskStatus(), 2500));
  },
  enableAgentAutostart: () => {
    const accepted = window.confirm("Enable Sylphie agent autostart at logon?");
    if (!accepted) return;
    return run("agent", "Enabling autostart...", () => post("/api/agent/task/enable-autostart", {})).then(() => setTimeout(() => actions.agentTaskStatus(), 2500));
  },
  disableAgentAutostart: () => run("agent", "Disabling autostart...", () => post("/api/agent/task/disable-autostart", {})).then(() => setTimeout(() => actions.agentTaskStatus(), 2500)),
  uninstallAgentTask: () => {
    const accepted = window.confirm("Uninstall SylphieAgent Scheduled Task? If it is running from the task, the agent will be stopped.");
    if (!accepted) return;
    return run("agent", "Uninstalling task...", () => post("/api/agent/task/uninstall", {stop_agent: true})).then(() => setTimeout(() => actions.agentTaskStatus(), 2500));
  },
  startAgentNow: () => {
    const accepted = window.confirm("Start Sylphie agent manually now without enabling autostart?");
    if (!accepted) return;
    return run("agent", "Starting agent now...", () => post("/api/agent/task/start-now", {})).then(() => setTimeout(refreshOwnership, 2500));
  },
  stopAgentTask: () => run("agent", "Stopping agent...", () => post("/api/agent/task/stop", {})).then(() => setTimeout(refreshOwnership, 2000)),
  serviceStatus: () => run("takeover", "Loading services...", () => request("/api/services/status")),
  takeoverCheck: () => run("takeover", "Checking takeover...", () => post("/api/agent/takeover-check")),
  takeoverDryRun: () => run("takeover", "Planning takeover...", () => post("/api/agent/takeover-dry-run", {})),
  takeoverExecute: () => {
    if (!window.confirm("Stop ASUS lighting services and take ownership? LightingService will be stopped first.")) return;
    return run("takeover", "Executing takeover...", () => post("/api/agent/takeover-execute", {i_accept_stopping_lighting_services: true})).then(() => setTimeout(refreshOwnership, 2000));
  },
  restoreServices: () => run("takeover", "Restoring services...", () => post("/api/agent/restore-services")),
  armouryHealth: () => run("diagnostics", "Checking Armoury health...", () => request("/api/diagnostics/armoury-health")),
  audioReactiveHealth: () => run("diagnostics", "Checking audio/reactive health...", () => request("/api/diagnostics/audio-reactive-health")),
  restartLightingService: () => {
    if (!window.confirm("Restart LightingService now? This can temporarily hand RGB control back to Armoury/Aura.")) return;
    return run("diagnostics", "Requesting LightingService restart...", () => post("/api/diagnostics/armoury/restart-lighting", {}));
  },
  restartArmouryStack: () => {
    if (!window.confirm("Restart Armoury stack now? LightingService will be restarted and Armoury launched if a known path exists.")) return;
    return run("diagnostics", "Requesting Armoury stack restart...", () => post("/api/diagnostics/armoury/restart-stack", {}));
  },
  restartWindowsAudioServices: () => {
    if (!window.confirm("Restart Windows Audio services now? Audio playback/capture may briefly drop.")) return;
    return run("diagnostics", "Requesting audio service restart...", () => post("/api/diagnostics/audio-reactive/restart-windows-audio", {}));
  },
  restoreLogitechLampArray: () => {
    if (!window.confirm("Restore logi_lamparray_service now? This sets it to Automatic and starts it if present.")) return;
    return run("diagnostics", "Requesting Logitech LampArray restore...", () => post("/api/diagnostics/armoury/restore-logitech-lamparray", {}));
  },
  busStatus: () => run("recovery", "Reading bus status...", () => post("/api/agent/bus-status")),
  recover: () => run("recovery", "Recovering...", () => post("/api/agent/recover")),
  recoverWhite: () => run("recovery", "Recovering white...", () => post("/api/agent/recover-set", {rgb: "FFFFFF"})),
  recoverRed: () => run("recovery", "Recovering red...", () => post("/api/agent/recover-set", {rgb: "FF0000"})),
  recoverLast: () => run("recovery", "Recovering last color...", () => post("/api/agent/recover-set", {rgb: lastRequestedRgb || "FFFFFF"})),
  experimentalArmouryFe: () => run("recovery", "Experimental command unavailable...", async () => ({ok: false, error: "Not wired yet. Use CLI experimental command manually for now."})),
  experimentalClearMode: () => run("recovery", "Experimental command unavailable...", async () => ({ok: false, error: "Not wired yet. Use CLI experimental command manually for now."})),
  startBroadCapture: () => run("capture", "Starting broad capture...", () => post("/api/capture/start", captureStartPayload("broad"))),
  startArmouryCapture: () => run("capture", "Starting Armoury UI capture...", () => post("/api/capture/start", captureStartPayload("armoury-ui"))),
  startRedStuckGreenCapture: () => run("capture", "Starting RED_STUCK_TO_GREEN capture...", () => post("/api/capture/start", redStuckGreenCapturePayload())),
  startColdStartCapture: () => {
    const accepted = window.confirm("This launches an elevated cold-start capture and may stop the Sylphie server/dashboard. Continue?");
    if (!accepted) return;
    const mode = coldStartMode ? coldStartMode.value : "gui-cold-launch";
    return run("capture", "Launching cold-start capture...", () => post("/api/capture/cold-start", {mode}));
  },
  startArmouryStack: () => {
    const accepted = window.confirm("Start LightingService or launch Armoury now? Add FIRST_LIGHT marker manually when LEDs return.");
    if (!accepted) return;
    const mode = coldStartMode ? coldStartMode.value : "gui-cold-launch";
    return run("capture", "Starting Armoury stack...", () => post("/api/capture/start-stack", {mode}));
  },
  stopCapture: () => run("capture", "Stopping capture...", () => post("/api/capture/stop")),
  captureStatus: () => run("capture", "Loading capture status...", () => request("/api/capture/status")),
  analyzeCapture: () => run("capture", "Analyzing capture...", () => post("/api/capture/analyze", {})),
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

if (captureMode) {
  captureMode.addEventListener("change", updateCaptureModeHint);
  updateCaptureModeHint();
}

wireTabs();
buildSceneButtons();
buildMarkerButtons();
wireActions();
applyOwnerGuards();
refreshOwnership();
actions.agentTaskStatus();
