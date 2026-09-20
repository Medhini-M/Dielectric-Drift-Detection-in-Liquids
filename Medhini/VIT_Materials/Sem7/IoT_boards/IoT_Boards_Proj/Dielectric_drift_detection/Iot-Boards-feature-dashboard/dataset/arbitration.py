"""
Scenario classification: Phase 0 measurement row -> one of the four
dashboard states (NORMAL / DEGRADED / SUBSTITUTED / INSUFFICIENT EVIDENCE).

This is the "adapt the existing scenario logic to the new dataset" piece
(integration step 6). It does not invent a new decision system - it wires
the dashboard's existing four-state selector to real fields already in
phase0_measurements.csv.

Base mapping
------------
`drift_label` is a regular dataset column (not a `_gt_*` ground-truth
column), so using it to select which rows represent which state is not
fabricating data:

    drift_label == "none"   -> NORMAL       (Fresh state, no drift)
    drift_label == "subtle" -> DEGRADED     (Expired / Heat-stressed /
                                              Freeze-thaw / Photodegraded)
    drift_label == "gross"  -> SUBSTITUTED  (Substituted state / fill-
                                              integrity decoys)

INSUFFICIENT EVIDENCE
----------------------
Phase 0 has no dedicated label for this: `ref_n` is always 3, so no row is
a genuine quorum failure. Rather than invent an unrelated rule, we use the
dataset's own documented finding (README_phase0_dataset.md, "The Phase 0
finding this dataset encodes"): "none" and "subtle" residual_norm are
statistically indistinguishable from each other. Computed directly from
the actual none+subtle residual_norm pool in phase0_measurements.csv:

    p25 = 0.402   p75 = 1.153

Any none/subtle row whose residual_norm falls in that interquartile band
is a row where a real arbitration stage could not reliably tell "no drift"
from "subtle drift" apart - which is exactly the condition the project's
own architecture says should abstain rather than guess. Those rows are
classified INSUFFICIENT EVIDENCE regardless of their drift_label.

Gross-substitution rows are left alone: they separate from the
none/subtle pool by roughly 26x in the dataset's own median residual_norm
and are not folded into the ambiguous band.
"""

from typing import Dict, List

from dataset.phase0_loader import Measurement

# Computed once from phase0_measurements.csv - see module docstring.
AMBIGUOUS_BAND_LOW = 0.402
AMBIGUOUS_BAND_HIGH = 1.153

DRIFT_LABEL_TO_CONDITION = {
    "none": "NORMAL",
    "subtle": "DEGRADED",
    "gross": "SUBSTITUTED",
}

CONDITION_LABELS = ["NORMAL", "DEGRADED", "SUBSTITUTED", "INSUFFICIENT EVIDENCE"]


def classify(m: Measurement) -> str:
    """Return the dashboard condition_label for one Phase 0 measurement row."""
    if m.drift_label in ("none", "subtle") and AMBIGUOUS_BAND_LOW <= m.residual_norm <= AMBIGUOUS_BAND_HIGH:
        return "INSUFFICIENT EVIDENCE"
    return DRIFT_LABEL_TO_CONDITION.get(m.drift_label, "INSUFFICIENT EVIDENCE")


def validity_bit_for(condition_label: str) -> int:
    """Existing app convention: validity_bit is 0 only when evidence is insufficient."""
    return 0 if condition_label == "INSUFFICIENT EVIDENCE" else 1


def _interleave_sweep_rows(pool: List[Measurement]) -> List[Measurement]:
    """
    Redistribute the measurements in `pool` that carry a full sweep trace
    (Measurement.has_sweep_trace) so they land at roughly evenly spaced
    positions, instead of wherever the (session_id, timestamp_utc) sort
    happened to put them.

    Only 24 of the 1000 Phase 0 rows have a sweep trace, and it turns out
    all 24 sort to the very start of their scenario pool (they're the
    earliest-timestamped enrollment rows in session S1). Without this
    step, a DEMO replay shows a sweep example for the first couple of
    ticks after selecting a scenario and then none again until the whole
    pool wraps around - up to ~18 minutes for the largest pool. This
    doesn't change *what* data is shown (every row is still the dataset's
    own row, in its own right position relative to its neighbours), it
    only changes *when in the replay order* the sweep-bearing rows appear,
    so the sweep-trace chart has something to show every few dozen ticks
    instead of once per lap.
    """
    sweep_items = [m for m in pool if m.has_sweep_trace]
    if not sweep_items or len(sweep_items) >= len(pool):
        return pool

    other_items = [m for m in pool if not m.has_sweep_trace]
    n, k = len(pool), len(sweep_items)
    step = n / (k + 1)

    target_indices = []
    for i in range(k):
        idx = max(0, min(int(round(step * (i + 1))), n - 1))
        while idx in target_indices:
            idx = min(idx + 1, n - 1)
        target_indices.append(idx)

    result: List[Measurement] = [None] * n  # type: ignore[list-item]
    for idx, item in zip(sorted(target_indices), sweep_items):
        result[idx] = item

    other_iter = iter(other_items)
    for i in range(n):
        if result[i] is None:
            result[i] = next(other_iter)
    return result


def build_scenario_pools(measurements: List[Measurement]) -> Dict[str, List[Measurement]]:
    """
    Partition all measurements into the four scenario pools. Each pool is
    first sorted by (session_id, timestamp_utc) so replaying it preserves
    the dataset's own relative temporal structure within a session, then
    has its sweep-bearing rows spread out via `_interleave_sweep_rows` so
    the sweep-trace chart gets a real example on a reasonable cadence
    instead of only at the very start of a pool's replay.
    """
    pools: Dict[str, List[Measurement]] = {label: [] for label in CONDITION_LABELS}
    for m in sorted(measurements, key=lambda x: (x.session_id, x.timestamp_utc)):
        pools[classify(m)].append(m)
    return {label: _interleave_sweep_rows(pool) for label, pool in pools.items()}


if __name__ == "__main__":
    from dataset.phase0_loader import load_dataset

    ms, _ = load_dataset()
    pools = build_scenario_pools(ms)
    for label in CONDITION_LABELS:
        print(f"{label}: {len(pools[label])} rows")
