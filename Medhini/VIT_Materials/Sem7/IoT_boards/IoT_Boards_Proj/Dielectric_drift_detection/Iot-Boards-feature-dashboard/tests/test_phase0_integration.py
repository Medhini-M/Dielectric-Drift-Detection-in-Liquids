"""
Step 12 automated validation suite for the Phase 0 integration.

Covers, without needing a browser:
  - Dataset validation (both CSVs load clean, sweep join, no ground-truth
    leakage)
  - Scenario / arbitration validation (all four pools real and non-empty,
    partition covers the dataset exactly once)
  - DEMO mode + API contract (scenario switch produces a correctly labeled
    real record, timestamps monotonic across ticks, /api/* endpoints shaped
    correctly, /api/sweep both branches, no old/duplicate data)

Runs against a throwaway sqlite file (see conftest.py) - never touches your
real data/sensor.db.

What this suite deliberately does NOT check (needs a real browser, not
pytest - see the manual checklist in docs/API_CHANGES.md and the earlier
sweep-trace-fix instructions):
  - the real-time chart visually redraws without a full page reload
  - the frontend's own record-id dedupe guard (covered here only at the
    API level: successive ticks produce distinct ids/timestamps, which is
    the precondition the frontend guard relies on)

Run with:
    pytest tests/ -v
"""

import time

import pytest

from dataset.phase0_loader import load_dataset
from dataset.arbitration import build_scenario_pools, classify, CONDITION_LABELS


# ---------------------------------------------------------------------------
# Dataset validation
# ---------------------------------------------------------------------------

def test_dataset_loads_with_zero_validation_errors():
    measurements, report = load_dataset()
    assert report.is_clean()
    assert report.n_measurement_rows == 1000
    assert not report.duplicate_measurement_ids
    assert not report.unknown_drift_labels
    assert not report.missing_value_counts


def test_all_timestamps_parse_into_the_four_known_sessions():
    measurements, _ = load_dataset()
    sessions = {}
    for m in measurements:
        sessions.setdefault(m.session_id, []).append(m.timestamp_utc)
    assert set(sessions) == {"S1", "S2", "S3", "S4"}
    for timestamps in sessions.values():
        assert all(ts.year == 2026 for ts in timestamps)


def test_sweep_traces_join_to_real_measurements():
    measurements, report = load_dataset()
    assert report.n_measurements_with_sweep == 24
    assert report.n_sweep_rows == 19224
    with_sweep = [m for m in measurements if m.has_sweep_trace]
    assert len(with_sweep) == 24
    for m in with_sweep:
        assert len(m.sweep_trace) == 801
        freqs = [p.frequency_MHz for p in m.sweep_trace]
        assert freqs == sorted(freqs)  # loader sorts each trace by frequency


def test_ground_truth_columns_never_reach_the_app_record():
    measurements, _ = load_dataset()
    record = measurements[0].to_app_record()
    assert not any(k.startswith("_gt_") for k in record)


# ---------------------------------------------------------------------------
# Scenario / arbitration validation
# ---------------------------------------------------------------------------

def test_all_four_scenario_pools_are_non_empty():
    measurements, _ = load_dataset()
    pools = build_scenario_pools(measurements)
    assert set(pools) == set(CONDITION_LABELS)
    for label, pool in pools.items():
        assert len(pool) > 0, f"{label} pool is empty"


def test_gross_drift_always_classifies_as_substituted():
    measurements, _ = load_dataset()
    for m in measurements:
        if m.drift_label == "gross":
            assert classify(m) == "SUBSTITUTED"


def test_pool_partition_covers_every_measurement_exactly_once():
    measurements, _ = load_dataset()
    pools = build_scenario_pools(measurements)
    all_ids = [m.measurement_id for pool in pools.values() for m in pool]
    assert len(all_ids) == len(measurements)
    assert len(set(all_ids)) == len(all_ids)  # nothing dropped, nothing duplicated


def test_sweep_bearing_rows_recur_within_a_bounded_gap():
    """Regression test for the 'stuck on no sweep trace' bug: no scenario
    pool should make you wait more than ~100 ticks to see a sweep example."""
    measurements, _ = load_dataset()
    pools = build_scenario_pools(measurements)
    for label, pool in pools.items():
        positions = [i for i, m in enumerate(pool) if m.has_sweep_trace]
        if not positions:
            continue
        gaps = [b - a for a, b in zip([0] + positions, positions)]
        assert max(gaps) < 100, f"{label}: gap of {max(gaps)} ticks between sweep examples"


# ---------------------------------------------------------------------------
# DEMO generator + live API (uses the throwaway db from conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    import app as app_module  # import here, after conftest has patched DATABASE_PATH
    return app_module.app.test_client()


def test_demo_scenario_endpoint_accepts_all_four_scenarios(client):
    from simulator.demo_generator import VALID_SCENARIOS
    for scenario in VALID_SCENARIOS:
        resp = client.post("/api/demo/scenario", json={"scenario": scenario})
        assert resp.status_code == 200
        assert resp.get_json()["scenario"] == scenario


