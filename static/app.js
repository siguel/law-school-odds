/* ── Law School Admission Odds – Frontend ────────────────────────── */

let allSchools = [];       // [{name, slug, rank}, ...]
let selectedSchools = new Set();

// ── Scenario colors ─────────────────────────────────────────────────
const SCENARIO_COLORS = {
  base:         { fill: "#64748b", label: "Base Model" },
  median_plus:  { fill: "#3b82f6", label: "Median+1 LSAT" },
  gpa_comp:     { fill: "#8b5cf6", label: "25th–Med GPA" },
  both_upgrade: { fill: "#22c55e", label: "Both Upgrades" },
};

// ── Init ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  const resp = await fetch("/api/schools");
  allSchools = await resp.json();
  buildSchoolList();
  updateSelectedCount();

  document.getElementById("school-search").addEventListener("input", onSearch);
  document.getElementById("clear-all").addEventListener("click", clearAll);
  document.getElementById("toggle-list").addEventListener("click", toggleList);
  document.getElementById("analyze-btn").addEventListener("click", runAnalysis);

  document.querySelectorAll(".tier-btn[data-tier]").forEach(btn => {
    btn.addEventListener("click", () => selectTier(btn.dataset.tier));
  });
});

// ── School list ─────────────────────────────────────────────────────

function buildSchoolList() {
  const container = document.getElementById("school-list");
  container.innerHTML = "";
  allSchools.forEach(school => {
    const div = document.createElement("div");
    div.className = "school-item";
    div.dataset.name = school.name.toLowerCase();
    div.dataset.rank = school.rank || 999;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = `school-${school.slug}`;
    cb.value = school.name;
    cb.addEventListener("change", () => {
      if (cb.checked) selectedSchools.add(school.name);
      else selectedSchools.delete(school.name);
      updateSelectedCount();
    });
    const rankSpan = document.createElement("span");
    rankSpan.className = "school-rank";
    rankSpan.textContent = school.rank ? `#${school.rank}` : "NR";
    const label = document.createElement("label");
    label.htmlFor = cb.id;
    label.textContent = school.name;
    label.style.cursor = "pointer";
    div.appendChild(cb);
    div.appendChild(rankSpan);
    div.appendChild(label);
    container.appendChild(div);
  });
}

function onSearch(e) {
  const query = e.target.value.toLowerCase().trim();
  const items = document.querySelectorAll(".school-item");
  let visible = 0;
  items.forEach(item => {
    const match = !query || item.dataset.name.includes(query);
    item.classList.toggle("hidden", !match);
    if (match) visible++;
  });
  const countEl = document.getElementById("search-count");
  countEl.textContent = query ? `${visible} match${visible !== 1 ? "es" : ""}` : "";
  if (query) document.getElementById("school-list-container").classList.remove("hidden");
}

function selectTier(tier) {
  fetch(`/api/tiers/${tier}`)
    .then(r => r.json())
    .then(names => {
      names.forEach(n => selectedSchools.add(n));
      syncCheckboxes();
      updateSelectedCount();
    });
}

function clearAll() {
  selectedSchools.clear();
  syncCheckboxes();
  updateSelectedCount();
}

function syncCheckboxes() {
  document.querySelectorAll("#school-list input[type=checkbox]").forEach(cb => {
    cb.checked = selectedSchools.has(cb.value);
  });
}

function updateSelectedCount() {
  document.getElementById("selected-count").textContent = selectedSchools.size;
}

function toggleList() {
  const container = document.getElementById("school-list-container");
  const btn = document.getElementById("toggle-list");
  const isHidden = container.classList.toggle("hidden");
  btn.textContent = isHidden ? "Show School List" : "Hide School List";
}

// ── Analysis ────────────────────────────────────────────────────────

async function runAnalysis() {
  const lsatVal = document.getElementById("lsat").value;
  const gpaVal = document.getElementById("gpa").value;
  const isKjd = document.getElementById("is_kjd").checked;
  const isUrm = document.getElementById("is_urm").checked;

  const errors = [];
  if (!lsatVal || lsatVal < 120 || lsatVal > 180) errors.push("LSAT must be 120-180");
  if (!gpaVal || gpaVal < 0 || gpaVal > 4.33) errors.push("GPA must be 0-4.33");
  if (selectedSchools.size === 0) errors.push("Select at least one school");

  const errorEl = document.getElementById("error-msg");
  if (errors.length) {
    errorEl.textContent = errors.join(". ") + ".";
    errorEl.classList.remove("hidden");
    return;
  }
  errorEl.classList.add("hidden");

  const btn = document.getElementById("analyze-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Analyzing...';

  try {
    const resp = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gpa: parseFloat(gpaVal),
        lsat: parseFloat(lsatVal),
        is_kjd: isKjd,
        is_urm: isUrm,
        schools: Array.from(selectedSchools),
      }),
    });
    const data = await resp.json();
    if (data.error) {
      errorEl.textContent = data.error;
      errorEl.classList.remove("hidden");
      return;
    }
    renderResults(data);
  } catch (err) {
    errorEl.textContent = "Request failed: " + err.message;
    errorEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze Odds";
  }
}

