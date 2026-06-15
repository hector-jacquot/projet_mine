/* global Chart */

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("fr-FR");
}

function setCardState(cardEl, isAlert) {
  // Basculer la classe alert-active pour la bordure
  cardEl.classList.toggle("alert-active", isAlert);
  
  // Mettre à jour le texte du statut
  const statusEl = cardEl.querySelector(".sensor-status");
  if (statusEl) {
    statusEl.textContent = isAlert ? "ALERTE" : "SÉCURISÉ";
    // Mettre à jour les styles du statut
    statusEl.style.color = isAlert ? "var(--alert-danger)" : "var(--alert-success)";
    statusEl.style.textDecoration = isAlert ? "underline" : "none";
  }
}

async function fetchJson(url) {
  const r = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

let chart;
let currentType;

async function loadHistory(capteurType) {
  currentType = capteurType;
  const data = await fetchJson(`/api/historique/${encodeURIComponent(capteurType)}`);
  const labels = data.points.map((p) => fmtDate(p.created_at));
  const values = data.points.map((p) => p.valeur);
  const alertFlags = data.points.map((p) => p.buzzer_on);

  const ctx = document.getElementById("historyChart").getContext("2d");
  const datasetLabel = (window.MINES.capteurs[capteurType] || {}).label || capteurType;

  const ds = {
    label: datasetLabel,
    data: values,
    tension: 0.25,
    fill: true,
    borderColor: "#0d6efd",
    backgroundColor: "rgba(13, 110, 253, 0.12)",
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBackgroundColor: alertFlags.map((a) => (a ? "#dc3545" : "#0d6efd")),
  };

  if (!chart) {
    chart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [ds] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true },
          tooltip: { mode: "index", intersect: false },
        },
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { maxRotation: 0, autoSkip: true } },
          y: { beginAtZero: false },
        },
      },
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0] = ds;
    chart.update();
  }
}

async function refreshLatest() {
  const payload = await fetchJson("/api/dernieres");
  document.querySelectorAll(".sensor-card").forEach((card) => {
    const t = card.dataset.capteur;
    const p = payload[t];
    if (!p) return;

    card.querySelector(".sensor-value").textContent = p.valeur ?? "—";
    card.querySelector(".sensor-time").textContent = p.created_at ? fmtDate(p.created_at) : "—";

    const isAlert = !!p.buzzer_on;
    setCardState(card, isAlert);
  });

  // Recharge l'historique du capteur affiché si besoin
  if (currentType) {
    await loadHistory(currentType);
  }
}

async function refreshOutsideTemp() {
  try {
    const m = await fetchJson("/api/meteo");
    const el = document.getElementById("outsideTemp");
    if (el && m.ok && m.temp_c !== null && m.temp_c !== undefined) {
      el.textContent = m.temp_c;
    }
  } catch (_e) {
    // silencieux
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const select = document.getElementById("capteurSelect");
  const initial = (window.MINES && window.MINES.initialType) || "temperature";

  if (select) {
    select.value = initial;
    select.addEventListener("change", () => loadHistory(select.value));
  }

  document.querySelectorAll(".btn-history").forEach((btn) => {
    btn.addEventListener("click", () => {
      const t = btn.dataset.capteur;
      if (select) select.value = t;
      loadHistory(t);
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    });
  });

  await loadHistory(initial);
  await refreshLatest();
  await refreshOutsideTemp();

  // "temps réel" (démo)
  setInterval(() => refreshLatest().catch(() => {}), 5000);
  setInterval(() => refreshOutsideTemp().catch(() => {}), 60000);
});

