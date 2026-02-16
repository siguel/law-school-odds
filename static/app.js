/* ── Law School Admission Odds – Frontend ────────────────────────── */

let allSchools = [];       // [{name, slug, rank}, ...]
let selectedSchools = new Set();

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
  let hasCompFlag = false;

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
    const hasComp = !!r.comparison;
    if (hasComp) hasCompFlag = true;

    const card = document.createElement("div");
    card.className = "school-card";

    const be = r.best_estimate;
    const rate = be.rate;
    const verdictCls = verdictClass(r.verdict);

    const mflag = r.at_lsat_median ? '<span class="at-median-flag"> *</span>' : "";
    const gflag = r.below_gpa_floor ? '<span class="below-floor-flag"> **</span>' : "";

    // Build comparison chart column if below 25th GPA
    let compChartHtml = "";
    if (hasComp) {
      const c = r.comparison;
      const compBe = pickBestEstimate(c.total, c.kjd, c.urm, c.on_time, r.kjd_label, r.urm_label);
      compChartHtml = `
        <div class="card-chart-col comp-chart-col">
          <div class="comp-label">If 25th&ndash;med GPA</div>
          <canvas class="pie-canvas pie-comp" width="110" height="110"></canvas>
          <div class="card-verdict ${verdictClassFromRate(compBe.rate)}">${fmtRate(compBe.rate)}</div>
          <div class="card-basis">${esc(compBe.label)} (n=${compBe.n})</div>
        </div>`;
    }

    // Build comparison table rows
    let compColHeaders = "";
    let compRowTotal = "", compRowKjd = "", compRowUrm = "", compRowOt = "";
    if (hasComp) {
      const c = r.comparison;
      compColHeaders = `<th class="comp-th">N</th><th class="comp-th">Adm</th><th class="comp-th">Rate</th>`;
      compRowTotal = `<td class="comp-td">${c.total.total}</td><td class="comp-td">${c.total.accepted}</td><td class="comp-td">${fmtRate(c.total.rate)}</td>`;
      compRowKjd   = `<td class="comp-td">${c.kjd.total}</td><td class="comp-td">${c.kjd.accepted}</td><td class="comp-td">${fmtRate(c.kjd.rate)}</td>`;
      compRowUrm   = `<td class="comp-td">${c.urm.total}</td><td class="comp-td">${c.urm.accepted}</td><td class="comp-td">${fmtRate(c.urm.rate)}</td>`;
      compRowOt    = `<td class="comp-td">${c.on_time.total}</td><td class="comp-td">${c.on_time.accepted}</td><td class="comp-td">${fmtRate(c.on_time.rate)}</td>`;
    }

    card.innerHTML = `
      <div class="card-header">
        <span class="card-rank">${r.rank ? "#" + r.rank : "NR"}</span>
        <span class="card-school-name">${esc(r.school)}</span>
      </div>
      <div class="card-body">
        <div class="card-chart-col">
          ${hasComp ? '<div class="comp-label">Your range</div>' : ''}
          <canvas class="pie-canvas pie-primary" width="${hasComp ? 110 : 140}" height="${hasComp ? 110 : 140}"></canvas>
          <div class="card-verdict ${verdictCls}">${r.verdict}</div>
          <div class="card-basis">${esc(be.label)} (n=${be.n})</div>
        </div>
        ${compChartHtml}
        <div class="card-stats-col">
          <div class="card-ranges">
            <span class="range-label">LSAT:</span> ${fmtRange(r.lsat_range, true)}${mflag}
            <span class="range-med">(med ${fmtPct(r.lsat_50, true)})</span><br>
            <span class="range-label">GPA:</span> ${fmtRange(r.gpa_range, false)}${gflag}
            <span class="range-med">(med ${fmtPct(r.gpa_50, false)})</span>
            ${hasComp ? '<br><span class="range-label comp-color">Comp GPA:</span> ' + fmtRange(r.comparison.gpa_range, false) + ' <span class="range-med">(25th&ndash;med)</span>' : ''}
          </div>
          <table class="card-table">
            <tr>
              <th>Level</th><th>N</th><th>Adm</th><th>Rate</th>${compColHeaders}
            </tr>
            <tr class="${be.level === 'total' ? 'best-row' : ''}">
              <td>Total</td><td>${r.total.total}</td><td>${r.total.accepted}</td><td>${fmtRate(r.total.rate)}</td>${compRowTotal}
            </tr>
            <tr class="${be.level === 'kjd' ? 'best-row' : ''}">
              <td>${esc(r.kjd_label)}</td><td>${r.kjd.total}</td><td>${r.kjd.accepted}</td><td>${fmtRate(r.kjd.rate)}</td>${compRowKjd}
            </tr>
            <tr class="${be.level === 'urm' ? 'best-row' : ''}">
              <td>${esc(r.urm_label)}</td><td>${r.urm.total}</td><td>${r.urm.accepted}</td><td>${fmtRate(r.urm.rate)}</td>${compRowUrm}
            </tr>
            <tr class="${be.level === 'on_time' ? 'best-row' : ''}">
              <td>On-time</td><td>${r.on_time.total}</td><td>${r.on_time.accepted}</td><td>${fmtRate(r.on_time.rate)}</td>${compRowOt}
            </tr>
          </table>
        </div>
      </div>`;

    grid.appendChild(card);

    // Draw primary pie chart
    const primaryCanvas = card.querySelector(".pie-primary");
    drawPie(primaryCanvas, rate, r.verdict);

    // Draw comparison pie chart if present
    if (hasComp) {
      const compCanvas = card.querySelector(".pie-comp");
      const c = r.comparison;
      const compBe = pickBestEstimate(c.total, c.kjd, c.urm, c.on_time, r.kjd_label, r.urm_label);
      const compVerdict = verdictFromRate(compBe.rate, compBe.n);
      drawPie(compCanvas, compBe.rate, compVerdict, "#8b5cf6");
    }
  });

  // Legend
  const legend = document.getElementById("legend");
  let legendText = "";
  if (hasMedianFlag) legendText += "* = applicant is at LSAT median (treated as below-median for range)<br>";
  if (hasGpaFloorFlag) legendText += "** = applicant GPA is below the 2nd-lowest accepted GPA (range capped at floor)<br>";
  if (hasCompFlag) legendText += '<span class="comp-color">Purple chart</span> = comparison using 25th&ndash;median GPA range (what if your GPA were in the normal below-median band)<br>';
  legendText += "Pie chart shows best estimate: the most specific cascade level with N &ge; 5.<br>";
  legendText += `Cascade: Total (decided) &rarr; ${kjdLabel} &rarr; ${urmLabel} &rarr; On-time (&le; Jan 1)<br>`;
  legendText += "Percentiles: ABA First Year Class 2025. Outcomes: LSD self-reports.";
  legend.innerHTML = legendText;

  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── Best-estimate picker (reused for comparison) ────────────────────