// ── Render results ──────────────────────────────────────────────────

function renderResults(data) {
  const section = document.getElementById("results-section");
  section.classList.remove("hidden");

  const a = data.applicant;
  const kjdLabel = a.is_kjd ? "KJD" : "Non-KJD";
  const urmLabel = a.is_urm ? "URM" : "Non-URM";
  document.getElementById("applicant-summary").textContent =
    `GPA ${a.gpa.toFixed(2)} / LSAT ${a.lsat.toFixed(0)} / ${kjdLabel} / ${urmLabel}`;

  // Sort results by rank
  const results = data.results.sort((a, b) => {
    const ra = a.rank || 999;
    const rb = b.rank || 999;
    return ra - rb || a.school.localeCompare(b.school);
  });

  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";

  let hasMedianFlag = false;
  let hasGpaFloorFlag = false;
  let usedColorKeys = new Set();

  results.forEach(r => {
    if (r.error) {
      const card = document.createElement("div");
      card.className = "school-card school-card-error";
      card.innerHTML = `
        <div class="card-header">
          <span class="card-rank">${r.rank ? "#" + r.rank : "NR"}</span>
          <span class="card-school-name">${esc(r.school)}</span>
        </div>
        <div class="card-error">${esc(r.error)}</div>`;
      grid.appendChild(card);
      return;
    }

    if (r.at_lsat_median) hasMedianFlag = true;
    if (r.below_gpa_floor) hasGpaFloorFlag = true;

    const scenarios = r.scenarios || [];
    scenarios.forEach(s => usedColorKeys.add(s.color_key));

    const card = document.createElement("div");
    card.className = "school-card";

    // Build scenario bars HTML
    let scenarioBarsHtml = "";
    scenarios.forEach((s, i) => {
      const color = SCENARIO_COLORS[s.color_key] || { fill: "#999", label: s.label };
      const rate = s.best_estimate.rate;
      const rateStr = rate != null ? rate.toFixed(1) + "%" : "N/A";
      const verdictCls = verdictClassFromRate(rate);
      const barWidth = rate != null ? Math.max(rate, 2) : 0; // min 2% width for visibility
      scenarioBarsHtml += `
        <div class="scenario-row" data-index="${i}">
          <div class="scenario-label-col">
            <span class="scenario-color-dot" style="background:${color.fill}"></span>
            <span class="scenario-name">${esc(s.label)}</span>
          </div>
          <div class="scenario-bar-col">
            <div class="scenario-bar-bg">
              <div class="scenario-bar-fill" style="width:${barWidth}%;background:${color.fill}"></div>
            </div>
          </div>
          <div class="scenario-rate-col ${verdictCls}">${rateStr}</div>
          <div class="scenario-n-col">n=${s.best_estimate.n}</div>
        </div>`;
    });

    // Build the details for each scenario (collapsible)
    let scenarioDetailsHtml = "";
    scenarios.forEach((s, i) => {
      const color = SCENARIO_COLORS[s.color_key] || { fill: "#999", label: s.label };
      scenarioDetailsHtml += `
        <div class="scenario-detail" data-index="${i}">
          <div class="scenario-detail-header" style="border-left: 3px solid ${color.fill}">
            <strong>${esc(s.label)}</strong>
            <span class="scenario-desc">${esc(s.description)}</span>
          </div>
          <table class="card-table scenario-table">
            <tr>
              <th>Level</th><th>N</th><th>Adm</th><th>Rate</th>
            </tr>
            <tr class="${s.best_estimate.level === 'total' ? 'best-row' : ''}">
              <td>Total</td><td>${s.total.total}</td><td>${s.total.accepted}</td><td>${fmtRate(s.total.rate)}</td>
            </tr>
            <tr class="${s.best_estimate.level === 'kjd' ? 'best-row' : ''}">
              <td>${esc(r.kjd_label)}</td><td>${s.kjd.total}</td><td>${s.kjd.accepted}</td><td>${fmtRate(s.kjd.rate)}</td>
            </tr>
            <tr class="${s.best_estimate.level === 'urm' ? 'best-row' : ''}">
              <td>${esc(r.urm_label)}</td><td>${s.urm.total}</td><td>${s.urm.accepted}</td><td>${fmtRate(s.urm.rate)}</td>
            </tr>
            <tr class="${s.best_estimate.level === 'on_time' ? 'best-row' : ''}">
              <td>On-time</td><td>${s.on_time.total}</td><td>${s.on_time.accepted}</td><td>${fmtRate(s.on_time.rate)}</td>
            </tr>
          </table>
        </div>`;
    });

    // Find the primary (base) scenario for the pie chart
    const baseSc = scenarios.find(s => s.color_key === "base") || scenarios[0];
    const baseRate = baseSc ? baseSc.best_estimate.rate : null;
    const baseVerdict = baseSc ? baseSc.verdict : "Low Data";

    const mflag = r.at_lsat_median ? '<span class="at-median-flag"> *</span>' : "";
    const gflag = r.below_gpa_floor ? '<span class="below-floor-flag"> **</span>' : "";

    card.innerHTML = `
      <div class="card-header">
        <span class="card-rank">${r.rank ? "#" + r.rank : "NR"}</span>
        <span class="card-school-name">${esc(r.school)}</span>
        ${r.warning ? '<span class="card-warning">' + esc(r.warning) + '</span>' : ''}
      </div>
      <div class="card-body">
        <div class="card-chart-col">
          <canvas class="pie-canvas pie-primary" width="130" height="130"></canvas>
          <div class="card-verdict ${verdictClass(baseVerdict)}">${baseVerdict}</div>
          <div class="card-basis">${baseSc ? esc(baseSc.best_estimate.label) : ''} (n=${baseSc ? baseSc.best_estimate.n : 0})</div>
        </div>
        <div class="card-scenarios-col">
          <div class="card-ranges">
            <span class="range-label">LSAT 25th/50th:</span> ${fmtPct(r.lsat_25, true)} / ${fmtPct(r.lsat_50, true)}${mflag}<br>
            <span class="range-label">GPA 25th/50th:</span> ${fmtPct(r.gpa_25, false)} / ${fmtPct(r.gpa_50, false)}${gflag}
          </div>
          <div class="scenario-bars">
            ${scenarioBarsHtml}
          </div>
          <button class="scenario-toggle-btn" onclick="this.closest('.school-card').querySelector('.scenario-details').classList.toggle('hidden'); this.textContent = this.textContent === 'Show Details' ? 'Hide Details' : 'Show Details';">Show Details</button>
          <div class="scenario-details hidden">
            ${scenarioDetailsHtml}
          </div>
        </div>
      </div>`;

    grid.appendChild(card);

    // Draw the main pie chart with scenario segments
    const primaryCanvas = card.querySelector(".pie-primary");
    if (scenarios.length > 1) {
      drawMultiPie(primaryCanvas, scenarios);
    } else {
      drawPie(primaryCanvas, baseRate, baseVerdict);
    }
  });

  // Legend
  const legend = document.getElementById("legend");
  let legendText = "<strong>Scenario Colors:</strong><br>";
  for (const [key, info] of Object.entries(SCENARIO_COLORS)) {
    if (usedColorKeys.has(key)) {
      legendText += `<span class="legend-dot" style="background:${info.fill}"></span> ${info.label}&nbsp;&nbsp;`;
    }
  }
  legendText += "<br><br>";
  if (hasMedianFlag) legendText += "* = applicant is at LSAT median (treated as below-median for range)<br>";
  if (hasGpaFloorFlag) legendText += "** = applicant GPA is below the 2nd-lowest accepted GPA (range capped at floor)<br>";
  legendText += "Bars show best estimate: the most specific cascade level with N &ge; 5.<br>";
  legendText += `Cascade: Total (decided) &rarr; ${kjdLabel} &rarr; ${urmLabel} &rarr; On-time (&le; Jan 1)<br>`;
  legendText += "Percentiles: ABA First Year Class 2025. Outcomes: LSD self-reports.";
  legend.innerHTML = legendText;

  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── Multi-scenario pie chart (concentric rings) ─────────────────────

function drawMultiPie(canvas, scenarios) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const maxRadius = Math.min(cx, cy) - 4;

  ctx.clearRect(0, 0, w, h);

  // Draw concentric rings: outermost = first scenario (lowest rate),
  // innermost = last scenario (highest rate)
  const ringWidth = maxRadius / (scenarios.length + 1); // +1 for center hole

  scenarios.forEach((s, i) => {
    const outerR = maxRadius - i * ringWidth;
    const innerR = outerR - ringWidth + 2; // 2px gap between rings
    const rate = s.best_estimate.rate;
    const color = SCENARIO_COLORS[s.color_key] || { fill: "#999" };

    if (rate == null) {
      // Grey ring
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
      ctx.arc(cx, cy, Math.max(innerR, 0), 0, Math.PI * 2, true);
      ctx.fillStyle = "#e5e7eb";
      ctx.fill();
      return;
    }

    const pct = rate / 100;
    const acceptAngle = pct * Math.PI * 2;
    const startAngle = -Math.PI / 2;

    // Reject arc (grey)
    if (pct < 1) {
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, startAngle + acceptAngle, startAngle + Math.PI * 2);
      ctx.arc(cx, cy, Math.max(innerR, 0), startAngle + Math.PI * 2, startAngle + acceptAngle, true);
      ctx.closePath();
      ctx.fillStyle = "#e5e7eb";
      ctx.fill();
    }

    // Accept arc (colored)
    if (pct > 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, startAngle, startAngle + acceptAngle);
      ctx.arc(cx, cy, Math.max(innerR, 0), startAngle + acceptAngle, startAngle, true);
      ctx.closePath();
      ctx.fillStyle = color.fill;
      ctx.fill();
    }
  });

  // White center
  const centerR = maxRadius - scenarios.length * ringWidth;
  if (centerR > 0) {
    ctx.beginPath();
    ctx.arc(cx, cy, centerR, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
  }

  // Show base rate in center
  const baseSc = scenarios.find(s => s.color_key === "base") || scenarios[0];
  const baseRate = baseSc ? baseSc.best_estimate.rate : null;
  if (baseRate != null) {
    ctx.font = "bold 18px -apple-system, sans-serif";
    ctx.fillStyle = "#2c3e50";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(baseRate.toFixed(0) + "%", cx, cy);
  }
}

