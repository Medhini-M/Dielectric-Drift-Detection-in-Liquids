# Sensor Monitoring Dashboard (Flask prototype)

A lightweight Flask + SQLite + vanilla JS dashboard prototype for the
container-condition sensing system. Runs entirely on a Raspberry Pi 5 with
no cloud dependency.

## Architecture

```
DemoGenerator (background thread, simulator/demo_generator.py)
        │ writes rows tagged mode="DEMO"
        ▼
   SQLite (data/sensor.db)
        ▲
        │ reads
   Flask REST API (routes/api.py)
        ▲
        │ fetch() polling every ~1.5s
   Browser dashboard (static/js/dashboard.js + templates/index.html)
```

- **DEMO MODE** is fully functional: a background thread generates smoothly
  drifting simulated sensor records every 1–2 seconds and writes them to
  SQLite. A scenario selector lets you force NORMAL / DEGRADED / SUBSTITUTED
  / INSUFFICIENT EVIDENCE for a live demonstration.
- **LIVE MODE** is a structural placeholder. Switching to LIVE mode stops
  the demo generator from writing new rows, and the dashboard shows
  "LIVE MODE — Waiting for sensor data..." because nothing has written a
  row with `mode="LIVE"` yet. No MQTT client is implemented in this
  prototype. To wire up real sensor data later, add an MQTT subscriber that
  inserts rows into `sensor_records` with `mode="LIVE"` using the same
  pattern as `simulator/demo_generator.py::_insert_record` — no changes to
  the frontend or API routes are required.

**Important:** the value ranges and step sizes in `simulator/demo_generator.py`
are simulation choices for a believable demo UI. They are **not**
experimentally validated sensor limits.

## Project structure

```
sensor_dashboard/
├── app.py
├── requirements.txt
├── README.md
├── config.py
├── database/
│   ├── __init__.py
│   ├── db.py
│   └── schema.sql
├── simulator/
│   ├── __init__.py
│   └── demo_generator.py
├── routes/
│   ├── __init__.py
│   └── api.py
├── templates/
│   └── index.html
├── static/
│   ├── css/style.css
│   └── js/dashboard.js
└── data/
    └── sensor.db          # created automatically on first run
```

## Install and run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open, from any device on the same network:

```
http://<raspberry-pi-ip>:5000
```

The SQLite database and `data/` directory are created automatically on
first run — no manual setup needed.

## REST API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/latest` | Most recent record for the current mode |
| GET | `/api/history` | Historical records; supports `?limit=`, `?container_id=`, `?mode=` |
| GET | `/api/rejections` | Rejection reason counts (bar chart data) |
| GET | `/api/integrity` | Latest chain-integrity status |
| GET/POST | `/api/mode` | Read or set current mode (`DEMO` / `LIVE`) |
| GET/POST | `/api/demo/scenario` | Read or set the active demo scenario |

## Offline / no-internet use

Chart.js is loaded from a CDN (`cdn.jsdelivr.net`) in `templates/index.html`.
If the Pi will run fully offline, download
`https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js`, save it
as `static/js/chart.umd.min.js`, and change the `<script src="...">` tag in
`templates/index.html` to `{{ url_for('static', filename='js/chart.umd.min.js') }}`.

## Notes

- No authentication or transport security is implemented — this is a
  functional prototype, not a hardened deployment.
- SQLite access uses a single shared connection with a lock; this is fine
  at the prototype's write volume (roughly one insert every 1–2 seconds)
  but is not intended for high-concurrency production use.
