"""
Background DEMO-mode sensor simulator.

IMPORTANT: All ranges and step sizes below are simulation choices made for a
believable demo UI. They are NOT experimentally validated sensor limits and
must not be treated as calibration data for the real RF sensing hardware.

Design:
  - Runs on a daemon thread, ticking every DEMO_UPDATE_INTERVAL_SEC.
  - Maintains state between ticks and applies small bounded random steps
    ("random walk") so values drift smoothly instead of jumping randomly.
  - The active scenario (NORMAL / DEGRADED / SUBSTITUTED / INSUFFICIENT
    EVIDENCE) shifts the distribution of the residual and validity_bit,
    simulating what each condition would look like.
  - Only runs its insert/update logic while the app-wide mode is "DEMO".
    When mode is "LIVE" it keeps ticking (cheap) but does not write records,
    so switching back to DEMO resumes immediately without a restart.
"""

import random
import threading
import time
from datetime import datetime, timezone

from config import DEMO_UPDATE_INTERVAL_SEC
from database.db import execute_write, get_app_state, set_app_state

ANTENNAS = [1, 2, 3, 4]
FREQUENCIES_MHZ = [433.0, 868.0, 915.0, 2400.0]
DEFAULT_CONTAINER_ID = "C001"

VALID_SCENARIOS = ["NORMAL", "DEGRADED", "SUBSTITUTED", "INSUFFICIENT_EVIDENCE"]

CONDITION_LABELS = {
    "NORMAL": "NORMAL",
    "DEGRADED": "DEGRADED",
    "SUBSTITUTED": "SUBSTITUTED",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT EVIDENCE",
}

# Rejection reasons a real gate could plausibly report. These are simulated
# for demo variety - the "quorum not met" reason is also logged for real
# whenever the INSUFFICIENT_EVIDENCE scenario is active (see _generate_record).
RANDOM_REJECTION_REASONS = [
    "quorum not met",
    "consistency check failed",
    "residual out of bounds",
    "timestamp gap detected",
    "checksum mismatch",
]

# Probability, per tick, of logging one extra simulated rejection event.
# This is independent of the active scenario, so the rejection chart has
# some background variety to demo even while sitting in NORMAL.
RANDOM_REJECTION_CHANCE = 0.15


def _walk(value, step, lo, hi):
    """Bounded random-walk step: smooth drift instead of independent noise."""
    nxt = value + random.uniform(-step, step)
    return max(lo, min(hi, nxt))


class DemoGenerator:
    def __init__(self):
        self._state = {
            "amplitude_db": -12.0,
            "phase_deg": 135.0,
            "temp_ambient_c": 23.5,
            "antenna_idx": 0,
        }
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

    def _generate_record(self):
        s = self._state
        s["amplitude_db"] = _walk(s["amplitude_db"], 0.3, -20.0, -5.0)
        s["phase_deg"] = _walk(s["phase_deg"], 2.0, 0.0, 360.0)
        s["temp_ambient_c"] = _walk(s["temp_ambient_c"], 0.1, 18.0, 30.0)
        s["antenna_idx"] = (s["antenna_idx"] + 1) % len(ANTENNAS)

        scenario = self.get_scenario()

        if scenario == "NORMAL":
            residual = _walk(0.05, 0.02, 0.0, 0.10)
            validity_bit = 1
        elif scenario == "DEGRADED":
            residual = _walk(0.25, 0.05, 0.15, 0.40)
            validity_bit = 1
        elif scenario == "SUBSTITUTED":
            residual = _walk(0.75, 0.08, 0.55, 0.95)
            validity_bit = 1
            # Simulate a bigger, more abrupt amplitude jump for a spoofed signal.
            s["amplitude_db"] = _walk(s["amplitude_db"], 1.5, -25.0, -3.0)
        else:  # INSUFFICIENT_EVIDENCE - quorum not met, residual withheld
            residual = None
            validity_bit = 0

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "container_id": DEFAULT_CONTAINER_ID,
            "antenna": ANTENNAS[s["antenna_idx"]],
            "frequency": FREQUENCIES_MHZ[s["antenna_idx"]],
            "amplitude_db": round(s["amplitude_db"], 2),
            "phase_deg": round(s["phase_deg"], 2),
            "residual": round(residual, 3) if residual is not None else None,
            "temp_ambient_c": round(s["temp_ambient_c"], 2),
            "validity_bit": validity_bit,
            "condition_label": CONDITION_LABELS[scenario],
            "mode": "DEMO",
        }
        return record

    def _insert_record(self, record):
        execute_write(
            """
            INSERT INTO sensor_records
                (timestamp, container_id, antenna, frequency, amplitude_db,
                 phase_deg, residual, temp_ambient_c, validity_bit,
                 condition_label, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["timestamp"],
                record["container_id"],
                record["antenna"],
                record["frequency"],
                record["amplitude_db"],
                record["phase_deg"],
                record["residual"],
                record["temp_ambient_c"],
                record["validity_bit"],
                record["condition_label"],
                record["mode"],
            ),
        )
        if record["condition_label"] == "INSUFFICIENT EVIDENCE":
            self._log_rejection(record, "quorum not met")

        # Occasionally log an extra, independent simulated rejection so the
        # rejection-statistics chart has more than one reason to show.
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
