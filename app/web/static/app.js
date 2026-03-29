// Dashboard auto-refresh and interactivity

document.addEventListener("DOMContentLoaded", () => {
  loadHAMQTTSettings();
  loadMapping();
  setupForms();
  // Auto-refresh station status every 30 seconds
  setInterval(refreshStations, 30000);
});

function setupForms() {
  const addForm = document.getElementById("add-station-form");
  if (addForm) {
    addForm.addEventListener("submit", (e) => {
      e.preventDefault();
      addStation();
    });
  }

  const discoverBtn = document.getElementById("discover-btn");
  if (discoverBtn) {
    discoverBtn.addEventListener("click", discoverStation);
  }

  const haMqttForm = document.getElementById("ha-mqtt-form");
  if (haMqttForm) {
    haMqttForm.addEventListener("submit", (e) => {
      e.preventDefault();
      saveHAMQTT();
    });
  }

  const passwordForm = document.getElementById("password-form");
  if (passwordForm) {
    passwordForm.addEventListener("submit", (e) => {
      e.preventDefault();
      changePassword();
    });
  }
}

async function addStation() {
  const id = document.getElementById("station-id").value.trim().toLowerCase();
  const name = document.getElementById("station-name").value.trim();
  if (!id) return;

  const resp = await fetch("/api/stations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, display_name: name }),
  });

  if (resp.ok) {
    location.reload();
  } else {
    const data = await resp.json();
    alert(data.error || "Failed to add station");
  }
}

async function removeStation(id) {
  if (!confirm(`Remove station "${id}"? This will also remove HA entities.`)) return;

  await fetch(`/api/stations/${id}`, { method: "DELETE" });
  location.reload();
}

async function discoverStation() {
  const id = document.getElementById("station-id").value.trim().toLowerCase();
  if (!id) return;

  const resultDiv = document.getElementById("discover-result");
  resultDiv.style.display = "block";
  resultDiv.innerHTML = '<span class="loading">Discovering lifts and slopes... (up to 15s)</span>';

  const resp = await fetch(`/api/stations/${id}/discover`, { method: "POST" });
  const data = await resp.json();

  if (data.error) {
    resultDiv.innerHTML = `<div class="alert alert-error">${data.error}</div>`;
    return;
  }

  let html = "";
  for (const sector of data.sectors) {
    html += `<h3>${sector.name}</h3>`;
    if (sector.lifts.length) {
      html += "<p><strong>Lifts:</strong> " + sector.lifts.map((l) => `${l.name} (${l.type})`).join(", ") + "</p>";
    }
    if (sector.slopes.length) {
      html += "<p><strong>Slopes:</strong> " + sector.slopes.map((s) => `${s.name}`).join(", ") + "</p>";
    }
  }
  resultDiv.innerHTML = html || "<p>No sectors found.</p>";
}

async function refreshStations() {
  const cards = document.querySelectorAll(".station-card");
  for (const card of cards) {
    const stationId = card.dataset.stationId;
    try {
      const resp = await fetch(`/api/stations/${stationId}/status`);
      if (!resp.ok) continue;
      // Just reload the page for simplicity on data update
    } catch (e) {
      // ignore
    }
  }
}

async function loadHAMQTTSettings() {
  try {
    const resp = await fetch("/api/settings/ha-mqtt");
    const data = await resp.json();
    const hostEl = document.getElementById("ha-host");
    if (hostEl) {
      hostEl.value = data.host || "";
      document.getElementById("ha-port").value = data.port || 1883;
      document.getElementById("ha-username").value = data.username || "";
    }
  } catch (e) {
    // ignore
  }
}

async function saveHAMQTT() {
  const payload = {
    host: document.getElementById("ha-host").value,
    port: document.getElementById("ha-port").value,
    username: document.getElementById("ha-username").value,
  };
  const pw = document.getElementById("ha-password").value;
  if (pw) payload.password = pw;

  const resp = await fetch("/api/settings/ha-mqtt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (resp.ok) alert("MQTT settings saved. Publisher reconnecting.");
}

async function loadMapping() {
  try {
    const resp = await fetch("/api/settings/mapping");
    const data = await resp.json();
    const editor = document.getElementById("mapping-editor");
    if (!editor) return;

    let html = "";
    for (const [key, value] of Object.entries(data)) {
      html += `<div class="mapping-row">
        <input type="text" class="map-key" value="${key}" readonly>
        <span class="arrow">&rarr;</span>
        <input type="text" class="map-value" value="${value}">
      </div>`;
    }
    editor.innerHTML = html;
  } catch (e) {
    // ignore
  }
}

async function saveMapping() {
  const rows = document.querySelectorAll(".mapping-row");
  const mapping = {};
  rows.forEach((row) => {
    const key = row.querySelector(".map-key").value;
    const value = row.querySelector(".map-value").value;
    if (key) mapping[key] = value;
  });

  const resp = await fetch("/api/settings/mapping", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mapping),
  });
  if (resp.ok) alert("Mapping saved.");
}

async function changePassword() {
  const pw = document.getElementById("new-password").value;
  const resp = await fetch("/api/settings/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: pw }),
  });
  if (resp.ok) {
    alert("Password updated.");
    document.getElementById("new-password").value = "";
  } else {
    const data = await resp.json();
    alert(data.error || "Failed to update password");
  }
}