// ── Single pie chart drawing ────────────────────────────────────────

function drawPie(canvas, rate, verdict, colorOverride) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.min(cx, cy) - 6;

  ctx.clearRect(0, 0, w, h);

  if (rate == null) {
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = "#e5e7eb";
    ctx.fill();
    ctx.font = "bold 22px -apple-system, sans-serif";
    ctx.fillStyle = "#999";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("?", cx, cy);
    return;
  }

  const pct = rate / 100;
  const acceptAngle = pct * Math.PI * 2;
  const startAngle = -Math.PI / 2;

  const acceptColor = colorOverride || getAcceptColor(verdict);
  const rejectColor = "#e5e7eb";

  if (pct < 1) {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle + acceptAngle, startAngle + Math.PI * 2);
    ctx.closePath();
    ctx.fillStyle = rejectColor;
    ctx.fill();
  }

  if (pct > 0) {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle, startAngle + acceptAngle);
    ctx.closePath();
    ctx.fillStyle = acceptColor;
    ctx.fill();
  }

  const innerRadius = radius * 0.6;
  ctx.beginPath();
  ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();

  ctx.font = "bold 20px -apple-system, sans-serif";
  ctx.fillStyle = "#2c3e50";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(rate.toFixed(0) + "%", cx, cy);
}

