"""Load school percentile data from the First Year Class Excel file
and applicant outcome data from LSD CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from school_names import EXCEL_TO_LSD

ROOT = Path(__file__).resolve().parent
EXCEL_PATH = ROOT / "First_Year_Class_2025(2).xlsx"
LSD_DIR = ROOT / "lsd_tables_all"


@dataclass
class SchoolPercentiles:
    """Official 25th / 50th / 75th percentile GPA and LSAT for a school."""
    name: str
    gpa_25: Optional[float]
    gpa_50: Optional[float]
    gpa_75: Optional[float]
    lsat_25: Optional[float]
    lsat_50: Optional[float]
    lsat_75: Optional[float]


def _safe_float(value) -> Optional[float]:
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def load_percentiles(path: Path = EXCEL_PATH) -> dict[str, SchoolPercentiles]:
    """Load percentile data from the First Year Class Excel file.

    Returns a dict keyed by Excel SchoolName.
    """
    df = pd.read_excel(path, sheet_name=0, header=0)
    results = {}
    for _, row in df.iterrows():
        name = row.get("SchoolName")
        if pd.isna(name):
            continue
        results[name] = SchoolPercentiles(
            name=name,
            gpa_25=_safe_float(row.get("All25thPercentileUGPA")),
            gpa_50=_safe_float(row.get("All50thPercentileUGPA")),
            gpa_75=_safe_float(row.get("All75thPercentileUGPA")),
            lsat_25=_safe_float(row.get("All25thPercentileLSAT")),
            lsat_50=_safe_float(row.get("All50thPercentileLSAT")),
            lsat_75=_safe_float(row.get("All75thPercentileLSAT")),
        )
    return results


def _classify_result(value: str) -> str:
    """Normalize LSD result strings into standard categories."""
    if not isinstance(value, str):
        return "unknown"
    v = value.strip().lower()
    if v in ("accepted", "wl, accepted", "wl_accepted", "accepted_withdrawn",
             "hold_accepted"):
        return "accepted"
    if v in ("rejected", "wl, rejected", "wl_rejected", "hold_rejected"):
        return "rejected"
    if v in ("waitlisted", "wl", "wl, withdrawn", "wl_withdrawn", "hold_wl"):
        return "waitlisted"
    if v in ("hold", "hold_withdrawn"):
        return "hold"
    if v in ("pending", "withdrawn"):
        return "no_decision"
    return "no_decision"


def load_lsd_data(slug: str, lsd_dir: Path = LSD_DIR) -> Optional[pd.DataFrame]:
    """Load and clean one school's LSD applicant CSV.

    Returns a DataFrame with columns: gpa, lsat, is_urm, result_group,
    sent_at, received_at, complete_at.  Rows missing both gpa and lsat
    are dropped.  Returns None if the file doesn't exist.
    """
    csv_path = lsd_dir / f"{slug}.csv"
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path)
    df["lsat"] = pd.to_numeric(df.get("lsat"), errors="coerce")
    df["gpa"] = pd.to_numeric(df.get("gpa"), errors="coerce")
    df = df.dropna(subset=["lsat", "gpa"], how="any")
    df["result_group"] = df["result"].apply(_classify_result)
    df["is_urm"] = df["is_urm"].fillna(False).astype(bool)

    # KJD = "Kindergarten through JD" = 0 years work experience
    if "work_experience" in df.columns:
        df["is_kjd"] = pd.to_numeric(df["work_experience"], errors="coerce") == 0
    elif "work_experience_label" in df.columns:
        df["is_kjd"] = df["work_experience_label"].str.contains("KJD", case=False, na=False)
    else:
        df["is_kjd"] = False

    for col in ("sent_at", "received_at", "complete_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def load_school(excel_name: str,
                percentiles: dict[str, SchoolPercentiles],
                lsd_dir: Path = LSD_DIR,
                ) -> tuple[Optional[SchoolPercentiles], Optional[pd.DataFrame]]:
    """Convenience: load both percentiles and LSD data for one school.

    Returns (percentiles, lsd_dataframe).  Either may be None.
    """
    pct = percentiles.get(excel_name)
    slug = EXCEL_TO_LSD.get(excel_name)
    lsd = load_lsd_data(slug, lsd_dir) if slug else None
    return pct, lsd
