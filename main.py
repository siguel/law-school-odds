"""CLI entry point for law school admission odds analysis.

Usage:
    # Single applicant
    python main.py --gpa 3.40 --lsat 159 --schools "Georgetown" "Emory"

    # With URM and KJD status
    python main.py --gpa 3.40 --lsat 159 --urm --kjd --schools "Georgetown"

    # Batch from CSV
    python main.py --csv applicants.csv

    # Save markdown report
    python main.py --gpa 3.40 --lsat 159 --schools "Yale" --output report.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from school_names import resolve_school, SCHOOL_RANK
from data_loader import load_percentiles, load_lsd_data
from analyzer import analyze_school, SchoolAnalysis, Range


@dataclass
class Applicant:
    name: Optional[str]
    gpa: float
    lsat: float
    is_urm: bool
    is_kjd: bool
    schools: list[str]


# ── Output formatting ────────────────────────────────────────────────

def _range_str(r: Optional[Range], is_lsat: bool) -> str:
    if r is None:
        return "N/A"
    fmt = "{:.0f}" if is_lsat else "{:.2f}"
    return f"{fmt.format(r.lower)}-{fmt.format(r.upper)}"


def _pct_str(val: Optional[float], is_lsat: bool) -> str:
    if val is None:
        return "N/A"
    return f"{val:.0f}" if is_lsat else f"{val:.2f}"


def _assessment(analysis: SchoolAnalysis) -> str:
    """Quick verdict based on total (decided) acceptance rate."""
    rate = analysis.total.rate
    n = analysis.total.total
    if n < 5 or rate is None:
        return "? Low data"
    if rate >= 60:
        return "LIKELY"
    if rate >= 40:
        return "GOOD CHANCE"
    if rate >= 20:
        return "POSSIBLE"
    return "UNLIKELY"


def _median_flag(r: SchoolAnalysis) -> str:
    return " *" if r.at_lsat_median else ""


def _gpa_floor_flag(r: SchoolAnalysis) -> str:
    return " **" if r.below_gpa_floor else ""


def _rank_str(school_name: str) -> str:
    rank = SCHOOL_RANK.get(school_name)
    return f"#{rank}" if rank else "NR"


def print_results(applicant: Applicant, results: list[SchoolAnalysis]) -> None:
    label = f" ({applicant.name})" if applicant.name else ""
    kjd = "KJD" if applicant.is_kjd else "Non-KJD"
    urm = "URM" if applicant.is_urm else "Non-URM"
    print(f"\nApplicant{label}: GPA {applicant.gpa:.2f} / LSAT {applicant.lsat:.0f} / {kjd} / {urm}")
    print("=" * 170)

    if not results:
        print("No schools could be analyzed.")
        return

    # Column headers using actual labels
    k = results[0].kjd_label
    u = results[0].urm_label

    header = (
        f"{'Rank':>5} {'School':<42} {'LSAT Rng':>9} {'GPA Rng':>11} "
        f"{'MedL':>5} {'MedG':>5} "
        f"{'Tot':>5} {'A':>4} {'%':>7} "
        f"{'|':>1} {k:>7} {'A':>4} {'%':>7} "
        f"{'|':>1} {u:>7} {'A':>4} {'%':>7} "
        f"{'|':>1} {'OnTm':>5} {'A':>4} {'%':>7} "
        f"{'Verdict':>12}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        rank = _rank_str(r.school_name)
        if r.warning and r.total.total == 0:
            print(f"{rank:>5} {r.school_name:<42} {r.warning}")
            continue
        mflag = _median_flag(r)
        gflag = _gpa_floor_flag(r)
        print(
            f"{rank:>5} {r.school_name:<42} "
            f"{_range_str(r.lsat_range, True):>9}{mflag:2s}"
            f"{_range_str(r.gpa_range, False):>11}{gflag:3s}"
            f"{_pct_str(r.lsat_50, True):>5} "
            f"{_pct_str(r.gpa_50, False):>5} "
            f"{r.total.total:>5} {r.total.accepted:>4} {r.total.rate_str():>7} "
            f"{'|':>1} {r.kjd.total:>7} {r.kjd.accepted:>4} {r.kjd.rate_str():>7} "
            f"{'|':>1} {r.urm.total:>7} {r.urm.accepted:>4} {r.urm.rate_str():>7} "
            f"{'|':>1} {r.on_time.total:>5} {r.on_time.accepted:>4} {r.on_time.rate_str():>7} "
            f"{_assessment(r):>12}"
        )

    # Legend
    has_median_flag = any(r.at_lsat_median for r in results)
    has_gpa_floor_flag = any(r.below_gpa_floor for r in results)
    if has_median_flag:
        print("\n  * = applicant is at LSAT median (treated as below-median for range)")
    if has_gpa_floor_flag:
        print(" ** = applicant GPA is below the 2nd-lowest accepted GPA (range capped at floor)")
    print(f"\nCascade: Total (decided) > {results[0].kjd_label} > {results[0].urm_label} > On-time (<= Jan 1)")


def render_markdown(applicant: Applicant, results: list[SchoolAnalysis]) -> str:
    k = results[0].kjd_label if results else ("KJD" if applicant.is_kjd else "Non-KJD")
    u = results[0].urm_label if results else ("URM" if applicant.is_urm else "Non-URM")
    label = f" ({applicant.name})" if applicant.name else ""
    lines = [
        f"Applicant{label}: GPA {applicant.gpa:.2f} / LSAT {applicant.lsat:.0f} / {k} / {u}",
        "",
        f"| Rank | School | LSAT Range | GPA Range | Med LSAT | Med GPA "
        f"| Total | Adm | % "
        f"| {k} | Adm | % "
        f"| {u} | Adm | % "
        f"| On-time | Adm | % "
        f"| Verdict |",
        "| --- " * 19 + "|",
    ]
    for r in results:
        mflag = " \\*" if r.at_lsat_median else ""
        gflag = " \\*\\*" if r.below_gpa_floor else ""
        verdict = _assessment(r)
        rank = _rank_str(r.school_name)
        lines.append(
            f"| {rank} "
            f"| {r.school_name} "
            f"| {_range_str(r.lsat_range, True)}{mflag} "
            f"| {_range_str(r.gpa_range, False)}{gflag} "
            f"| {_pct_str(r.lsat_50, True)} "
            f"| {_pct_str(r.gpa_50, False)} "
            f"| {r.total.total} | {r.total.accepted} | {r.total.rate_str()} "
            f"| {r.kjd.total} | {r.kjd.accepted} | {r.kjd.rate_str()} "
            f"| {r.urm.total} | {r.urm.accepted} | {r.urm.rate_str()} "
            f"| {r.on_time.total} | {r.on_time.accepted} | {r.on_time.rate_str()} "
            f"| {verdict} |"
        )
    lines.append("")
    has_median = any(r.at_lsat_median for r in results)
    has_gpa_floor = any(r.below_gpa_floor for r in results)
    if has_median:
        lines.append("\\* = applicant at LSAT median, treated as below-median for range.")
    if has_gpa_floor:
        lines.append("\\*\\* = applicant GPA below the 2nd-lowest accepted GPA; range capped at floor.")
    lines.append(
        f"Cascade: Total (decided) > {k} > {u} > On-time (<= Jan 1)."
    )
    lines.append("Percentiles: ABA First Year Class 2025.  Outcomes: LSD self-reports.")
    return "\n".join(lines)


# ── CSV batch loading ────────────────────────────────────────────────

def _parse_bool(value: Optional[str], true_vals: tuple) -> bool:
    if not value:
        return False
    return value.strip().lower() in true_vals


def _find_field(row: dict, *candidates: str) -> Optional[str]:
    for key in row:
        if key and key.strip().lower() in candidates:
            return row[key]
    return None


def load_applicants_csv(path: Path) -> list[Applicant]:
    applicants = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=2):
            name = _find_field(row, "username", "name") or f"Row {idx}"
            lsat_raw = _find_field(row, "lsat")
            gpa_raw = _find_field(row, "gpa")
            urm_raw = _find_field(row, "urm status", "urm")
            kjd_raw = _find_field(row, "kjd status", "kjd")
            try:
                lsat = float(lsat_raw)
                gpa = float(gpa_raw)
            except (TypeError, ValueError):
                print(f"  [warn] Skipping {name}: can't parse GPA/LSAT")
                continue

            schools = []
            for key, val in row.items():
                if key and key.strip().lower().startswith("school") and val and val.strip():
                    schools.append(val.strip())

            if not schools:
                print(f"  [warn] Skipping {name}: no schools listed")
                continue

            applicants.append(Applicant(
                name=name, gpa=gpa, lsat=lsat,
                is_urm=_parse_bool(urm_raw, ("urm", "y", "yes", "true")),
                is_kjd=_parse_bool(kjd_raw, ("kjd", "y", "yes", "true")),
                schools=schools,
            ))
    return applicants


# ── Main pipeline ────────────────────────────────────────────────────

def resolve_schools(raw_names: list[str]) -> list[tuple[str, str]]:
    """Resolve user-typed school names to (excel_name, lsd_slug) pairs."""
    resolved = []
    for name in raw_names:
        result = resolve_school(name)
        if result is None:
            print(f"  [warn] Could not find school: {name}")
            continue
        excel_name, slug = result
        if slug is None:
            print(f"  [warn] {excel_name} has no LSD data")
            continue
        resolved.append((excel_name, slug))
    return resolved


def run_applicant(applicant: Applicant, percentiles, output_md: Optional[Path] = None) -> None:
    schools = resolve_schools(applicant.schools)
    results = []

    for excel_name, slug in schools:
        pct = percentiles.get(excel_name)
        if pct is None:
            print(f"  [warn] No percentile data for {excel_name}")
            continue
        lsd = load_lsd_data(slug)
        if lsd is None:
            print(f"  [warn] No LSD data file for {slug}")
            continue
        analysis = analyze_school(
            school_name=excel_name, pct=pct, lsd=lsd,
            applicant_gpa=applicant.gpa, applicant_lsat=applicant.lsat,
            is_urm=applicant.is_urm, is_kjd=applicant.is_kjd,
        )
        results.append(analysis)

    print_results(applicant, results)

    if output_md and results:
        md = render_markdown(applicant, results)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(md, encoding="utf-8")
        print(f"\nMarkdown saved to {output_md}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Estimate law school admission odds.",
    )
    p.add_argument("--gpa", type=float, help="Applicant GPA")
    p.add_argument("--lsat", type=float, help="Applicant LSAT score")
    p.add_argument("--urm", action="store_true", help="Applicant is URM")
    p.add_argument("--kjd", action="store_true", help="Applicant is KJD (no work experience)")
    p.add_argument("--schools", nargs="+", help="School names to analyze")
    p.add_argument("--csv", type=Path, help="CSV file with multiple applicants")
    p.add_argument("--output", type=Path, help="Save markdown report to this path")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print("Loading percentile data...")
    percentiles = load_percentiles()

    if args.csv:
        applicants = load_applicants_csv(args.csv)
        if not applicants:
            print("No valid applicants found in CSV.")
            sys.exit(1)
        for applicant in applicants:
            run_applicant(applicant, percentiles, args.output)
        return

    if args.gpa is None or args.lsat is None or not args.schools:
        parser.error("Provide --gpa, --lsat, and --schools (or use --csv)")

    applicant = Applicant(
        name=None, gpa=args.gpa, lsat=args.lsat,
        is_urm=args.urm, is_kjd=args.kjd, schools=args.schools,
    )
    run_applicant(applicant, percentiles, args.output)


if __name__ == "__main__":
    main()