function getAcceptColor(verdict) {
  switch (verdict) {
    case "Likely":      return "#22c55e";
    case "Good Chance": return "#3b82f6";
    case "Possible":    return "#f59e0b";
    case "Unlikely":    return "#ef4444";
    default:            return "#d1d5db";
  }
}

// ── Helpers ──────────────────────────────────────────────────────────

function fmtRange(r, isLsat) {
  if (!r) return "N/A";
  if (isLsat) return `${r.lower.toFixed(0)}-${r.upper.toFixed(0)}`;
  return `${r.lower.toFixed(2)}-${r.upper.toFixed(2)}`;
}

function fmtPct(val, isLsat) {
  if (val == null) return "N/A";
  return isLsat ? val.toFixed(0) : val.toFixed(2);
}

function fmtRate(rate) {
  if (rate == null) return "N/A";
  return rate.toFixed(1) + "%";
}

function verdictClass(v) {
  switch (v) {
    case "Likely":      return "verdict-likely";
    case "Good Chance": return "verdict-good-chance";
    case "Possible":    return "verdict-possible";
    case "Unlikely":    return "verdict-unlikely";
    default:            return "verdict-low-data";
  }
}

function verdictClassFromRate(rate) {
  if (rate == null) return "verdict-low-data";
  if (rate >= 60) return "verdict-likely";
  if (rate >= 40) return "verdict-good-chance";
  if (rate >= 20) return "verdict-possible";
  return "verdict-unlikely";
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
