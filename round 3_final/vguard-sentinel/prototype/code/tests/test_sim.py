"""Sanity tests for sim/battery_sim.py -- see sim/README.md for what is/isn't proven."""
import os

import numpy as np
import pandas as pd
import pytest

from sim.battery_sim import simulate_battery  # noqa: F401 (imported for availability check)


@pytest.fixture(scope="module")
def sim_out(tmp_path_factory):
    """Run a small (fast) 2-battery, 6-cycle simulation once and share it across tests."""
    out_dir = tmp_path_factory.mktemp("sim_out")
    from sim import battery_sim
    manifest_rows = []
    all_cycle_rows = []
    for i in range(2):
        bp, cycle_rows = battery_sim.simulate_battery(
            battery_id=i, master_seed=1, out_dir=str(out_dir), max_cycles=6,
            cycle_hours_range=(8.0, 12.0), label_noise_std=0.0, sensor_noise=True,
            float_cap_hours=2.0,
        )
        manifest_rows.append(dict(battery_id=i, C_rated_Ah=bp.C_rated, n_cycles=len(cycle_rows)))
        all_cycle_rows.extend(cycle_rows)
    pd.DataFrame(manifest_rows).to_csv(os.path.join(str(out_dir), "manifest.csv"), index=False)
    pd.DataFrame(all_cycle_rows).to_csv(os.path.join(str(out_dir), "sim_cycle_debug.csv"), index=False)
    return str(out_dir), manifest_rows, all_cycle_rows


def _load_stream(out_dir, battery_id):
    return pd.read_csv(os.path.join(out_dir, "battery_%03d.csv" % battery_id))


def test_stream_has_contract_columns(sim_out):
    out_dir, manifest, _ = sim_out
    df = _load_stream(out_dir, 0)
    for col in ("t", "I", "V", "T", "grid", "P_load", "soc_true", "soh_true"):
        assert col in df.columns


def test_voltage_within_sane_range(sim_out):
    """CONTRACTS.md sanity band for a 12V flooded lead-acid battery."""
    out_dir, manifest, _ = sim_out
    for row in manifest:
        df = _load_stream(out_dir, row["battery_id"])
        assert df["V"].min() >= 10.5 - 1e-6, "voltage dropped below inverter cutoff floor"
        assert df["V"].max() <= 14.8, "voltage exceeded the sane charging ceiling"


def test_temperature_within_sane_range(sim_out):
    out_dir, manifest, _ = sim_out
    for row in manifest:
        df = _load_stream(out_dir, row["battery_id"])
        # Chennai/Delhi ambient (0-50C) + self-heating headroom (<=20C offset)
        assert df["T"].min() > -10.0
        assert df["T"].max() < 65.0


def test_current_sign_convention(sim_out):
    """CONTRACTS.md SS1: I is +charge / -discharge. Both signs must occur."""
    out_dir, manifest, _ = sim_out
    df = _load_stream(out_dir, 0)
    assert (df["I"] > 0).any(), "no charging current observed"
    assert (df["I"] < 0).any(), "no discharging current observed"


def test_soc_monotonic_per_discharge_phase(sim_out):
    """SoC must not increase during a sustained discharge run (grid==0)."""
    out_dir, manifest, _ = sim_out
    df = _load_stream(out_dir, 0)
    grid = df["grid"].to_numpy()
    soc = df["soc_true"].to_numpy()
    # find contiguous grid==0 (discharge) runs and check SoC is non-increasing within each,
    # allowing a tiny tolerance for float noise
    in_run = False
    run_start = 0
    violations = 0
    n_checked_runs = 0
    for i in range(len(grid)):
        if grid[i] == 0 and not in_run:
            in_run = True
            run_start = i
        elif grid[i] != 0 and in_run:
            in_run = False
            seg = soc[run_start:i]
            if len(seg) > 5:
                n_checked_runs += 1
                # allow tiny upward noise (<1e-4) but not a real increase
                diffs = np.diff(seg)
                if (diffs > 2e-4).sum() > 0.02 * len(diffs):
                    violations += 1
    assert n_checked_runs > 0, "no discharge runs found to check"
    assert violations == 0, "SoC increased materially during a discharge phase"


def test_soc_bounded(sim_out):
    out_dir, manifest, _ = sim_out
    for row in manifest:
        df = _load_stream(out_dir, row["battery_id"])
        assert df["soc_true"].min() >= -0.01
        assert df["soc_true"].max() <= 1.01


def test_soh_capacity_fades_over_cycles(sim_out):
    """soh_true must be non-increasing across cycles (capacity only fades in this sim)."""
    _, _, cycle_rows = sim_out
    df = pd.DataFrame(cycle_rows)
    for bid, g in df.groupby("battery_id"):
        g = g.sort_values("cycle_idx")
        soh = g["soh_true"].to_numpy()
        assert soh[0] == pytest.approx(100.0, abs=1e-6)
        assert (np.diff(soh) <= 1e-9).all(), "soh_true increased between cycles"
        assert soh[-1] < soh[0], "soh_true did not fade at all over the run"


def test_efc_counts_accumulate(sim_out):
    """EFC = sum(Q_dis)/C_rated must be positive and monotonically increasing."""
    _, _, cycle_rows = sim_out
    df = pd.DataFrame(cycle_rows)
    for bid, g in df.groupby("battery_id"):
        g = g.sort_values("cycle_idx")
        efc = g["efc_cum"].to_numpy()
        assert efc[-1] > 0
        assert (np.diff(efc) >= -1e-9).all()


def test_r0_growth_nondecreasing(sim_out):
    _, _, cycle_rows = sim_out
    df = pd.DataFrame(cycle_rows)
    for bid, g in df.groupby("battery_id"):
        g = g.sort_values("cycle_idx")
        r0g = g["r0_growth"].to_numpy()
        assert r0g[0] == pytest.approx(1.0, abs=0.05)
        assert (np.diff(r0g) >= -1e-9).all(), "R0 growth multiplier decreased"


def test_domain_randomisation_differs_per_battery(sim_out):
    out_dir, manifest, _ = sim_out
    caps = [row["C_rated_Ah"] for row in manifest]
    assert len(set(round(c, 3) for c in caps)) == len(caps), "batteries were not domain-randomised"


def test_cli_runs_end_to_end(tmp_path):
    """python -m sim.battery_sim --n 1 ... completes and writes the expected files."""
    import subprocess
    import sys
    out_dir = str(tmp_path / "cli_out")
    result = subprocess.run(
        [sys.executable, "-m", "sim.battery_sim", "--n", "1", "--out", out_dir,
         "--seed", "2", "--cycles", "2"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert os.path.exists(os.path.join(out_dir, "manifest.csv"))
    assert os.path.exists(os.path.join(out_dir, "battery_000.csv"))
