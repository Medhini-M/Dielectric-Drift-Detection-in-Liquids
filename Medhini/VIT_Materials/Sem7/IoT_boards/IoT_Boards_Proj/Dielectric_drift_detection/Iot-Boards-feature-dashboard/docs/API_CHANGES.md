# API changes — Phase 0 integration (step 10)

Every existing route's URL, HTTP method, and top-level JSON shape is
**unchanged** — the frontend/API contract is preserved. What changed is
that `sensor_records` rows now carry ~17 extra Phase 0 fields (added in
step 4), so the routes that do `SELECT *` return those extra fields too.
One brand-new route was added (`/api/sweep`, step 9) for sweep-trace data.

## `GET /api/latest` — unchanged shape, richer `record`

**Before** (`record` fields): `id, timestamp, container_id, antenna,
frequency, amplitude_db, phase_deg, residual, temp_ambient_c,
validity_bit, condition_label, mode, digest, prev_digest`

**After**: all of the above, plus:
`measurement_id, session_id, item_id, container_type, formulation,
nominal_content, state, substitute_content, drift_label, is_enrollment,
placement_index, humidity_pct, bw_3dB_MHz, Q_factor, eps_real_estimated,
ref_sd_MHz, delta_f0_MHz`

Behavioral notes:
- `container_id` is still populated (now sourced from Phase 0's `item_id`,
  e.g. `VIA-01-001`, instead of the old fixed `"C001"`).
- `antenna` is now a short code string (`"ANT-A"` / `"ANT-B"`) instead of
  an integer 1–4.
- `frequency` is now a real f0 value (~2800–3200 MHz, continuous) instead
  of one of the old fixed values `[433.0, 868.0, 915.0, 2400.0]`.
- `residual` is `null` and `validity_bit` is `0` specifically when
  `condition_label == "INSUFFICIENT EVIDENCE"` — same convention as
  before, now driven by real ambiguous-residual rows instead of a
  scripted branch.
- `_gt_*` (ground-truth) columns are **never** present in this or any
  other response — see `dataset/phase0_loader.py`'s docstring.

## `GET /api/history?limit=&container_id=&mode=` — unchanged shape, richer `records`

Same extra fields as `/api/latest`, applied to every row in `records`.
Query params are unchanged; `container_id` now filters on real Phase 0
item ids (e.g. `?container_id=VIA-01-001`) instead of the old `"C001"`.

## `GET /api/rejections` — unchanged

Shape unchanged: `{"rejections": [{"reason": ..., "count": ...}, ...]}`.
`"quorum not met"` now fires specifically when a replayed row classifies
as `INSUFFICIENT EVIDENCE` (real ambiguous-residual rows), not on a fixed
scenario branch. The other four reasons are still randomly injected for
demo variety, unrelated to which dataset backs the readings.

## `GET /api/integrity` — unchanged

No change. Chain-of-custody digesting was never implemented in this
prototype (`digest`/`prev_digest` are still always `null`); out of scope
for the Phase 0 integration.

## `GET/POST /api/mode` — unchanged

No change. Still just toggles `DEMO`/`LIVE` in `app_state`.

## `GET/POST /api/demo/scenario` — unchanged shape, real data underneath

Same four accepted values (`NORMAL`, `DEGRADED`, `SUBSTITUTED`,
`INSUFFICIENT_EVIDENCE`) and same response shape
(`{"scenario": "..."}`). What changed is what happens server-side when
you set one: instead of shifting a random-walk's distribution, it now
selects which real Phase 0 scenario pool the replay loop draws from (see
`dataset/arbitration.py`).

## `GET /api/sweep/<measurement_id>` — new (step 9)

```json
{
  "measurement_id": "M00001",
  "points": [
    {"frequency_MHz": 2800.0, "magnitude_dB": -0.0182, "phase_deg": -2.509},
    ...
  ]
}
```

- Returns the full 801-point magnitude/phase-vs-frequency sweep for one
  measurement, if it has one.
- Only 24 of the 1000 Phase 0 measurements have a full sweep
  (`phase0_sweep_traces.csv` is a representative subset, not all 1000 —
  see `README_phase0_dataset.md`). For any other `measurement_id`,
  `points` is an empty list with a normal `200` response — **not** a 404
  — since "no sweep for this reading" is the common case, not an error.
- Used by the sweep-trace chart added in step 9.

## What did NOT change and why

- Route URLs, HTTP methods, and request payload shapes: identical.
- `routes/api.py`'s existing five routes needed **no logic changes** —
  they already do `SELECT *` / `INSERT` against whatever columns exist in
  `sensor_records`, so the step-4 schema migration and step-5/6 generator
  rewrite flow through them automatically. Only the new `/api/sweep` route
  is new code in this file.
- No breaking changes: any existing frontend code that only reads the
  original fields continues to work unmodified; new fields are additive.
