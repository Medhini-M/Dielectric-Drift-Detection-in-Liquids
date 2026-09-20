"""
Background DEMO-mode Phase 0 replay generator.

Replaces the earlier pure random-walk simulator: instead of inventing
sensor values, this ticks through real rows loaded from
phase0_measurements.csv (via dataset/phase0_loader.py), grouped into the
four scenario pools built by dataset/arbitration.py.

Design:
  - On construction, loads the full Phase 0 dataset once and partitions it
    into four scenario pools (NORMAL / DEGRADED / SUBSTITUTED /
    INSUFFICIENT EVIDENCE) using dataset/arbitration.py's classify().
  - Runs on a daemon thread, ticking every DEMO_UPDATE_INTERVAL_SEC
    (~2-3s). Each tick advances one position through the *currently
    selected* scenario's pool and inserts that row.
  - Looping: once a pool is exhausted it wraps back to its start, so DEMO
    mode can run indefinitely. Phase 0 only has 1000 rows total across all
    four pools, so looping is expected, not a bug.
  - The scenario selector (VALID_SCENARIOS / set_scenario / get_scenario)
    keeps the exact same public interface as before, so routes/api.py and
    the frontend need no changes.
  - Only writes records while the app-wide mode is "DEMO"; ticks are cheap
    no-ops while mode is "LIVE" so switching back resumes immediately.
  - `timestamp` is stamped with wall-clock "now" at insert time (not the
    dataset's original timestamp_utc), so DEMO mode is a genuine real-time,
    monotonically increasing stream. Every other field - frequency,
    amplitude, phase, residual_norm, state, formulation, drift_label, etc.
    - is that row's real Phase 0 value.
"""

import random
import threading
import time
from datetime import datetime, timezone

from config import DEMO_UPDATE_INTERVAL_SEC
from database.db import execute_write, get_app_state, set_app_state
from dataset.phase0_loader import load_dataset
from dataset.arbitration import build_scenario_pools, classify, validity_bit_for, CONDITION_LABELS

VALID_SCENARIOS = ["NORMAL", "DEGRADED", "SUBSTITUTED", "INSUFFICIENT_EVIDENCE"]

SCENARIO_TO_CONDITION_LABEL = {
    "NORMAL": "NORMAL",
    "DEGRADED": "DEGRADED",
    "SUBSTITUTED": "SUBSTITUTED",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT EVIDENCE",
}

# Rejection reasons a real gate could plausibly report. Kept from the
# original simulator for rejection-chart variety - unrelated to which
# dataset backs the sensor readings.
RANDOM_REJECTION_REASONS = [
    "quorum not met",
    "consistency check failed",
    "residual out of bounds",
    "timestamp gap detected",
    "checksum mismatch",
]

# Probability, per tick, of logging one extra simulated rejection event,
# independent of the active scenario.
RANDOM_REJECTION_CHANCE = 0.15

_SENSOR_RECORD_COLUMNS = [
    "timestamp", "container_id", "antenna", "frequency", "amplitude_db",
    "phase_deg", "residual", "temp_ambient_c", "validity_bit",
    "condition_label", "mode", "measurement_id", "session_id", "item_id",
    "container_type", "formulation", "nominal_content", "state",
    "substitute_content", "drift_label", "is_enrollment", "placement_index",
    "humidity_pct", "bw_3dB_MHz", "Q_factor", "eps_real_estimated",
    "ref_sd_MHz", "delta_f0_MHz",
]


class DemoGenerator:
    def __init__(self):
        measurements, self.load_report = load_dataset()
        self._pools = build_scenario_pools(measurements)
        self._cursors = {label: 0 for label in CONDITION_LABELS}
        self._scenario = "NORMAL"
        self._lock = threading.Lock()
        self._thread = None
        self._running = False

    def set_scenario(self, scenario):
        scenario = scenario.upper().replace(" ", "_")
        if scenario not in VALID_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")
        with self._lock:
            self._scenario = scenario

    def get_scenario(self):
        with self._lock:
            return self._scenario

    def _next_measurement(self, condition_label):
        pool = self._pools.get(condition_label, [])
        if not pool:
            return None
        with self._lock:
            idx = self._cursors[condition_label] % len(pool)
            self._cursors[condition_label] += 1
        return pool[idx]

    def _generate_record(self):
        scenario = self.get_scenario()
        condition_label = SCENARIO_TO_CONDITION_LABEL[scenario]
        m = self._next_measurement(condition_label)
        if m is None:
            return None  # shouldn't happen - every Phase 0 pool is non-empty

        # classify() is re-run here (not just trusted from the pool) so the
        # inserted label always matches this row's own data, even if a
        # future dataset revision changes the arbitration thresholds.
        actual_condition_label = classify(m)
        validity_bit = validity_bit_for(actual_condition_label)

        record = m.to_app_record(mode="DEMO")
        record["timestamp"] = datetime.now(timezone.utc).isoformat()
        record["condition_label"] = actual_condition_label
        record["validity_bit"] = validity_bit
        record["is_enrollment"] = int(m.is_enrollment)
        if actual_condition_label == "INSUFFICIENT EVIDENCE":
            # Existing convention: withhold the residual when evidence is
            # insufficient rather than asserting a number.
            record["residual"] = None
        return record

    def _insert_record(self, record):
        placeholders = ", ".join(["?"] * len(_SENSOR_RECORD_COLUMNS))
        columns = ", ".join(_SENSOR_RECORD_COLUMNS)
        execute_write(
            f"INSERT INTO sensor_records ({columns}) VALUES ({placeholders})",
            tuple(record[c] for c in _SENSOR_RECORD_COLUMNS),
        )

        if record["condition_label"] == "INSUFFICIENT EVIDENCE":
            self._log_rejection(record, "quorum not met")

        if random.random() < RANDOM_REJECTION_CHANCE:
            reason = random.choice(RANDOM_REJECTION_REASONS)
            self._log_rejection(record, reason)

    def _log_rejection(self, record, reason):
        execute_write(
            "INSERT INTO rejections (timestamp, container_id, reason, mode) "
            "VALUES (?, ?, ?, ?)",
            (record["timestamp"], record["container_id"], reason, record["mode"]),
        )

    def _loop(self):
        while self._running:
            current_mode = get_app_state("mode", "DEMO")
            if current_mode == "DEMO":
                record = self._generate_record()
                if record is not None:
                    self._insert_record(record)
                    set_app_state("latest_demo_timestamp", record["timestamp"])
            time.sleep(DEMO_UPDATE_INTERVAL_SEC)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False


# Module-level singleton used by the Flask app and routes.
generator = DemoGenerator()
