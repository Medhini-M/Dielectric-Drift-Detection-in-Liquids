-- Sensor monitoring schema.
-- NOTE: value ranges enforced in application code are simulation ranges for
-- the DEMO generator only; they are not experimentally validated sensor
-- limits.

CREATE TABLE IF NOT EXISTS sensor_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    container_id      TEXT NOT NULL,
    antenna           INTEGER,
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
    prev_digest       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sensor_timestamp ON sensor_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_sensor_container ON sensor_records(container_id);
CREATE INDEX IF NOT EXISTS idx_sensor_mode      ON sensor_records(mode);

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