function pickBestEstimate(total, kjd, urm, on_time, kjdLabel, urmLabel) {
  const MIN_N = 5;
  const levels = [
    { key: "on_time", label: "On-time", stats: on_time },
    { key: "urm",     label: urmLabel,   stats: urm },
    { key: "kjd",     label: kjdLabel,   stats: kjd },
    { key: "total",   label: "Total",    stats: total },
  ];
  for (const lv of levels) {
    if (lv.stats && lv.stats.total >= MIN_N && lv.stats.rate != null) {
      return { level: lv.key, label: lv.label, rate: lv.stats.rate, n: lv.stats.total };
    }
  }
  return { level: "total", label: "Total", rate: total ? total.rate : null, n: total ? total.total : 0 };
}

function verdictFromRate(rate, n) {
  if (n < 5 || rate == null) return "Low Data";
  if (rate >= 60) return "Likely";
  if (rate >= 40) return "Good Chance";
  if (rate >= 20) return "Possible";
  return "Unlikely";
}

function verdictClassFromRate(rate) {
  if (rate == null) return "verdict-low-data";
  if (rate >= 60) return "verdict-likely";
  if (rate >= 40) return "verdict-good-chance";
  if (rate >= 20) return "verdict-possible";
  return "verdict-unlikely";
}

// ── Pie chart drawing ───────────────────────────────────────────────

function drawPie(canvas, rate, verdict, colorOverride) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.min(cx, cy) - 6;

  ctx.clearRect(0, 0, w, h);

  if (rate == null) {
    // No data — grey circle with "?"
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
  const startAngle = -Math.PI / 2;  // 12 o'clock

  // Accepted slice color
  const acceptColor = colorOverride || getAcceptColor(verdict);
  const rejectColor = "#e5e7eb";

  // Reject slice
  if (pct < 1) {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle + acceptAngle, startAngle + Math.PI * 2);
    ctx.closePath();
    ctx.fillStyle = rejectColor;
    ctx.fill();
  }

  // Accept slice
  if (pct > 0) {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle, startAngle + acceptAngle);
    ctx.closePath();
    ctx.fillStyle = acceptColor;
    ctx.fill();
  }

  // Center white circle (donut hole)
  const innerRadius = radius * 0.6;
  ctx.beginPath();
  ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();

  // Percentage text in center
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

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
