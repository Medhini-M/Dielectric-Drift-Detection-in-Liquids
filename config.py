"""
Application configuration.

DEMO_UPDATE_INTERVAL_SEC controls how often the background simulator generates
a new record. This is a UI/demo-pacing knob only, not a sensor calibration
value.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.path.join(BASE_DIR, "data", "sensor.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")

DEMO_UPDATE_INTERVAL_SEC = 1.5

HOST = "0.0.0.0"
PORT = 5000
DEBUG = False