def test_demo_scenario_endpoint_rejects_unknown_scenario(client):
    resp = client.post("/api/demo/scenario", json={"scenario": "NOT_A_REAL_SCENARIO"})
    assert resp.status_code == 400


@pytest.mark.parametrize("scenario,expected_label,expect_residual", [
    ("NORMAL", "NORMAL", True),
    ("DEGRADED", "DEGRADED", True),
    ("SUBSTITUTED", "SUBSTITUTED", True),
    ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT EVIDENCE", False),
])
def test_each_scenario_produces_a_correctly_labeled_real_record(
    client, scenario, expected_label, expect_residual
):
    from simulator.demo_generator import generator

    generator.set_scenario(scenario)
    rec = generator._generate_record()
    generator._insert_record(rec)

    assert rec["condition_label"] == expected_label
    assert rec["mode"] == "DEMO"
    assert rec["item_id"]  # a real Phase 0 item_id, never fabricated
    assert rec["measurement_id"].startswith("M0")
    if expect_residual:
        assert rec["residual"] is not None
        assert rec["validity_bit"] == 1
    else:
        assert rec["residual"] is None
        assert rec["validity_bit"] == 0


def test_successive_ticks_produce_distinct_monotonic_timestamps(client):
    from simulator.demo_generator import generator

    generator.set_scenario("NORMAL")
    timestamps = []
    for _ in range(5):
        rec = generator._generate_record()
        generator._insert_record(rec)
        timestamps.append(rec["timestamp"])
        time.sleep(0.01)

    assert len(set(timestamps)) == len(timestamps)  # no duplicate timestamps
    assert timestamps == sorted(timestamps)  # monotonically increasing


def test_api_latest_reflects_the_active_scenario(client):
    from simulator.demo_generator import generator

    generator.set_scenario("SUBSTITUTED")
    rec = generator._generate_record()
    generator._insert_record(rec)

    data = client.get("/api/latest").get_json()
    assert data["mode"] == "DEMO"
    assert data["record"]["condition_label"] == "SUBSTITUTED"
    assert "id" in data["record"]  # required by the frontend's dedupe guard


def test_api_history_is_chronological_and_has_no_duplicate_ids(client):
    from simulator.demo_generator import generator

    generator.set_scenario("NORMAL")
    for _ in range(6):
        rec = generator._generate_record()
        generator._insert_record(rec)
        time.sleep(0.01)

    records = client.get("/api/history?limit=50").get_json()["records"]
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
    timestamps = [r["timestamp"] for r in records]
    assert timestamps == sorted(timestamps, reverse=True)  # documented DESC order


def test_api_rejections_shape(client):
    from simulator.demo_generator import generator

    generator.set_scenario("INSUFFICIENT_EVIDENCE")
    rec = generator._generate_record()
    generator._insert_record(rec)

    data = client.get("/api/rejections").get_json()
    assert "rejections" in data
    reasons = [r["reason"] for r in data["rejections"]]
    assert "quorum not met" in reasons


def test_api_sweep_known_and_unknown_measurement(client):
    data = client.get("/api/sweep/M00001").get_json()
    assert data["measurement_id"] == "M00001"
    assert len(data["points"]) == 801

    resp2 = client.get("/api/sweep/NOT-A-REAL-ID")
    assert resp2.status_code == 200  # empty, not an error
    assert resp2.get_json()["points"] == []


def test_no_gt_columns_ever_appear_in_an_api_response(client):
    from simulator.demo_generator import generator

    generator.set_scenario("NORMAL")
    rec = generator._generate_record()
    generator._insert_record(rec)

    for path in ["/api/latest", "/api/history?limit=10"]:
        body = client.get(path).get_data(as_text=True)
        assert "_gt_" not in body


def test_mode_endpoint_round_trip(client):
    resp = client.post("/api/mode", json={"mode": "LIVE"})
    assert resp.get_json()["mode"] == "LIVE"
    assert client.get("/api/mode").get_json()["mode"] == "LIVE"
    client.post("/api/mode", json={"mode": "DEMO"})  # restore for later tests


def test_mode_endpoint_rejects_invalid_mode(client):
    resp = client.post("/api/mode", json={"mode": "BOGUS"})
    assert resp.status_code == 400


def test_frequency_values_are_real_phase0_range_not_old_fixed_list():
    """Regression test for step 11: the old simulator used a fixed list
    [433.0, 868.0, 915.0, 2400.0] MHz. Phase 0 f0 values are continuous,
    roughly 2800-3200 MHz."""
    measurements, _ = load_dataset()
    old_fixed_values = {433.0, 868.0, 915.0, 2400.0}
    sampled = {round(m.f0_MHz) for m in measurements[:50]}
    assert not sampled & old_fixed_values
    assert all(2700 <= m.f0_MHz <= 3300 for m in measurements)
