"""model/datasets/synthetic.py -- registers the existing synthetic feature CSVs
(data/features_sim.csv = sim/ run A, data/features_sim_b.csv = sim/ run B) as
"datasets" in the same sense as nasa_pcoe.py / calce.py: validates them against
features/schema.py and writes a data/manifests/*.csv manifest (battery_id,
chemistry, n_cycles, capacity_bol, capacity_eol, source_file, sha256).

This is a thin registration wrapper, not a new feature pipeline: the CSVs
already conform to the schema (they come from features/cycle_features.py run
over sim/battery_sim.py output), so there is nothing to derive here. Capacity
here is expressed the way the rest of this schema does -- SoH percent, not Ah
-- since the sim/ pipeline does not carry a literal C_rated Ah figure through
to the features CSV; that is noted in the manifest's `chemistry` field.

CLI:
    python -m model.datasets.synthetic --data data/features_sim.csv --name sim_run_a
    python -m model.datasets.synthetic --data data/features_sim_b.csv --name sim_run_b
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from features.schema import validate_columns  # noqa: E402
from model.datasets._common import sha256_file, write_manifest  # noqa: E402

REGISTRY = {
    "sim_run_a": "data/features_sim.csv",
    "sim_run_b": "data/features_sim_b.csv",
}


def build_manifest(data_path, name, chemistry="synthetic-tubular-lead-acid (sim/)"):
    data_path = Path(data_path)
    df = pd.read_csv(data_path)
    validate_columns(df.columns)
    sha = sha256_file(data_path)

    rows = []
    for bid, g in df.sort_values("cycle_idx").groupby("battery_id", sort=False):
        rows.append({
            "battery_id": str(bid),
            "chemistry": chemistry,
            "n_cycles": int(len(g)),
            "capacity_bol": float(g["soh_true"].iloc[0]),   # SoH % at first logged cycle
            "capacity_eol": float(g["soh_true"].iloc[-1]),  # SoH % at last logged cycle
            "source_file": str(data_path),
            "sha256": sha,
        })
    out_path = Path("data/manifests") / ("%s_manifest.csv" % name)
    write_manifest(rows, out_path)
    return out_path, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--name", required=True, help="manifest file stem, e.g. sim_run_a")
    args = ap.parse_args()
    out_path, rows = build_manifest(args.data, args.name)
    print("wrote %s (%d batteries)" % (out_path, len(rows)))


if __name__ == "__main__":
    main()
