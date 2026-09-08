"""
REST API blueprint.

LIVE MODE NOTE: there is no MQTT client wired up yet. `/api/latest` and
`/api/history` behave the same way regardless of mode - they just read
whatever is in SQLite. When mode is LIVE and nothing has ever been written
with mode="LIVE", `/api/latest` naturally returns null/empty and the
frontend shows "Waiting for sensor data...". To add real sensor input
later, write an MQTT subscriber that calls the same insert logic used by
DemoGenerator._insert_record with mode="LIVE" - no frontend changes needed.
"""

from flask import Blueprint, jsonify, request

from database.db import execute_read, execute_read_one, get_app_state, set_app_state
from simulator.demo_generator import generator, VALID_SCENARIOS

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/latest", methods=["GET"])
def latest():
    mode = get_app_state("mode", "DEMO")
    row = execute_read_one(
        "SELECT * FROM sensor_records WHERE mode = ? ORDER BY id DESC LIMIT 1",
        (mode,),
    )
    return jsonify({"mode": mode, "record": row})


@api_bp.route("/history", methods=["GET"])
def history():
    limit = request.args.get("limit", default=200, type=int)
    container_id = request.args.get("container_id")
    mode = request.args.get("mode")

    sql = "SELECT * FROM sensor_records WHERE 1=1"
    params = []

    if container_id:
        sql += " AND container_id = ?"
        params.append(container_id)
    if mode:
        sql += " AND mode = ?"
        params.append(mode)

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = execute_read(sql, tuple(params))
    return jsonify({"count": len(rows), "records": rows})


@api_bp.route("/rejections", methods=["GET"])
def rejections():
    rows = execute_read(
        "SELECT reason, COUNT(*) AS count FROM rejections GROUP BY reason ORDER BY count DESC"
    )
    return jsonify({"rejections": rows})


@api_bp.route("/integrity", methods=["GET"])
def integrity():
    row = execute_read_one("SELECT * FROM integrity_log ORDER BY id DESC LIMIT 1")
    if row is None:
        # No chain events yet in this prototype - report a neutral placeholder
        # rather than fabricating a verified/failed state.
        row = {"chain_valid": None, "last_digest": None, "record_count": 0}
    return jsonify(row)


@api_bp.route("/mode", methods=["GET", "POST"])
def mode():
    if request.method == "GET":
        return jsonify({"mode": get_app_state("mode", "DEMO")})

    data = request.get_json(force=True, silent=True) or {}
    new_mode = str(data.get("mode", "")).upper()
    if new_mode not in ("DEMO", "LIVE"):
        return jsonify({"error": "mode must be 'DEMO' or 'LIVE'"}), 400

    set_app_state("mode", new_mode)
    return jsonify({"mode": new_mode})


@api_bp.route("/demo/scenario", methods=["GET", "POST"])
def demo_scenario():
    if request.method == "GET":
        return jsonify({"scenario": generator.get_scenario()})

    data = request.get_json(force=True, silent=True) or {}
    scenario = str(data.get("scenario", "")).upper()
    try:
        generator.set_scenario(scenario)
    except ValueError:
        return jsonify({
            "error": f"scenario must be one of {VALID_SCENARIOS}"
        }), 400

    return jsonify({"scenario": generator.get_scenario()})
