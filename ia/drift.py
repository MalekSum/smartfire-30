"""Drift detection (brief 05, step I). Run: python -m ia.drift

KS distance between a reference (normal rows of train) and recent normal rows.
Offline demo: sensor ageing simulated as gaz + 400 on a fresh normal dataset.
Online mode: pass --url http://localhost:8000 to read GET /api/export?limit=1000.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from ia.generator import FEATURES, build_dataset
from ia.split import split

KS_THRESHOLD = 0.2  # effect-size threshold, not a p-value (p is always tiny with thousands of rows)


def drift_report(ref: pd.DataFrame, recent: pd.DataFrame, seuil: float = KS_THRESHOLD,
                 n: int = 1000, seed: int = 0) -> dict:
    """KS statistic per feature (0 = same distribution, 1 = disjoint)."""
    rng = np.random.default_rng(seed)
    out = {}
    for f in FEATURES:
        a = rng.choice(ref[f].to_numpy(), size=min(n, len(ref)), replace=False)
        b = rng.choice(recent[f].to_numpy(), size=min(n, len(recent)), replace=False)
        stat = float(ks_2samp(a, b).statistic)
        out[f] = {"ks": round(stat, 3), "derive": stat > seuil}
    return out


def reference_normal(seed: int = 42) -> pd.DataFrame:
    """Reference = normal rows (y == 0) of the TRAIN split only."""
    tr, _, _ = split(build_dataset(seed), seed)
    return tr[tr["y"] == 0]


def recent_from_api(url: str) -> pd.DataFrame:
    import requests  # not in ia/requirements.txt: only needed in online mode
    rows = requests.get(f"{url}/api/export?limit=1000", timeout=10).json()
    df = pd.DataFrame(rows)
    return df[df["y_final"] == 0]  # recent rows judged normal


def simulated_recent(shift_gaz: float, seed: int = 7) -> pd.DataFrame:
    """Fresh normal rows (other seed), with an optional gaz offset (ageing sensor)."""
    df = build_dataset(seed)
    d = df[(df["kind"] == "normal")].copy()
    d["gaz"] = np.clip(d["gaz"] + shift_gaz, 0, 4095)
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=None, help="Cloud API base URL (online mode)")
    args = ap.parse_args()

    ref = reference_normal()
    if args.url:
        print(drift_report(ref, recent_from_api(args.url)))
        return 0

    rep0 = drift_report(ref, simulated_recent(0))
    rep1 = drift_report(ref, simulated_recent(400))
    print("no drift (gaz +0)  :", {f: v["ks"] for f, v in rep0.items()})
    print("drift    (gaz +400):", {f: v["ks"] for f, v in rep1.items()})
    checks = {
        "no feature flagged without drift": not any(v["derive"] for v in rep0.values()),
        "gaz flagged with gaz +400": rep1["gaz"]["derive"],
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())