/*
 * Sensor Monitoring Dashboard - frontend logic.
 *
 * Polls the Flask REST API on an interval and updates the DOM + Chart.js
 * charts without a page reload. All state (current mode, current scenario)
 * lives on the server; this file just reflects it and lets the user change
 * it via POST requests.
 */

const POLL_INTERVAL_MS = 1500;
const MAX_REALTIME_POINTS = 30;

let currentMode = "DEMO";
let realtimeChart = null;
let historyChart = null;
let rejectionChart = null;

const CONDITION_CLASS = {
    "NORMAL": "condition-normal",
    "DEGRADED": "condition-degraded",
    "SUBSTITUTED": "condition-substituted",
    "INSUFFICIENT EVIDENCE": "condition-insufficient",
};

function $(id) {
    return document.getElementById(id);
}

// ---------- Chart setup ----------

function initCharts() {
    const commonOptions = {
        responsive: true,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
            x: { ticks: { color: "#8b93a7" }, grid: { color: "#262f45" } },
            y: { ticks: { color: "#8b93a7" }, grid: { color: "#262f45" } },
        },
        plugins: {
            legend: { labels: { color: "#e7ecf5" } },
        },
    };

    realtimeChart = new Chart($("realtimeChart").getContext("2d"), {
        type: "line",
        data: {
            labels: [],
            datasets: [
                { label: "Amplitude (dB)", data: [], borderColor: "#4f8dfd", tension: 0.3 },
                { label: "Phase (deg)", data: [], borderColor: "#2ecc71", tension: 0.3 },
                { label: "Residual", data: [], borderColor: "#e74c3c", tension: 0.3 },
            ],
        },
        options: commonOptions,
    });

    historyChart = new Chart($("historyChart").getContext("2d"), {
        type: "line",
        data: {
            labels: [],
            datasets: [
                { label: "Amplitude (dB)", data: [], borderColor: "#4f8dfd", tension: 0.2 },
                { label: "Residual", data: [], borderColor: "#e74c3c", tension: 0.2 },
            ],
        },
        options: commonOptions,
    });

    rejectionChart = new Chart($("rejectionChart").getContext("2d"), {
        type: "bar",
        data: {
            labels: [],
            datasets: [{ label: "Count", data: [], backgroundColor: "#e67e22" }],
        },
        options: commonOptions,
    });
}

// ---------- API helpers ----------

async function apiGet(path) {
    const res = await fetch(path);
    return res.json();
}

async function apiPost(path, body) {
    const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    return res.json();
}

// ---------- Rendering ----------

function renderWaitingState(isWaiting) {
    $("live-waiting").classList.toggle("hidden", !isWaiting);
    $("value-cards").classList.toggle("hidden", isWaiting);
    document.querySelector(".condition-banner-wrap").classList.toggle("hidden", isWaiting);
    document.querySelector(".meta-strip").classList.toggle("hidden", isWaiting);
}

function renderRecord(record) {
    if (!record) {
        renderWaitingState(currentMode === "LIVE");
        return;
    }
    renderWaitingState(false);

    $("val-amplitude").textContent = `${record.amplitude_db.toFixed(1)} dB`;
    $("val-phase").textContent = `${record.phase_deg.toFixed(1)}°`;
    $("val-residual").textContent =
        record.residual === null || record.residual === undefined
            ? "—"
            : record.residual.toFixed(3);
    $("val-temp").textContent = `${record.temp_ambient_c.toFixed(1)}°C`;

    const banner = $("condition-banner");
    banner.textContent = record.condition_label;
    banner.className = "condition-banner " + (CONDITION_CLASS[record.condition_label] || "condition-unknown");

    $("meta-validity").textContent = record.validity_bit ? "1 (valid)" : "0 (invalid)";
    $("meta-gate").textContent = record.validity_bit ? "PASS" : "HOLD";
    $("meta-antenna").textContent = record.antenna;
    $("meta-frequency").textContent = `${record.frequency} MHz`;
    $("meta-container").textContent = record.container_id;
    $("meta-timestamp").textContent = new Date(record.timestamp).toLocaleTimeString();

    updateRealtimeChart(record);
}

function updateRealtimeChart(record) {
    const label = new Date(record.timestamp).toLocaleTimeString();
    const ds = realtimeChart.data;

    ds.labels.push(label);
    ds.datasets[0].data.push(record.amplitude_db);
    ds.datasets[1].data.push(record.phase_deg);
    ds.datasets[2].data.push(record.residual);

    if (ds.labels.length > MAX_REALTIME_POINTS) {
        ds.labels.shift();
        ds.datasets.forEach((d) => d.data.shift());
    }
    realtimeChart.update();
}

