const doorView = new URLSearchParams(location.search).get("view") === "door";
if (doorView) {
  document.body.classList.add("door-view");
  document.title = "Lab entrance | Door display";
}

const buttons = [...document.querySelectorAll("[data-field]")];
const readings = [...document.querySelectorAll("[data-reading]")];
const connection = document.querySelector(".connection");
const doorCard = document.querySelector(".door-card");
const alertLabel = document.querySelector("#alert-label");
const alertTitle = document.querySelector("#alert-title");
const entryNote = document.querySelector("#entry-note");

const unknown = { laser: "unknown", lock: "unknown", experiment: "unknown" };
const doorMessages = {
  on: ["36 W Class 4 laser on", "DANGER", "Do not enter without approved laser eyewear. Authorized personnel only."],
  off: ["Lab status", "Class 4 laser off", "Follow the posted lab entry procedures."],
  unknown: ["Class 4 laser", "Status unknown", "Contact the lab operator before entering."],
  offline: ["Display offline", "Status unavailable", "Contact the lab operator before entering."],
};

let status = unknown;
let connectionState = "connecting";
let requests = Promise.resolve();
let pendingRequests = 0;

function setText(element, value) {
  if (element.textContent !== value) {
    element.textContent = value;
  }
}

function render() {
  const connectionLabel = { connecting: "Connecting", online: "Connected", offline: "Offline" };
  connection.dataset.connection = connectionState;
  setText(connection, connectionLabel[connectionState]);

  for (const button of buttons) {
    const selected = status[button.dataset.field] === button.dataset.value;
    button.setAttribute("aria-pressed", String(selected));
    button.disabled = connectionState !== "online";
  }
  for (const reading of readings) {
    const value = status[reading.dataset.reading];
    reading.dataset.value = value;
    setText(reading, value[0].toUpperCase() + value.slice(1));
  }

  const alert = connectionState === "offline" ? "offline" : status.laser;
  const [label, title, note] = doorMessages[alert];
  doorCard.dataset.alert = alert;
  setText(alertLabel, label);
  setText(alertTitle, title);
  setText(entryNote, note);
}

async function requestStatus(change) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1800);
  try {
    const options = { cache: "no-store", signal: controller.signal };
    if (change) {
      options.method = "POST";
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(change);
    }
    const response = await fetch("/api/status", options);
    if (!response.ok) {
      throw new Error(`Status request failed (${response.status})`);
    }
    status = await response.json();
    connectionState = "online";
  } catch {
    status = unknown;
    connectionState = "offline";
  } finally {
    clearTimeout(timeout);
    render();
  }
}

// Keep polls and taps in order so an older response cannot overwrite a newer one.
function enqueue(change) {
  pendingRequests++;
  requests = requests.then(() => requestStatus(change)).finally(() => pendingRequests--);
}

function refresh() {
  if (pendingRequests === 0) {
    enqueue();
  }
}

if (!doorView) {
  for (const button of buttons) {
    button.addEventListener("click", () => {
      enqueue({ [button.dataset.field]: button.dataset.value });
    });
  }
}

refresh();
setInterval(refresh, 750);
