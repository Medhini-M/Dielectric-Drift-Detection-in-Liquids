"""
Phase 0 dataset loader / adapter.

Reads the two authoritative Phase 0 CSV files and turns them into normalized,
typed Python objects that the rest of the application (SQLite layer, API,
demo generator) can consume without ever touching CSV parsing directly.

    phase0_measurements.csv  ---\
                                  >---  load_dataset()  --->  list[Measurement]
    phase0_sweep_traces.csv  ---/                              (sweep trace attached
                                                                 to the ~24 rows that
                                                                 have one)

Design notes
------------
- This module has ONE job: CSV -> validated, normalized Python objects.
  It does not touch SQLite and does not decide DEMO-mode pacing; those are
  steps 4 and 5 in the integration plan and live in database/ and
  simulator/ respectively.
- `_gt_*` columns are ground-truth/answer-key columns (see
  README_phase0_dataset.md: "Drop the _gt_* columns before any analysis you
  intend to report"). They are parsed into `Measurement.ground_truth` for
  optional offline validation of the analysis code, but are deliberately
  EXCLUDED from `to_app_record()` so they can never leak into the database
  or the API response.
- `drift_label` (none / subtle / gross) is a regular dataset column, not a
  `_gt_*` column, so it is legitimate to use for scenario mapping. It maps
  directly to three of the four dashboard states:
      none   -> NORMAL
      subtle -> DEGRADED
      gross  -> SUBSTITUTED
  The dataset has no explicit INSUFFICIENT EVIDENCE label (ref_n is always
  3 in Phase 0 - no row represents a quorum failure). Per
  README_phase0_dataset.md's own finding, "none" and "subtle" residual_norm
  distributions overlap almost completely (medians 0.80 vs 0.78), which is
  precisely the situation the architecture's arbitration stage is meant to
  abstain on rather than guess. `condition_label`/`validity_bit` in
  `to_app_record()` are therefore left as a documented placeholder here
  (drift_label mapped 1:1, no ambiguity band applied yet) - the actual
  abstain-on-ambiguity rule is arbitration logic and belongs in step 5/6
  (demo generator / scenario logic), not in the CSV loader.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MEASUREMENTS_CSV = os.path.join(BASE_DIR, "..", "data", "phase0", "phase0_measurements.csv")
DEFAULT_SWEEP_CSV = os.path.join(BASE_DIR, "..", "data", "phase0", "phase0_sweep_traces.csv")

# Columns that must be present in phase0_measurements.csv, excluding the
# _gt_* answer-key columns (validated separately).
REQUIRED_MEASUREMENT_COLUMNS = [
    "measurement_id", "timestamp_utc", "session_id", "is_enrollment", "item_id",
    "container_type", "formulation", "nominal_content", "state",
    "substitute_content", "drift_label", "antenna", "placement_index",
    "temperature_C", "humidity_pct", "s_parameter", "f_start_MHz", "f_stop_MHz",
    "f_step_MHz", "n_points", "f0_MHz", "mag_peak_dB", "phase_at_f0_deg",
    "bw_3dB_MHz", "Q_factor", "eps_real_true", "loss_tangent_true",
    "eps_real_estimated", "ref_f0_MHz", "ref_bw_MHz", "ref_Q", "ref_mag_dB",
    "ref_eps", "ref_n", "ref_sd_MHz", "delta_f0_MHz", "delta_bw_MHz",
    "delta_Q", "delta_mag_dB", "delta_eps_real", "residual_norm",
]

GT_COLUMNS = [
    "_gt_b_item_MHz", "_gt_placement_MHz", "_gt_placement_repeatable_MHz",
    "_gt_state_shift_MHz", "_gt_noise_MHz",
]

REQUIRED_SWEEP_COLUMNS = [
    "measurement_id", "item_id", "state", "antenna", "placement_index",
    "frequency_MHz", "magnitude_dB", "phase_deg",
]

VALID_DRIFT_LABELS = {"none", "subtle", "gross"}

# Full descriptive antenna string (as it appears in the CSV) -> short code.
# Falls back to deriving the leading token rather than fabricating a value
# if a future dataset revision adds a new antenna we haven't seen.
ANTENNA_CODE_MAP = {
    "ANT-A (double-ridged horn, ETS 3115)": "ANT-A",
    "ANT-B (directional dipole)": "ANT-B",
}


class DatasetValidationError(Exception):
    """Raised when a CSV file is missing required columns or is structurally invalid."""


def _antenna_code(raw: str) -> str:
    if raw in ANTENNA_CODE_MAP:
        return ANTENNA_CODE_MAP[raw]
    return raw.split(" ")[0] if raw else raw


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _parse_optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    return v if v not in ("", "nan", "NaN", "NA") else None


def _parse_float(value: Optional[str]) -> Optional[float]:
    v = _parse_optional_str(value)
    return float(v) if v is not None else None


def _parse_int(value: Optional[str]) -> Optional[int]:
    v = _parse_optional_str(value)
    return int(float(v)) if v is not None else None


def _parse_timestamp(value: str) -> datetime:
    # phase0_measurements.csv uses "YYYY-MM-DD HH:MM:SS" UTC (no offset).
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


@dataclass
class SweepPoint:
    frequency_MHz: float
    magnitude_dB: float
    phase_deg: float


@dataclass
class Measurement:
    # --- identification ---
    measurement_id: str
    timestamp_utc: datetime
    session_id: str
    is_enrollment: bool
    item_id: str
    container_type: str
    formulation: str
    nominal_content: str
    state: str
    substitute_content: Optional[str]
    drift_label: str  # none | subtle | gross

    # --- geometry / environment ---
    antenna: str          # full descriptive string, as in the CSV
    antenna_code: str      # derived short code (ANT-A / ANT-B)
    placement_index: int
    temperature_C: float
    humidity_pct: float

    # --- sweep configuration ---
    s_parameter: str
    f_start_MHz: float
    f_stop_MHz: float
    f_step_MHz: float
    n_points: int

    # --- extracted resonance scalars ---
    f0_MHz: float
    mag_peak_dB: float
    phase_at_f0_deg: float
    bw_3dB_MHz: float
    Q_factor: float
    eps_real_true: Optional[float]
    loss_tangent_true: Optional[float]
    eps_real_estimated: float

    # --- this item's enrolled baseline ---
    ref_f0_MHz: float
    ref_bw_MHz: float
    ref_Q: float
    ref_mag_dB: float
    ref_eps: float
    ref_n: int
    ref_sd_MHz: float

    # --- drift vs. baseline ---
    delta_f0_MHz: float
    delta_bw_MHz: float
    delta_Q: float
    delta_mag_dB: float
    delta_eps_real: float
    residual_norm: float

    # --- ground truth (never written to DB / returned by the API) ---
    ground_truth: Dict[str, Optional[float]] = field(default_factory=dict)

    # --- attached full sweep, only present for the 24 measurements that have one ---
    sweep_trace: Optional[List[SweepPoint]] = None

    @property
    def has_sweep_trace(self) -> bool:
        return self.sweep_trace is not None

    def to_app_record(self, mode: str = "DEMO") -> dict:
        """
        Normalized dict for the ingestion pipeline. Keys prefixed with a
        comment below map 1:1 onto the CURRENT sensor_records columns;
        the remaining keys are new fields that step 4's schema migration
        will add. condition_label / validity_bit are intentionally NOT
        included here - see module docstring; they are computed by the
        step 5/6 arbitration logic, which receives this dict as input.
        """
        return {
            # --- existing sensor_records columns ---
            "timestamp": self.timestamp_utc.isoformat() + "Z",
            "container_id": self.item_id,
            "antenna": self.antenna_code,
            "frequency": self.f0_MHz,
            "amplitude_db": self.mag_peak_dB,
            "phase_deg": self.phase_at_f0_deg,
            "residual": self.residual_norm,
            "temp_ambient_c": self.temperature_C,
            "mode": mode,
            # --- new fields (added to schema in step 4) ---
            "measurement_id": self.measurement_id,
            "session_id": self.session_id,
            "item_id": self.item_id,
            "container_type": self.container_type,
            "formulation": self.formulation,
            "nominal_content": self.nominal_content,
            "state": self.state,
            "substitute_content": self.substitute_content,
            "drift_label": self.drift_label,
            "is_enrollment": self.is_enrollment,
            "placement_index": self.placement_index,
            "humidity_pct": self.humidity_pct,
            "bw_3dB_MHz": self.bw_3dB_MHz,
            "Q_factor": self.Q_factor,
            "eps_real_estimated": self.eps_real_estimated,
            "ref_sd_MHz": self.ref_sd_MHz,
            "delta_f0_MHz": self.delta_f0_MHz,
        }


@dataclass
class ValidationReport:
    n_measurement_rows: int = 0
    n_sweep_rows: int = 0
    n_measurements_with_sweep: int = 0
    duplicate_measurement_ids: List[str] = field(default_factory=list)
    missing_value_counts: Dict[str, int] = field(default_factory=dict)
    unknown_drift_labels: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not (self.duplicate_measurement_ids or self.unknown_drift_labels)


def _validate_header(fieldnames: List[str], required: List[str], source: str) -> None:
    missing = [c for c in required if c not in fieldnames]
    if missing:
        raise DatasetValidationError(
            f"{source}: missing required column(s): {missing}. "
            f"Refusing to load with an unverified structure."
        )


def load_sweep_traces(path: str = DEFAULT_SWEEP_CSV) -> Dict[str, List[SweepPoint]]:
    """Group phase0_sweep_traces.csv by measurement_id, points sorted by frequency."""
    if not os.path.exists(path):
        raise DatasetValidationError(f"Sweep trace CSV not found: {path}")

    by_measurement: Dict[str, List[SweepPoint]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _validate_header(reader.fieldnames or [], REQUIRED_SWEEP_COLUMNS, path)
        for row in reader:
            mid = row["measurement_id"]
            point = SweepPoint(
                frequency_MHz=_parse_float(row["frequency_MHz"]),
                magnitude_dB=_parse_float(row["magnitude_dB"]),
                phase_deg=_parse_float(row["phase_deg"]),
            )
            by_measurement.setdefault(mid, []).append(point)

    for mid, points in by_measurement.items():
        points.sort(key=lambda p: p.frequency_MHz)

    return by_measurement


def load_measurements(
    path: str = DEFAULT_MEASUREMENTS_CSV,
    sweep_by_measurement: Optional[Dict[str, List[SweepPoint]]] = None,
) -> tuple[List[Measurement], ValidationReport]:
    """Load phase0_measurements.csv into validated Measurement objects."""
    if not os.path.exists(path):
        raise DatasetValidationError(f"Measurements CSV not found: {path}")

    report = ValidationReport()
    sweep_by_measurement = sweep_by_measurement or {}
    seen_ids = set()
    measurements: List[Measurement] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        _validate_header(fieldnames, REQUIRED_MEASUREMENT_COLUMNS, path)
        has_gt = all(c in fieldnames for c in GT_COLUMNS)
        if not has_gt:
            report.warnings.append(
                "_gt_* ground-truth columns not found - ground_truth will be empty on all rows."
            )

        for row in reader:
            report.n_measurement_rows += 1

            mid = row["measurement_id"]
            if mid in seen_ids:
                report.duplicate_measurement_ids.append(mid)
                continue
            seen_ids.add(mid)

            for col in REQUIRED_MEASUREMENT_COLUMNS:
                if _parse_optional_str(row.get(col)) is None and col not in (
                    "substitute_content",
                ):
                    report.missing_value_counts[col] = report.missing_value_counts.get(col, 0) + 1

            drift_label = row["drift_label"].strip()
            if drift_label not in VALID_DRIFT_LABELS:
                report.unknown_drift_labels.append(f"{mid}:{drift_label}")

            antenna_raw = row["antenna"].strip()
            ground_truth = (
                {col: _parse_float(row.get(col)) for col in GT_COLUMNS} if has_gt else {}
            )

            m = Measurement(
                measurement_id=mid,
                timestamp_utc=_parse_timestamp(row["timestamp_utc"]),
                session_id=row["session_id"].strip(),
                is_enrollment=_parse_bool(row["is_enrollment"]),
                item_id=row["item_id"].strip(),
                container_type=row["container_type"].strip(),
                formulation=row["formulation"].strip(),
                nominal_content=row["nominal_content"].strip(),
                state=row["state"].strip(),
                substitute_content=_parse_optional_str(row.get("substitute_content")),
                drift_label=drift_label,
                antenna=antenna_raw,
                antenna_code=_antenna_code(antenna_raw),
                placement_index=_parse_int(row["placement_index"]),
                temperature_C=_parse_float(row["temperature_C"]),
                humidity_pct=_parse_float(row["humidity_pct"]),
                s_parameter=row["s_parameter"].strip(),
                f_start_MHz=_parse_float(row["f_start_MHz"]),
                f_stop_MHz=_parse_float(row["f_stop_MHz"]),
                f_step_MHz=_parse_float(row["f_step_MHz"]),
                n_points=_parse_int(row["n_points"]),
                f0_MHz=_parse_float(row["f0_MHz"]),
                mag_peak_dB=_parse_float(row["mag_peak_dB"]),
                phase_at_f0_deg=_parse_float(row["phase_at_f0_deg"]),
                bw_3dB_MHz=_parse_float(row["bw_3dB_MHz"]),
                Q_factor=_parse_float(row["Q_factor"]),
                eps_real_true=_parse_float(row.get("eps_real_true")),
                loss_tangent_true=_parse_float(row.get("loss_tangent_true")),
                eps_real_estimated=_parse_float(row["eps_real_estimated"]),
                ref_f0_MHz=_parse_float(row["ref_f0_MHz"]),
                ref_bw_MHz=_parse_float(row["ref_bw_MHz"]),
                ref_Q=_parse_float(row["ref_Q"]),
                ref_mag_dB=_parse_float(row["ref_mag_dB"]),
                ref_eps=_parse_float(row["ref_eps"]),
                ref_n=_parse_int(row["ref_n"]),
                ref_sd_MHz=_parse_float(row["ref_sd_MHz"]),
                delta_f0_MHz=_parse_float(row["delta_f0_MHz"]),
                delta_bw_MHz=_parse_float(row["delta_bw_MHz"]),
                delta_Q=_parse_float(row["delta_Q"]),
                delta_mag_dB=_parse_float(row["delta_mag_dB"]),
                delta_eps_real=_parse_float(row["delta_eps_real"]),
                residual_norm=_parse_float(row["residual_norm"]),
                ground_truth=ground_truth,
                sweep_trace=sweep_by_measurement.get(mid),
            )
            if m.sweep_trace is not None:
                report.n_measurements_with_sweep += 1
            measurements.append(m)

    report.missing_value_counts = {k: v for k, v in report.missing_value_counts.items() if v > 0}
    if report.duplicate_measurement_ids:
        report.warnings.append(
            f"{len(report.duplicate_measurement_ids)} duplicate measurement_id row(s) skipped."
        )
    if report.unknown_drift_labels:
        report.warnings.append(
            f"{len(report.unknown_drift_labels)} row(s) with a drift_label outside "
            f"{sorted(VALID_DRIFT_LABELS)}."
        )

    return measurements, report


def load_dataset(
    measurements_path: str = DEFAULT_MEASUREMENTS_CSV,
    sweep_path: str = DEFAULT_SWEEP_CSV,
) -> tuple[List[Measurement], ValidationReport]:
    """
    Load both Phase 0 CSVs and return measurements (each with its sweep_trace
    attached when one exists) plus a validation report. This is the single
    entry point the rest of the application should import.
    """
    report = ValidationReport()
    sweep_by_measurement = {}
    try:
        sweep_by_measurement = load_sweep_traces(sweep_path)
        report.n_sweep_rows = sum(len(v) for v in sweep_by_measurement.values())
    except DatasetValidationError as e:
        report.warnings.append(f"Sweep traces unavailable ({e}); continuing without them.")

    measurements, m_report = load_measurements(measurements_path, sweep_by_measurement)
    m_report.n_sweep_rows = report.n_sweep_rows
    m_report.warnings = report.warnings + m_report.warnings
    return measurements, m_report


if __name__ == "__main__":
    ms, rpt = load_dataset()
    print(f"Loaded {rpt.n_measurement_rows} measurement rows, "
          f"{rpt.n_sweep_rows} sweep points across "
          f"{rpt.n_measurements_with_sweep} measurements with a full trace.")
    print(f"Duplicates: {len(rpt.duplicate_measurement_ids)}")
    print(f"Unknown drift labels: {len(rpt.unknown_drift_labels)}")
    print(f"Missing-value columns: {rpt.missing_value_counts}")
    for w in rpt.warnings:
        print("WARNING:", w)
    print("Clean:", rpt.is_clean())
    print("Sample normalized record:", ms[0].to_app_record())
