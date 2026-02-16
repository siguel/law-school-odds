"""Competitive range analysis engine.

Given an applicant's GPA, LSAT, URM status, and KJD status, compute
admission odds for each school by:
1. Building a "competitive range" box from official percentiles + LSD data.
2. Filtering LSD self-reported outcomes to that box.
3. Reporting acceptance rates through a 4-level cascade.

LSAT range logic:
  - Above median  -> [median, applicant]
  - At median     -> treated as below-median (flagged "at median")
  - Between 25th and median (exclusive) -> [25th, applicant]
  - Below 25th    -> find the 2nd-lowest accepted LSAT in LSD data ("floor").
                     If applicant >= floor: [applicant, 25th]
                     If applicant <  floor: [applicant, floor]

GPA range logic:
  - Above median  -> [median, applicant]
  - At or below median -> [25th, median - 0.01]
  - Below 25th    -> find the 2nd-lowest accepted GPA in LSD data ("floor").
                     If applicant >= floor: [applicant, 25th]
                     If applicant <  floor: [applicant, floor]  (flagged "below GPA floor")

Cascade (4 levels, each a strict subset of the previous):
  Total (drop pending/no-decision) -> KJD-adjusted -> URM-adjusted -> On-time
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from data_loader import SchoolPercentiles

# GPA range extends to median minus this epsilon
GPA_MEDIAN_EPS = 0.01

# Applications submitted on or before this date count as "on-time"
ONTIME_CUTOFF = pd.Timestamp("2025-01-01")


@dataclass
class Range:
    lower: float
    upper: float


@dataclass
class GroupStats:
    """Counts for one filter level."""
    total: int
    accepted: int

    @property
    def rate(self) -> Optional[float]:
        return (self.accepted / self.total * 100) if self.total > 0 else None

    def rate_str(self) -> str:
        r = self.rate
        return f"{r:.1f}%" if r is not None else "N/A"


@dataclass
class SchoolAnalysis:
    """Full analysis result for one school."""
    school_name: str
    lsat_range: Optional[Range]
    gpa_range: Optional[Range]
    lsat_25: Optional[float]
    lsat_50: Optional[float]
    gpa_25: Optional[float]
    gpa_50: Optional[float]
    at_lsat_median: bool
    below_gpa_floor: bool
    # Cascade: total -> kjd -> urm -> on_time
    total: GroupStats       # in-box, pending removed
    kjd: GroupStats         # filtered to KJD or non-KJD
    urm: GroupStats         # then filtered to URM or non-URM
    on_time: GroupStats     # then filtered to on-time apps
    kjd_label: str
    urm_label: str
    warning: Optional[str] = None


# ── LSAT range ────────────────────────────────────────────────────────

def _find_lsat_floor(lsd: pd.DataFrame) -> Optional[float]:
    """Return the 2nd-lowest LSAT among accepted applicants, or None."""
    accepted_lsats = (
        lsd.loc[lsd["result_group"] == "accepted", "lsat"]
        .dropna()
        .sort_values()
    )
    if len(accepted_lsats) >= 2:
        return float(accepted_lsats.iloc[1])
    if len(accepted_lsats) == 1:
        return float(accepted_lsats.iloc[0])
    return None


def _build_lsat_range(
    applicant_lsat: float,
    pct: SchoolPercentiles,
    lsd: pd.DataFrame,
) -> tuple[Optional[Range], bool]:
    """Build LSAT range. Returns (range, at_median_flag)."""
    if pct.lsat_25 is None or pct.lsat_50 is None:
        return None, False
    p25, median = pct.lsat_25, pct.lsat_50

    # Above median
    if applicant_lsat > median:
        return Range(median, applicant_lsat), False

    # At median -> flag it, then use below-median logic
    at_median = (applicant_lsat == median)

    # Between 25th and median (inclusive of both for at-median case)
    if applicant_lsat >= p25:
        # At-median gets [25th, median-1] (same as strictly-below-median
        # would get if applicant were median-1, but we widen to full band)
        if at_median:
            upper = median - 1
            if upper < p25:
                upper = p25
            return Range(p25, upper), True
        # Strictly between 25th and median
        return Range(p25, applicant_lsat), False

    # Below 25th -> use the 2nd-lowest accepted LSAT as floor
    floor = _find_lsat_floor(lsd)

    if floor is None:
        # No accepted data, fall back to [applicant, 25th]
        return Range(applicant_lsat, p25), False

    if applicant_lsat >= floor:
        return Range(applicant_lsat, p25), False
    else:
        return Range(applicant_lsat, floor), False


# ── GPA range ─────────────────────────────────────────────────────────

def _find_gpa_floor(lsd: pd.DataFrame) -> Optional[float]:
    """Return the 2nd-lowest GPA among accepted applicants, or None."""
    accepted_gpas = (
        lsd.loc[lsd["result_group"] == "accepted", "gpa"]
        .dropna()
        .sort_values()
    )
    if len(accepted_gpas) >= 2:
        return float(accepted_gpas.iloc[1])
    if len(accepted_gpas) == 1:
        return float(accepted_gpas.iloc[0])
    return None


def _build_gpa_range(
    applicant_gpa: float,
    pct: SchoolPercentiles,
    lsd: pd.DataFrame,
) -> tuple[Optional[Range], bool]:
    """Build GPA range. Returns (range, below_gpa_floor_flag).

    - Above median  -> [median, applicant]
    - At or below median, >= 25th -> [25th, median - eps]
    - Below 25th    -> use 2nd-lowest accepted GPA as floor.
        If applicant >= floor: [applicant, 25th]
        If applicant <  floor: [applicant, floor] (flagged)
    """
    if pct.gpa_25 is None or pct.gpa_50 is None:
        return None, False
    p25, median = pct.gpa_25, pct.gpa_50

    # Above median
    if applicant_gpa > median:
        return Range(median, applicant_gpa), False

    # At or below median but >= 25th
    if applicant_gpa >= p25:
        upper = median - GPA_MEDIAN_EPS
        if upper < p25:
            upper = p25
        return Range(p25, upper), False

    # Below 25th -> use the 2nd-lowest accepted GPA as floor
    floor = _find_gpa_floor(lsd)

    if floor is None:
        # No accepted data, fall back to [applicant, 25th]
        return Range(applicant_gpa, p25), False

    if applicant_gpa >= floor:
        return Range(applicant_gpa, p25), False
    else:
        return Range(applicant_gpa, floor), True


# ── Counting & filtering ──────────────────────────────────────────────

def _count(df: pd.DataFrame) -> GroupStats:
    n = len(df)
    accepted = int((df["result_group"] == "accepted").sum()) if n > 0 else 0
    return GroupStats(total=n, accepted=accepted)


def _filter_on_time(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = [c for c in ("sent_at", "received_at", "complete_at") if c in df.columns]
    if not date_cols:
        return df
    earliest = df[date_cols].min(axis=1)
    mask = earliest.isna() | (earliest <= ONTIME_CUTOFF)
    return df[mask]


# ── Main analysis ─────────────────────────────────────────────────────

def analyze_school(
    school_name: str,
    pct: SchoolPercentiles,
    lsd: pd.DataFrame,
    applicant_gpa: float,
    applicant_lsat: float,
    is_urm: bool,
    is_kjd: bool,
) -> SchoolAnalysis:
    """Run the full competitive range analysis for one school.

    Cascade: Total (no pending) -> KJD slice -> URM slice -> On-time
    """
    lsat_range, at_median = _build_lsat_range(applicant_lsat, pct, lsd)
    gpa_range, below_gpa_floor = _build_gpa_range(applicant_gpa, pct, lsd)
    kjd_label = "KJD" if is_kjd else "Non-KJD"
    urm_label = "URM" if is_urm else "Non-URM"

    empty = GroupStats(0, 0)

    if lsat_range is None or gpa_range is None:
        return SchoolAnalysis(
            school_name=school_name,
            lsat_range=lsat_range, gpa_range=gpa_range,
            lsat_25=pct.lsat_25, lsat_50=pct.lsat_50,
            gpa_25=pct.gpa_25, gpa_50=pct.gpa_50,
            at_lsat_median=at_median,
            below_gpa_floor=below_gpa_floor,
            total=empty, kjd=empty, urm=empty, on_time=empty,
            kjd_label=kjd_label, urm_label=urm_label,
            warning="Missing percentile data",
        )

    # Filter to competitive range box
    in_box = lsd[
        (lsd["lsat"] >= lsat_range.lower) & (lsd["lsat"] <= lsat_range.upper) &
        (lsd["gpa"] >= gpa_range.lower) & (lsd["gpa"] <= gpa_range.upper)
    ]

    # Level 1: Total — remove pending / no-decision
    decided = in_box[in_box["result_group"] != "no_decision"]
    total = _count(decided)

    # Level 2: KJD slice
    if is_kjd:
        kjd_df = decided[decided["is_kjd"]]
    else:
        kjd_df = decided[~decided["is_kjd"]]
    kjd_stats = _count(kjd_df)

    # Level 3: URM slice (within the KJD slice)
    if is_urm:
        urm_df = kjd_df[kjd_df["is_urm"]]
    else:
        urm_df = kjd_df[~kjd_df["is_urm"]]
    urm_stats = _count(urm_df)

    # Level 4: On-time (within the URM slice)
    on_time_df = _filter_on_time(urm_df)
    on_time_stats = _count(on_time_df)

    warning = None
    if total.total < 5:
        warning = f"Low sample size (n={total.total})"

    return SchoolAnalysis(
        school_name=school_name,
        lsat_range=lsat_range, gpa_range=gpa_range,
        lsat_25=pct.lsat_25, lsat_50=pct.lsat_50,
        gpa_25=pct.gpa_25, gpa_50=pct.gpa_50,
        at_lsat_median=at_median,
        below_gpa_floor=below_gpa_floor,
        total=total, kjd=kjd_stats, urm=urm_stats, on_time=on_time_stats,
        kjd_label=kjd_label, urm_label=urm_label, warning=warning,
    )
