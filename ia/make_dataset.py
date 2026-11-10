"""Write the versioned synthetic dataset v1 to data/ (brief 05, step C).

Run from the repository root: python -m ia.make_dataset
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import pandas as pd

from ia.generator import FEATURES, build_dataset
from ia.split import split

SEED = 42
OUT = pathlib.Path("data") / "dataset_v1.csv"
# episode_id, kind and split are metadata: they must never be used as model features
COLUMNS = [*FEATURES, "y", "episode_id", "kind", "split"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=pathlib.Path, default=OUT)
    args = parser.parse_args()

    df = build_dataset(args.seed)
    tr, va, te = split(df, args.seed)  # raises on leakage or missing scenario types

    df = df.copy()
    df["split"] = "train"
    df.loc[va.index, "split"] = "val"
    df.loc[te.index, "split"] = "test"
    df = df[COLUMNS]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # "\n" line endings: same bytes on Windows and Linux, so the file hash is comparable
    df.to_csv(args.out, index=False, lineterminator="\n")

    # round-trip check: what is on disk must equal what is in memory
    back = pd.read_csv(args.out)
    try:
        pd.testing.assert_frame_equal(df.reset_index(drop=True), back, check_dtype=False)
    except AssertionError as exc:
        print(f"FAIL round-trip: {exc}")
        return 1

    raw = args.out.read_bytes()
    print(f"file      : {args.out}  ({len(raw) / 1024 / 1024:.2f} Mo)")
    print(f"sha256    : {hashlib.sha256(raw).hexdigest()[:16]}...")
    print(f"seed      : {args.seed}")
    print(f"rows      : {len(df)}   episodes: {df['episode_id'].nunique()}")
    print("rows per class (y):")
    print(df["y"].value_counts().sort_index().to_string())
    print("episodes per kind:")
    print(df.groupby("kind")["episode_id"].nunique().to_string())
    print("rows per split:")
    print(df["split"].value_counts().to_string())
    print("OK   round-trip CSV identical to memory")
    return 0


if __name__ == "__main__":
    sys.exit(main())