"""
Sensor Monitoring Dashboard - Flask application entry point.

Architecture / data flow
-------------------------
    DemoGenerator (background thread)
            |
            v  writes rows tagged mode="DEMO"
        SQLite (data/sensor.db)
            ^
            |  reads (mode-filtered)
    Flask REST API (/api/*)
            ^
            |  fetch() polling every 1-2s
    Browser dashboard (static/js/dashboard.js)

LIVE MODE is a placeholder in this prototype: switching the mode to LIVE
(via POST /api/mode) stops the demo generator from writing new rows, and the
frontend shows "Waiting for sensor data..." because /api/latest has nothing
tagged mode="LIVE" to return yet. The API, database schema, and frontend are
already mode-aware, so wiring in a real MQTT subscriber later only requires
adding a subscriber that inserts rows with mode="LIVE" using the same
insert pattern as simulator/demo_generator.py - no route or frontend
changes are required.
"""

from flask import Flask, render_template

from config import HOST, PORT, DEBUG
from database.db import init_db, set_app_state, get_app_state
from routes.api import api_bp
from simulator.demo_generator import generator


def create_app():
    app = Flask(__name__)

    init_db()

    # Default to DEMO mode on a fresh database.
    if get_app_state("mode") is None:
        set_app_state("mode", "DEMO")

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


app = create_app()

# Start the background demo simulator once, at import time, so it runs
# under both `python app.py` and a production WSGI server.
generator.start()


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
