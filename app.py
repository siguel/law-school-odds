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

        # ── Best estimate: most specific cascade level with N >= 5 ──
        MIN_N = 5
        kjd_label = analysis.kjd_label
        urm_label = analysis.urm_label
        # Walk from most specific (on_time) back to least (total)
        cascade_levels = [
            ("on_time", "On-time", analysis.on_time),
            ("urm",     urm_label, analysis.urm),
            ("kjd",     kjd_label, analysis.kjd),
            ("total",   "Total",   analysis.total),
        ]
        best_key = "total"
        best_label = "Total"
        best_rate = analysis.total.rate
        best_n = analysis.total.total
        for key, label, stats in cascade_levels:
            if stats.total >= MIN_N and stats.rate is not None:
                best_key = key
                best_label = label
                best_rate = stats.rate
                best_n = stats.total
                break   # most specific that qualifies

        if best_n < MIN_N or best_rate is None:
            verdict = "Low Data"
        elif best_rate >= 60:
            verdict = "Likely"
        elif best_rate >= 40:
            verdict = "Good Chance"
        elif best_rate >= 20:
            verdict = "Possible"
        else:
            verdict = "Unlikely"

        results.append({
            "school": excel_name,
            "rank": rank,
            "lsat_range": _range_dict(analysis.lsat_range),
            "gpa_range": _range_dict(analysis.gpa_range),
            "lsat_25": analysis.lsat_25,
            "lsat_50": analysis.lsat_50,
            "gpa_25": analysis.gpa_25,
            "gpa_50": analysis.gpa_50,
            "at_lsat_median": analysis.at_lsat_median,
            "below_gpa_floor": analysis.below_gpa_floor,
            "below_gpa_25": analysis.below_gpa_25,
            "total": _group_dict(analysis.total),
            "kjd": _group_dict(analysis.kjd),
            "urm": _group_dict(analysis.urm),
            "on_time": _group_dict(analysis.on_time),
            "kjd_label": kjd_label,
            "urm_label": urm_label,
            "best_estimate": {
                "level": best_key,
                "label": best_label,
                "rate": best_rate,
                "n": best_n,
            },
            "comparison": {
                "gpa_range": _range_dict(analysis.comp_gpa_range),
                "total": _group_dict(analysis.comp_total) if analysis.comp_total else None,
                "kjd": _group_dict(analysis.comp_kjd) if analysis.comp_kjd else None,
                "urm": _group_dict(analysis.comp_urm) if analysis.comp_urm else None,
                "on_time": _group_dict(analysis.comp_on_time) if analysis.comp_on_time else None,
            } if analysis.below_gpa_25 else None,
            "verdict": verdict,
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
