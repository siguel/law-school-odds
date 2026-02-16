"""Flask web app for law school admission odds analysis."""

from __future__ import annotations

from flask import Flask, jsonify, request, render_template

from school_names import EXCEL_TO_LSD, SCHOOL_RANK, resolve_school
from data_loader import load_percentiles, load_lsd_data
from analyzer import analyze_school

app = Flask(__name__)

# ── Pre-load data at startup ────────────────────────────────────────
print("Loading percentile data...")
PERCENTILES = load_percentiles()
print(f"  Loaded {len(PERCENTILES)} schools from Excel.")

# ── Build school list for the frontend ──────────────────────────────

def _build_school_list() -> list[dict]:
    """Return a list of {name, slug, rank} for every school that has both
    percentile data and LSD data (i.e. is actually analyzable)."""
    schools = []
    for excel_name, slug in EXCEL_TO_LSD.items():
        if slug is None:
            continue
        if excel_name not in PERCENTILES:
            continue
        rank = SCHOOL_RANK.get(excel_name)
        schools.append({
            "name": excel_name,
            "slug": slug,
            "rank": rank,
        })
    # Sort by rank (None/unranked at bottom), then alphabetical
    schools.sort(key=lambda s: (s["rank"] or 999, s["name"]))
    return schools

SCHOOL_LIST = _build_school_list()
print(f"  {len(SCHOOL_LIST)} schools available for analysis.")


# ── Tier definitions ────────────────────────────────────────────────

def _schools_by_max_rank(max_rank: int) -> list[str]:
    """Return school names with rank <= max_rank."""
    return [s["name"] for s in SCHOOL_LIST if s["rank"] is not None and s["rank"] <= max_rank]

TIERS = {
    "t14": _schools_by_max_rank(14),
    "t20": _schools_by_max_rank(20),
    "t30": _schools_by_max_rank(30),
    "t50": _schools_by_max_rank(50),
    "all": [s["name"] for s in SCHOOL_LIST],
}


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/schools")
def api_schools():
    """Return full school list for the frontend."""
    return jsonify(SCHOOL_LIST)


