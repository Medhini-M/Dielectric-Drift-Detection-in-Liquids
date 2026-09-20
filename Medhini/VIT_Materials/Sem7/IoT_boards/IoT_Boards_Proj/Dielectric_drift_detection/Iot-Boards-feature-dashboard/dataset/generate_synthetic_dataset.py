"""
Synthetic dataset generator — Provenance-Gated Dielectric Drift Detection prototype.

Generates a single flat CSV covering:
  - multiple vials, cradle angles, repeats, antennas
  - a fixed excitation frequency (2.8 GHz)
  - varying ambient temperature, condition label (control/stressed),
    injected corruption modes, gate_enabled states
  - a physically consistent dielectric_constant that DRIVES amplitude_db
    and phase_deg (not an independent random column)

Requirements:
    pip install pandas numpy

Run:
    python generate_synthetic_dataset.py

Output:
    synthetic_dielectric_dataset.csv  (>= 1000 rows)
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config / reproducibility
# ---------------------------------------------------------------------------
SEED = 42
rng = np.random.default_rng(SEED)

VIALS = [f"V{i:02d}" for i in range(1, 11)]          # 10 vials
ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]          # 8 indexed cradle stops
REPEATS = [1, 2, 3]                                     # 3 repeats per placement
ANTENNAS = [f"A{i}" for i in range(1, 7)]              # 6 antennas
FREQUENCY_HZ = 2.8e9                                    # fixed, per instructions

CORRUPTION_TYPES = ["displaced", "loosened", "interference"]
GATE_STATES = [True, False]

# Half the vial pool is designated "stressed" (heat-exposed surrogate),
# half stays "control" — mirrors the synopsis's Phase 1 stress-vs-control design.
CONDITION_MAP = {v: ("stressed" if i % 2 == 1 else "control")
                  for i, v in enumerate(VIALS)}

# Dielectric constant (real part, eps_r) — nominal ranges from the literature
# review (saline sits close to DI water, eps_r ~ 65-80 in the 1-2.5 GHz band).
EPS_MIN, EPS_MAX = 65.0, 80.0
EPS_CONTROL_MEAN, EPS_CONTROL_STD = 74.0, 0.4
EPS_STRESSED_MEAN, EPS_STRESSED_STD = 69.5, 0.6

VALIDITY_RESIDUAL_THRESHOLD = 3.0   # combined amp/phase residual cutoff for validity_bit
CORRUPTION_ROWS_PER_COMBO = 5        # repeats per (vial, corruption, gate) combo


# ---------------------------------------------------------------------------
# Physical model helpers
# ---------------------------------------------------------------------------
def sample_dielectric(condition):
    """Draw eps_r for a given vial/session, condition-dependent, clipped to range."""
    if condition == "control":
        val = rng.normal(EPS_CONTROL_MEAN, EPS_CONTROL_STD)
    else:
        val = rng.normal(EPS_STRESSED_MEAN, EPS_STRESSED_STD)
    return float(np.clip(val, EPS_MIN, EPS_MAX))


def eps_to_amp_phase(eps, angle_deg, antenna_idx, corrupted=False):
    """
    Map a latent dielectric constant to simulated amplitude/phase readings,
    with small placement- and antenna-dependent offsets plus measurement noise.
    Corrupted acquisitions get an extra large, non-physical perturbation.
    """
    eps_frac = (eps - EPS_MIN) / (EPS_MAX - EPS_MIN)  # 0..1

    # Amplitude ratio: -30 dB (low eps) to 0 dB (high eps), plus small
    # placement/antenna structure and Gaussian measurement noise.
    base_amp = -30.0 + eps_frac * 30.0
    placement_offset_amp = 0.5 * np.sin(np.radians(angle_deg)) + 0.3 * (antenna_idx % 3)
    amp_noise = rng.normal(0, 0.3)
    amplitude_db = base_amp + placement_offset_amp + amp_noise

    # Phase difference: -180 to +180 deg sweep with eps, plus placement offset + noise.
    base_phase = -180.0 + eps_frac * 360.0
    placement_offset_phase = 1.0 * np.sin(np.radians(angle_deg)) + 0.5 * (antenna_idx % 3)
    phase_noise = rng.normal(0, 3.0)
    phase_deg = ((base_phase + placement_offset_phase + phase_noise + 180.0) % 360.0) - 180.0

    if corrupted:
        amplitude_db += rng.normal(0, 5.0)     # gross, non-physical shift
        phase_deg += rng.normal(0, 25.0)
        phase_deg = ((phase_deg + 180.0) % 360.0) - 180.0

    return round(float(amplitude_db), 3), round(float(phase_deg), 3)


def sample_ambient_temp(session_base_temp):
    """Small within-session jitter around a per-session base ambient temperature."""
    return round(float(np.clip(rng.normal(session_base_temp, 0.3), 18.0, 30.0)), 2)


# ---------------------------------------------------------------------------
# Baseline (non-corrupted) dataset: enrollment + routine measurements
# ---------------------------------------------------------------------------
def generate_baseline_records():
    rows = []
    record_counter = 1
    session_counter = 1

    for vial in VIALS:
        condition = CONDITION_MAP[vial]

        # --- Enrollment session: session 0 for this vial ---
        enrollment_session_id = session_counter
        session_counter += 1
        session_base_temp = float(rng.uniform(20.0, 27.0))
        eps_enroll = sample_dielectric(condition)

        for angle in ANGLES:
            for antenna_idx, antenna in enumerate(ANTENNAS, start=1):
                for repeat in REPEATS:
                    amp, phase = eps_to_amp_phase(eps_enroll, angle, antenna_idx)
                    rows.append({
                        "record_id": f"REC{record_counter:06d}",
                        "session_id": enrollment_session_id,
                        "vial_id": vial,
                        "cradle_angle_deg": angle,
                        "repeat_index": repeat,
                        "antenna_id": antenna,
                        "frequency_hz": FREQUENCY_HZ,
                        "amplitude_db": amp,
                        "phase_deg": phase,
                        "temp_ambient_c": sample_ambient_temp(session_base_temp),
                        "condition_label": condition,
                        "is_enrollment": True,
                        "injected_corruption": "none",
                        "gate_enabled": True,
                        "dielectric_constant": round(eps_enroll, 3),
                    })
                    record_counter += 1

        # --- Routine (non-enrollment) session for the same vial ---
        routine_session_id = session_counter
        session_counter += 1
        session_base_temp = float(rng.uniform(20.0, 27.0))
        eps_routine = sample_dielectric(condition)

        # Fewer angle/antenna combos for the routine session to keep dataset balanced
        routine_angles = rng.choice(ANGLES, size=5, replace=False)
        routine_antennas = rng.choice(ANTENNAS, size=4, replace=False)

        for angle in routine_angles:
            for antenna_idx, antenna in enumerate(routine_antennas, start=1):
                for repeat in REPEATS:
                    amp, phase = eps_to_amp_phase(eps_routine, angle, antenna_idx)
                    rows.append({
                        "record_id": f"REC{record_counter:06d}",
                        "session_id": routine_session_id,
                        "vial_id": vial,
                        "cradle_angle_deg": int(angle),
                        "repeat_index": repeat,
                        "antenna_id": antenna,
                        "frequency_hz": FREQUENCY_HZ,
                        "amplitude_db": amp,
                        "phase_deg": phase,
                        "temp_ambient_c": sample_ambient_temp(session_base_temp),
                        "condition_label": condition,
                        "is_enrollment": False,
                        "injected_corruption": "none",
                        "gate_enabled": True,
                        "dielectric_constant": round(eps_routine, 3),
                    })
                    record_counter += 1

    return rows, record_counter, session_counter


# ---------------------------------------------------------------------------
# Corruption ablation records: same vials, paired gated/ungated runs
# ---------------------------------------------------------------------------
def generate_corruption_records(record_counter, session_counter):
    rows = []
    ablation_vials = VIALS[:6]  # subset is enough to exercise the ablation

    for vial in ablation_vials:
        condition = CONDITION_MAP[vial]
        for corruption in CORRUPTION_TYPES:
            corruption_session_id = session_counter
            session_counter += 1
            session_base_temp = float(rng.uniform(20.0, 27.0))
            eps_val = sample_dielectric(condition)

            for gate_enabled in GATE_STATES:
                for i in range(CORRUPTION_ROWS_PER_COMBO):
                    angle = int(rng.choice(ANGLES))
                    antenna_idx = int(rng.integers(1, len(ANTENNAS) + 1))
                    antenna = ANTENNAS[antenna_idx - 1]
                    amp, phase = eps_to_amp_phase(
                        eps_val, angle, antenna_idx, corrupted=True
                    )
                    rows.append({
                        "record_id": f"REC{record_counter:06d}",
                        "session_id": corruption_session_id,
                        "vial_id": vial,
                        "cradle_angle_deg": angle,
                        "repeat_index": i + 1,
                        "antenna_id": antenna,
                        "frequency_hz": FREQUENCY_HZ,
                        "amplitude_db": amp,
                        "phase_deg": phase,
                        "temp_ambient_c": sample_ambient_temp(session_base_temp),
                        "condition_label": condition,
                        "is_enrollment": False,
                        "injected_corruption": corruption,
                        "gate_enabled": bool(gate_enabled),
                        "dielectric_constant": round(eps_val, 3),
                    })
                    record_counter += 1

    return rows, record_counter, session_counter


# ---------------------------------------------------------------------------
# validity_bit: computed from deviation against each vial's own enrollment
# reference, not injected as ground truth.
# ---------------------------------------------------------------------------
def compute_validity_bit(df):
    ref = (
        df[df["is_enrollment"]]
        .groupby("vial_id")[["amplitude_db", "phase_deg"]]
        .mean()
        .rename(columns={"amplitude_db": "ref_amp", "phase_deg": "ref_phase"})
    )
    df = df.merge(ref, on="vial_id", how="left")

    residual = np.sqrt(
        (df["amplitude_db"] - df["ref_amp"]) ** 2
        + ((df["phase_deg"] - df["ref_phase"]) / 10.0) ** 2  # scale phase into a comparable range
    )
    df["residual"] = residual.round(3)
    df["validity_bit"] = df["residual"] < VALIDITY_RESIDUAL_THRESHOLD
    df = df.drop(columns=["ref_amp", "ref_phase"])
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    baseline_rows, record_counter, session_counter = generate_baseline_records()
    corruption_rows, record_counter, session_counter = generate_corruption_records(
        record_counter, session_counter
    )

    df = pd.DataFrame(baseline_rows + corruption_rows)
    df = compute_validity_bit(df)

    # Reorder columns to match the finalized table
    column_order = [
        "record_id", "session_id", "vial_id", "cradle_angle_deg", "repeat_index",
        "antenna_id", "frequency_hz", "amplitude_db", "phase_deg",
        "temp_ambient_c", "condition_label", "is_enrollment",
        "injected_corruption", "gate_enabled", "validity_bit",
        "dielectric_constant", "residual",
    ]
    df = df[column_order]

    assert len(df) >= 1000, f"Only generated {len(df)} rows, need >= 1000"

    out_path = "synthetic_dielectric_dataset.csv"
    df.to_csv(out_path, index=False)

    print(f"Generated {len(df)} records -> {out_path}")
    print("\nCondition label counts:\n", df["condition_label"].value_counts())
    print("\nInjected corruption counts:\n", df["injected_corruption"].value_counts())
    print("\nGate enabled counts:\n", df["gate_enabled"].value_counts())
    print("\nValidity bit counts:\n", df["validity_bit"].value_counts())
    print("\nDielectric constant summary by condition:\n",
          df.groupby("condition_label")["dielectric_constant"].describe())


if __name__ == "__main__":
    main()
