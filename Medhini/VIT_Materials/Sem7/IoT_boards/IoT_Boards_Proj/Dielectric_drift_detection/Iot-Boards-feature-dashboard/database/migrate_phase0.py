"""
Idempotent migration for databases created before the Phase 0 integration.

`database/schema.sql` already has the new columns and the sweep_points
table for a FRESH database (CREATE TABLE IF NOT EXISTS handles that). This
script is for a `data/sensor.db` that already exists from a previous run:
SQLite's CREATE TABLE IF NOT EXISTS won't add columns to a table that
already exists, so we ALTER TABLE ... ADD COLUMN for anything missing.

Safe to run multiple times - every step checks what's already there first.
Also populates sweep_points from phase0_sweep_traces.csv on first run
(once only; re-running with sweep_points already populated is a no-op).
"""

from database.db import get_connection
from dataset.phase0_loader import load_sweep_traces, DEFAULT_SWEEP_CSV, DatasetValidationError

# (column name, SQLite type) - kept in sync with database/schema.sql
NEW_SENSOR_RECORD_COLUMNS = [
    ("measurement_id", "TEXT"),
    ("session_id", "TEXT"),
    ("item_id", "TEXT"),
    ("container_type", "TEXT"),
    ("formulation", "TEXT"),
    ("nominal_content", "TEXT"),
    ("state", "TEXT"),
    ("substitute_content", "TEXT"),
    ("drift_label", "TEXT"),
    ("is_enrollment", "INTEGER"),
    ("placement_index", "INTEGER"),
    ("humidity_pct", "REAL"),
    ("bw_3dB_MHz", "REAL"),
    ("Q_factor", "REAL"),
    ("eps_real_estimated", "REAL"),
    ("ref_sd_MHz", "REAL"),
    ("delta_f0_MHz", "REAL"),
]


def _existing_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _migrate_sensor_records_columns(conn):
    existing = _existing_columns(conn, "sensor_records")
    added = []
    for name, coltype in NEW_SENSOR_RECORD_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sensor_records ADD COLUMN {name} {coltype}")
            added.append(name)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sensor_measurement ON sensor_records(measurement_id)"
    )
    conn.commit()
    return added


def _ensure_sweep_points_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sweep_points (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            measurement_id TEXT NOT NULL,
            frequency_MHz  REAL NOT NULL,
            magnitude_dB   REAL,
            phase_deg      REAL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sweep_measurement ON sweep_points(measurement_id)")
    conn.commit()


def _populate_sweep_points(conn):
    count = conn.execute("SELECT COUNT(*) FROM sweep_points").fetchone()[0]
    if count > 0:
        return 0, 0  # already populated, nothing to do

    try:
        sweep_by_measurement = load_sweep_traces(DEFAULT_SWEEP_CSV)
    except DatasetValidationError as e:
        print(f"WARNING: could not populate sweep_points ({e})")
        return 0, 0

    rows = [
        (mid, p.frequency_MHz, p.magnitude_dB, p.phase_deg)
        for mid, points in sweep_by_measurement.items()
        for p in points
    ]
    conn.executemany(
        "INSERT INTO sweep_points (measurement_id, frequency_MHz, magnitude_dB, phase_deg) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows), len(sweep_by_measurement)


def migrate():
    conn = get_connection()
    added = _migrate_sensor_records_columns(conn)
    _ensure_sweep_points_table(conn)
    n_points, n_measurements = _populate_sweep_points(conn)

    if added:
        print(f"sensor_records: added columns {added}")
    else:
        print("sensor_records: already up to date")

    if n_points:
        print(f"sweep_points: populated {n_points} rows across {n_measurements} measurements")
    else:
        print("sweep_points: already populated (or dataset unavailable) - skipped")


if __name__ == "__main__":
    migrate()
