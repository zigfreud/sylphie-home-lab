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

function log(payload) {
  logOutput.textContent = JSON.stringify(payload, null, 2);
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  log(payload);
  return payload;
}

async function setColor() {
  await requestJson("/api/set", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({rgb: colorInput.value}),
  });
}

async function setScene(name) {
  if (name === "off") {
    await requestJson("/api/off", {method: "POST"});
    return;
  }

  await requestJson("/api/scene", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name}),
  });
}

function buildSceneButtons() {
  for (const scene of scenes) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = scene;
    button.addEventListener("click", () => setScene(scene));
    sceneButtons.appendChild(button);
  }
}

healthButton.addEventListener("click", () => requestJson("/api/health"));
setColorButton.addEventListener("click", setColor);
buildSceneButtons();