function renderHistory(records) {
    const ordered = [...records].reverse(); // oldest -> newest for a left-to-right chart
    historyChart.data.labels = ordered.map((r) => new Date(r.timestamp).toLocaleTimeString());
    historyChart.data.datasets[0].data = ordered.map((r) => r.amplitude_db);
    historyChart.data.datasets[1].data = ordered.map((r) => r.residual);
    historyChart.update();
}

function renderRejections(rejections) {
    rejectionChart.data.labels = rejections.map((r) => r.reason);
    rejectionChart.data.datasets[0].data = rejections.map((r) => r.count);
    rejectionChart.update();
}

function renderIntegrity(integrity) {
    const el = $("integrity-status");
    if (integrity.chain_valid === null || integrity.chain_valid === undefined) {
        el.textContent = "NO DATA YET";
        el.style.color = "#8b93a7";
    } else if (integrity.chain_valid) {
        el.textContent = "✓ VERIFIED";
        el.style.color = "#2ecc71";
    } else {
        el.textContent = "✗ BROKEN";
        el.style.color = "#e74c3c";
    }
}

// ---------- Polling ----------

async function pollLatest() {
    try {
        const data = await apiGet("/api/latest");
        currentMode = data.mode;
        renderRecord(data.record);
    } catch (err) {
        console.error("Failed to fetch /api/latest", err);
    }
}

async function refreshHistory() {
    const containerId = $("history-container").value.trim();
    let url = "/api/history?limit=100";
    if (containerId) url += `&container_id=${encodeURIComponent(containerId)}`;
    try {
        const data = await apiGet(url);
        renderHistory(data.records);
    } catch (err) {
        console.error("Failed to fetch /api/history", err);
    }
}

async function refreshRejections() {
    try {
        const data = await apiGet("/api/rejections");
        renderRejections(data.rejections);
    } catch (err) {
        console.error("Failed to fetch /api/rejections", err);
    }
}

async function refreshIntegrity() {
    try {
        const data = await apiGet("/api/integrity");
        renderIntegrity(data);
    } catch (err) {
        console.error("Failed to fetch /api/integrity", err);
    }
}

// ---------- Mode + scenario controls ----------

async function setMode(mode) {
    await apiPost("/api/mode", { mode });
    currentMode = mode;

    $("btn-demo").classList.toggle("active", mode === "DEMO");
    $("btn-live").classList.toggle("active", mode === "LIVE");
    $("demo-controls").classList.toggle("hidden", mode !== "DEMO");

    // Clear the realtime chart on a mode switch so DEMO and LIVE traces
    // never visually blend together.
    realtimeChart.data.labels = [];
    realtimeChart.data.datasets.forEach((d) => (d.data = []));
    realtimeChart.update();

    await pollLatest();
}

async function applyScenario() {
    const scenario = $("scenario-select").value;
    const feedback = $("scenario-feedback");
    try {
        await apiPost("/api/demo/scenario", { scenario });
        feedback.textContent = `Applied: ${scenario.replace("_", " ")}`;
    } catch (err) {
        feedback.textContent = "Failed to apply scenario";
    }
    setTimeout(() => (feedback.textContent = ""), 2500);
}

// ---------- Init ----------

function wireControls() {
    $("btn-demo").addEventListener("click", () => setMode("DEMO"));
    $("btn-live").addEventListener("click", () => setMode("LIVE"));
    $("btn-apply-scenario").addEventListener("click", applyScenario);
    $("btn-refresh-history").addEventListener("click", refreshHistory);
}

async function init() {
    initCharts();
    wireControls();

    const modeData = await apiGet("/api/mode");
    currentMode = modeData.mode;
    $("btn-demo").classList.toggle("active", currentMode === "DEMO");
    $("btn-live").classList.toggle("active", currentMode === "LIVE");
    $("demo-controls").classList.toggle("hidden", currentMode !== "DEMO");

    await pollLatest();
    await refreshHistory();
    await refreshRejections();
    await refreshIntegrity();

    setInterval(pollLatest, POLL_INTERVAL_MS);
    setInterval(refreshHistory, POLL_INTERVAL_MS * 4);
    setInterval(refreshRejections, POLL_INTERVAL_MS * 6);
    setInterval(refreshIntegrity, POLL_INTERVAL_MS * 6);
}

document.addEventListener("DOMContentLoaded", init);
