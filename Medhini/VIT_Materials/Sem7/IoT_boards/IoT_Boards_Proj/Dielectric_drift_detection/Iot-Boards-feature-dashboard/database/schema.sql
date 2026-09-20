-- Sensor monitoring schema.
-- NOTE: value ranges enforced in application code are simulation ranges for
-- the DEMO generator only; they are not experimentally validated sensor
-- limits.

CREATE TABLE IF NOT EXISTS sensor_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    container_id      TEXT NOT NULL,
    antenna           TEXT,
    frequency         REAL,
    amplitude_db      REAL,
    phase_deg         REAL,
    residual          REAL,
    temp_ambient_c    REAL,
    validity_bit      INTEGER NOT NULL,
    condition_label   TEXT NOT NULL CHECK (
                          condition_label IN (
                              'NORMAL', 'DEGRADED', 'SUBSTITUTED', 'INSUFFICIENT EVIDENCE'
                          )
                      ),
    mode              TEXT NOT NULL CHECK (mode IN ('DEMO', 'LIVE')),
    digest            TEXT,
    prev_digest       TEXT,

    -- Phase 0 dataset fields (see dataset/phase0_loader.py). NULL for any
    -- future LIVE-mode row that doesn't originate from the CSV dataset.
    measurement_id     TEXT,
    session_id         TEXT,
    item_id            TEXT,
    container_type     TEXT,
    formulation        TEXT,
    nominal_content    TEXT,
    state              TEXT,
    substitute_content TEXT,
    drift_label        TEXT CHECK (drift_label IN ('none', 'subtle', 'gross') OR drift_label IS NULL),
    is_enrollment       INTEGER,
    placement_index     INTEGER,
    humidity_pct        REAL,
    bw_3dB_MHz           REAL,
    Q_factor             REAL,
    eps_real_estimated   REAL,
    ref_sd_MHz           REAL,
    delta_f0_MHz         REAL
);

CREATE INDEX IF NOT EXISTS idx_sensor_timestamp ON sensor_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_sensor_container ON sensor_records(container_id);
CREATE INDEX IF NOT EXISTS idx_sensor_mode      ON sensor_records(mode);
CREATE INDEX IF NOT EXISTS idx_sensor_measurement ON sensor_records(measurement_id);

CREATE TABLE IF NOT EXISTS rejections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    container_id  TEXT,
    reason        TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('DEMO', 'LIVE'))
);

CREATE TABLE IF NOT EXISTS integrity_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    chain_valid   INTEGER NOT NULL,
    last_digest   TEXT,
    record_count  INTEGER
);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Full magnitude/phase-vs-frequency sweep points from phase0_sweep_traces.csv,
-- for the subset of measurements that have one (see dataset/phase0_loader.py).
-- Joined to sensor_records via measurement_id, not a foreign key, since a
-- LIVE-mode row may have no measurement_id at all.
CREATE TABLE IF NOT EXISTS sweep_points (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id TEXT NOT NULL,
    frequency_MHz  REAL NOT NULL,
    magnitude_dB   REAL,
    phase_deg      REAL
);

CREATE INDEX IF NOT EXISTS idx_sweep_measurement ON sweep_points(measurement_id);