@app.route("/api/tiers/<tier>")
def api_tier(tier):
    """Return school names for a tier (t14, t20, t30, t50, all)."""
    names = TIERS.get(tier)
    if names is None:
        return jsonify({"error": f"Unknown tier: {tier}"}), 400
    return jsonify(names)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Run analysis for one applicant.

    Expects JSON:
      {
        "gpa": 3.5,
        "lsat": 165,
        "is_urm": false,
        "is_kjd": true,
        "schools": ["Harvard University", "Yale University"]
      }
    """
    data = request.get_json(force=True)
    try:
        gpa = float(data["gpa"])
        lsat = float(data["lsat"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "gpa and lsat are required numbers"}), 400

    is_urm = bool(data.get("is_urm", False))
    is_kjd = bool(data.get("is_kjd", False))
    school_names = data.get("schools", [])

    if not school_names:
        return jsonify({"error": "At least one school is required"}), 400

    def _range_dict(r):
        if r is None:
            return None
        return {"lower": r.lower, "upper": r.upper}

    def _group_dict(g):
        return {"total": g.total, "accepted": g.accepted, "rate": g.rate}

    def _range_str(r, is_lsat):
        if r is None:
            return "N/A"
        if is_lsat:
            return f"{r.lower:.0f}–{r.upper:.0f}"
        return f"{r.lower:.2f}–{r.upper:.2f}"

    results = []
    for name in school_names:
        # Resolve the name
        resolved = resolve_school(name)
        if resolved is None:
            results.append({"school": name, "error": f"Could not find school: {name}"})
            continue
        excel_name, slug = resolved
        if slug is None:
            results.append({"school": excel_name, "error": "No LSD data available"})
            continue

        pct = PERCENTILES.get(excel_name)
        if pct is None:
            results.append({"school": excel_name, "error": "No percentile data"})
            continue

        lsd = load_lsd_data(slug)
        if lsd is None:
            results.append({"school": excel_name, "error": "No LSD data file"})
            continue

        analysis = analyze_school(
            school_name=excel_name, pct=pct, lsd=lsd,
            applicant_gpa=gpa, applicant_lsat=lsat,
            is_urm=is_urm, is_kjd=is_kjd,
        )

        rank = SCHOOL_RANK.get(excel_name)
        kjd_label = analysis.kjd_label
        urm_label = analysis.urm_label

        # ── Build scenarios ──────────────────────────────────────
        # Each scenario: {label, lsat_range, gpa_range, total, kjd,
        #   urm, on_time, best_estimate, verdict, color_key}

        scenarios = []

        def _best_estimate(a):
            """Pick best cascade level with N >= 10."""
            MIN_N = 10
            levels = [
                ("on_time", "On-time", a.on_time),
                ("urm",     urm_label, a.urm),
                ("kjd",     kjd_label, a.kjd),
                ("total",   "Total",   a.total),
            ]
            bk, bl, br, bn = "total", "Total", a.total.rate, a.total.total
            for key, label, stats in levels:
                if stats.total >= MIN_N and stats.rate is not None:
                    bk, bl, br, bn = key, label, stats.rate, stats.total
                    break
            return {"level": bk, "label": bl, "rate": br, "n": bn}

        def _verdict(be):
            if be["n"] < 10 or be["rate"] is None:
                return "Low Data"
            if be["rate"] >= 60: return "Likely"
            if be["rate"] >= 40: return "Good Chance"
            if be["rate"] >= 20: return "Possible"
            return "Unlikely"

        def _scenario_dict(label, a, color_key, desc):
            be = _best_estimate(a)
            return {
                "label": label,
                "description": desc,
                "color_key": color_key,
                "lsat_range": _range_dict(a.lsat_range),
                "gpa_range": _range_dict(a.gpa_range),
                "total": _group_dict(a.total),
                "kjd": _group_dict(a.kjd),
                "urm": _group_dict(a.urm),
                "on_time": _group_dict(a.on_time),
                "best_estimate": be,
                "verdict": _verdict(be),
            }

        # Determine which extra scenarios apply
        lsat_below_median = (
            pct.lsat_50 is not None and lsat <= pct.lsat_50
        )
        gpa_below_25 = analysis.below_gpa_25  # below 25th but above floor

        # Scenario 1: Base model (always present)
        base_label = "Base"
        if analysis.at_lsat_median:
            base_label = "At Median LSAT"
        elif lsat_below_median:
            base_label = "Below Median LSAT"
        scenarios.append(_scenario_dict(
            base_label, analysis, "base",
            f"LSAT {_range_str(analysis.lsat_range, True)}, GPA {_range_str(analysis.gpa_range, False)}"
        ))

        # Scenario 2: At-Median LSAT (only if strictly below median,
        # to show what "at median" would look like)
        if lsat_below_median and not analysis.at_lsat_median and pct.lsat_50 is not None:
            at_med_analysis = analyze_school(
                school_name=excel_name, pct=pct, lsd=lsd,
                applicant_gpa=gpa, applicant_lsat=pct.lsat_50,
                is_urm=is_urm, is_kjd=is_kjd,
            )
            scenarios.append(_scenario_dict(
                "At Median LSAT", at_med_analysis, "at_median",
                f"LSAT {_range_str(at_med_analysis.lsat_range, True)}, GPA {_range_str(at_med_analysis.gpa_range, False)}"
            ))

        # Scenario 3: Median+1 LSAT (if at or below median)
        if lsat_below_median and pct.lsat_50 is not None:
            med1_analysis = analyze_school(
                school_name=excel_name, pct=pct, lsd=lsd,
                applicant_gpa=gpa, applicant_lsat=pct.lsat_50 + 1,
                is_urm=is_urm, is_kjd=is_kjd,
            )
            scenarios.append(_scenario_dict(
                "Median+1 LSAT", med1_analysis, "median_plus",
                f"LSAT {_range_str(med1_analysis.lsat_range, True)}, GPA {_range_str(med1_analysis.gpa_range, False)}"
            ))

        # Scenario 4: 25th–Med GPA (only if below 25th GPA)
        if gpa_below_25 and pct.gpa_25 is not None:
            gpa_comp_analysis = analyze_school(
                school_name=excel_name, pct=pct, lsd=lsd,
                applicant_gpa=pct.gpa_25, applicant_lsat=lsat,
                is_urm=is_urm, is_kjd=is_kjd,
            )
            scenarios.append(_scenario_dict(
                "25th–Med GPA", gpa_comp_analysis, "gpa_comp",
                f"LSAT {_range_str(gpa_comp_analysis.lsat_range, True)}, GPA {_range_str(gpa_comp_analysis.gpa_range, False)}"
            ))

        # Scenario 5: Median+1 LSAT + 25th–Med GPA (both upgrades)
        if (lsat_below_median and gpa_below_25
                and pct.lsat_50 is not None and pct.gpa_25 is not None):
            both_analysis = analyze_school(
                school_name=excel_name, pct=pct, lsd=lsd,
                applicant_gpa=pct.gpa_25, applicant_lsat=pct.lsat_50 + 1,
                is_urm=is_urm, is_kjd=is_kjd,
            )
            scenarios.append(_scenario_dict(
                "Med+1 + 25th GPA", both_analysis, "both_upgrade",
                f"LSAT {_range_str(both_analysis.lsat_range, True)}, GPA {_range_str(both_analysis.gpa_range, False)}"
            ))

        # Sort scenarios by best_estimate rate (low to high)
        scenarios.sort(key=lambda s: s["best_estimate"]["rate"] if s["best_estimate"]["rate"] is not None else -1)

        results.append({
            "school": excel_name,
            "rank": rank,
            "lsat_25": analysis.lsat_25,
            "lsat_50": analysis.lsat_50,
            "gpa_25": analysis.gpa_25,
            "gpa_50": analysis.gpa_50,
            "at_lsat_median": analysis.at_lsat_median,
            "below_gpa_floor": analysis.below_gpa_floor,
            "below_gpa_25": analysis.below_gpa_25,
            "kjd_label": kjd_label,
            "urm_label": urm_label,
            "scenarios": scenarios,
            "warning": analysis.warning,
        })

    return jsonify({
        "applicant": {
            "gpa": gpa,
            "lsat": lsat,
            "is_urm": is_urm,
            "is_kjd": is_kjd,
        },
        "results": results,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
