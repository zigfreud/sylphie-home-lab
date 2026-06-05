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

const logOutput = document.getElementById("logOutput");
const sceneButtons = document.getElementById("sceneButtons");
const colorInput = document.getElementById("colorInput");
const setColorButton = document.getElementById("setColorButton");
const healthButton = document.getElementById("healthButton");
const statusText = document.getElementById("statusText");

let applying = false;
let activeAction = null;
let statePollTimer = null;
const sceneButtonElements = new Map();

function log(payload) {
  logOutput.textContent = JSON.stringify(summarizePayload(payload), null, 2);
}

function summarizePayload(payload) {
  if (!payload || typeof payload !== "object") {
    return payload;
  }

  const copy = Array.isArray(payload) ? [...payload] : {...payload};
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
  statusText.textContent = value ? label : "Idle";
  setColorButton.disabled = value;
  healthButton.disabled = value;
  for (const button of sceneButtonElements.values()) {
    button.disabled = value;
  }
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  log(payload);
  return payload;
}

function startStatePolling() {
  if (statePollTimer !== null) {
    return;
  }

  statePollTimer = window.setInterval(async () => {
    try {
      const state = await requestJson("/api/state");
      if (!state.running && !state.pending) {
        stopStatePolling();
        activeAction = null;
        setApplying(false);
      } else {
        statusText.textContent = state.pending ? "Queued..." : "Applying...";
      }
    } catch (error) {
      log({ok: false, error: String(error)});
    }
  }, 500);
}

function stopStatePolling() {
  if (statePollTimer !== null) {
    window.clearInterval(statePollTimer);
    statePollTimer = null;
  }
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
    if (payload.running || payload.queued) {
      startStatePolling();
    } else {
      activeAction = null;
      setApplying(false);
    }
  } catch (error) {
    log({ok: false, error: String(error)});
    activeAction = null;
    setApplying(false);
  }
}

async function setColor() {
  const rgb = colorInput.value;
  await runAction(`set:${rgb}`, () => {
    return requestJson("/api/set", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({rgb}),
    });
  });
}

async function setScene(name) {
  await runAction(`scene:${name}`, () => {
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
    setApplying(false);
  }
});
setColorButton.addEventListener("click", setColor);
buildSceneButtons();
