const scenes = [
  "focus",
  "movie",
  "night",
  "reading",
  "cyberpunk",
  "deepblue",
  "red",
  "green",
  "blue",
  "white",
  "off",
];

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

const logOutput = document.getElementById("logOutput");
const sceneButtons = document.getElementById("sceneButtons");
const colorInput = document.getElementById("colorInput");
const setColorButton = document.getElementById("setColorButton");
const healthButton = document.getElementById("healthButton");
const statusText = document.getElementById("statusText");
const recoverButton = document.getElementById("recoverButton");
const recoverLastButton = document.getElementById("recoverLastButton");
const takeoverCheckButton = document.getElementById("takeoverCheckButton");
const takeoverDryRunButton = document.getElementById("takeoverDryRunButton");
const takeoverExecuteButton = document.getElementById("takeoverExecuteButton");
const restoreServicesButton = document.getElementById("restoreServicesButton");
const conflictAlert = document.getElementById("conflictAlert");

let applying = false;
let activeAction = null;
let lastRequestedRgb = "FF0000";
const sceneButtonElements = new Map();

function log(payload) {
  logOutput.textContent = JSON.stringify(summarizePayload(payload), null, 2);
}

function summarizePayload(payload) {
  if (!payload || typeof payload !== "object") {
    return payload;
  }

  const copy = Array.isArray(payload) ? [...payload] : {
    ok: payload.ok,
    applied: payload.applied,
    command: payload.command,
    exit_code: payload.exit_code,
    duration_ms: payload.duration_ms,
    conflicting_processes: payload.conflicting_processes,
    stdout: payload.stdout,
    stderr: payload.stderr,
    error: payload.error,
  };
  for (const key of ["stdout", "stderr", "raw"]) {
    if (typeof copy[key] === "string" && copy[key].length > 1200) {
      copy[key] = `${copy[key].slice(0, 1200)}\n... truncated ...`;
    }
  }
  if (copy.doctor) {
    copy.doctor = summarizePayload(copy.doctor);
  }
  if (copy.last_result) {
    copy.last_result = summarizePayload(copy.last_result);
  }
  return copy;
}

function setApplying(value, label = "Applying...") {
  applying = value;
  if (value) {
    statusText.textContent = label;
  }
  setColorButton.disabled = value;
  healthButton.disabled = value;
  recoverButton.disabled = value;
  recoverLastButton.disabled = value;
  takeoverCheckButton.disabled = value;
  takeoverDryRunButton.disabled = value;
  takeoverExecuteButton.disabled = value;
  restoreServicesButton.disabled = value;
  for (const button of sceneButtonElements.values()) {
    button.disabled = value;
  }
}

function updateConflictAlert(payload) {
  const conflicts = payload && payload.conflicting_processes;
  if (Array.isArray(conflicts) && conflicts.length > 0) {
    conflictAlert.hidden = false;
    conflictAlert.textContent = `Controller conflict detected: ${conflicts.join(", ")}. Close Armoury/Aura/OpenRGB before writing.`;
    return;
  }

  if (payload && payload.error === "controller conflict detected") {
    conflictAlert.hidden = false;
    conflictAlert.textContent = payload.suggestion || "Controller conflict detected. Run takeover first or close Armoury/Aura/OpenRGB before writing.";
    return;
  }

  conflictAlert.hidden = true;
  conflictAlert.textContent = "";
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  updateConflictAlert(payload);
  log(payload);
  return payload;
}

async function runAction(actionKey, callback) {
  if (applying && activeAction === actionKey) {
    return;
  }
  if (applying) {
    return;
  }

  activeAction = actionKey;
  setApplying(true);
  try {
    const payload = await callback();
    if (payload.ok && payload.applied) {
      statusText.textContent = "Applied";
    } else {
      statusText.textContent = payload.error ? "Error" : "Not applied";
    }
  } catch (error) {
    log({ok: false, error: String(error)});
    statusText.textContent = "Error";
  } finally {
    activeAction = null;
    setApplying(false);
  }
}

async function setColor() {
  const rgb = colorInput.value.replace("#", "").toUpperCase();
  await runAction(`set:${rgb}`, () => {
    lastRequestedRgb = rgb;
    return requestJson("/api/set", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({rgb}),
    });
  });
}

async function setScene(name) {
  await runAction(`scene:${name}`, () => {
    if (sceneRgb[name]) {
      lastRequestedRgb = sceneRgb[name];
    }

    if (name === "off") {
      return requestJson("/api/off", {method: "POST"});
    }

    return requestJson("/api/scene", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name}),
    });
  });
}

async function recoverController() {
  await runAction("recover", () => {
    return requestJson("/api/recover", {method: "POST"});
  });
}

async function recoverLastColor() {
  const rgb = lastRequestedRgb || colorInput.value.replace("#", "").toUpperCase();
  await runAction(`recover-set:${rgb}`, () => {
    return requestJson("/api/recover-set", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({rgb}),
    });
  });
}

async function takeoverCheck() {
  await runAction("takeover-check", () => {
    return requestJson("/api/takeover-check", {method: "POST"});
  });
}

async function takeoverDryRun() {
  await runAction("takeover-dry-run", () => {
    return requestJson("/api/takeover", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({execute: false}),
    });
  });
}

async function takeoverExecute() {
  const accepted = window.confirm("Sylphie will stop whitelisted lighting services/processes and run recovery. Continue?");
  if (!accepted) {
    return;
  }
  await runAction("takeover-execute", () => {
    return requestJson("/api/takeover", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({execute: true, accept: true}),
    });
  });
}

async function restoreServices() {
  await runAction("restore-services", () => {
    return requestJson("/api/restore-services", {method: "POST"});
  });
}

function buildSceneButtons() {
  for (const scene of scenes) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = scene;
    button.addEventListener("click", () => setScene(scene));
    sceneButtons.appendChild(button);
    sceneButtonElements.set(scene, button);
  }
}

healthButton.addEventListener("click", async () => {
  setApplying(true, "Checking...");
  try {
    await requestJson("/api/health");
  } finally {
    statusText.textContent = "Idle";
    setApplying(false);
  }
});
setColorButton.addEventListener("click", setColor);
recoverButton.addEventListener("click", recoverController);
recoverLastButton.addEventListener("click", recoverLastColor);
takeoverCheckButton.addEventListener("click", takeoverCheck);
takeoverDryRunButton.addEventListener("click", takeoverDryRun);
takeoverExecuteButton.addEventListener("click", takeoverExecute);
restoreServicesButton.addEventListener("click", restoreServices);
buildSceneButtons();
