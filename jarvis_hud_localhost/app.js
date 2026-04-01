const app = document.getElementById("app");
const stateText = document.getElementById("stateText");
const modeLabel = document.getElementById("modeLabel");
const statusChip = document.getElementById("statusChip");
const clockTime = document.getElementById("clockTime");
const clockDate = document.getElementById("clockDate");
const waveform = document.getElementById("waveform");

const bars = [];
for (let i = 0; i < 48; i += 1) {
    const el = document.createElement("div");
    el.className = "bar";
    el.style.height = `${18 + Math.abs(i - 24) * 0.6}px`;
    el.style.animationDelay = `${i * 0.03}s`;
    waveform.appendChild(el);
    bars.push(el);
}

function titleForState(state) {
    switch (state) {
        case "listening": return "LISTENING";
        case "processing": return "PROCESSING";
        case "speaking": return "SPEAKING";
        case "idle": return "OFFLINE";
        default: return "STANDBY";
    }
}

function updateClock() {
    const now = new Date();
    clockTime.textContent = now.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });
    clockDate.textContent = now.toLocaleDateString([], {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric"
    }).toUpperCase();
}

function updateVisualState(state) {
    app.className = `hud state-${state}`;
    const label = state.toUpperCase();
    stateText.textContent = label;
    modeLabel.textContent = label.charAt(0) + label.slice(1).toLowerCase();
    statusChip.textContent = titleForState(state);

    const params = {
        armed: { base: 14, amp: 12, speed: 0.8 },
        listening: { base: 24, amp: 36, speed: 1.45 },
        processing: { base: 20, amp: 22, speed: 2.0 },
        speaking: { base: 16, amp: 42, speed: 2.8 },
        idle: { base: 6, amp: 4, speed: 0.4 }
    }[state] || { base: 14, amp: 10, speed: 1 };

    bars.forEach((bar, i) => {
        const distance = Math.abs(i - bars.length / 2);
        const lift = Math.max(0, params.amp - distance * 1.2);
        bar.style.height = `${params.base + lift}px`;
        bar.style.animationDuration = `${Math.max(0.8, 2.8 / params.speed)}s`;
        bar.style.opacity = state === "armed" ? "0.7" : "1";
    });
}

async function pollState() {
    try {
        const res = await fetch(`/api/state?ts=${Date.now()}`, { cache: "no-store" });
        const data = await res.json();
        updateVisualState(data.state || "armed");
    } catch {
        updateVisualState("armed");
    }
}

updateClock();
setInterval(updateClock, 1000);
pollState();
setInterval(pollState, 250);