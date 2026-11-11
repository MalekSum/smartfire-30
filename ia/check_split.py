"""Acceptance checks for the episode split (run: python -m ia.check_split)."""
from __future__ import annotations

import sys

import pandas as pd

from ia.generator import build_dataset
from ia.split import split, summarize

SEEDS = (1, 2, 3, 4, 5, 42)  # the 5 evaluation seeds of the brief + the deployed one


def main() -> int:
    df = build_dataset(seed=42)
    tr, va, te = split(df, seed=42)  # raises on leakage or missing scenario types
    pd.set_option("display.width", 220)
    print(summarize(tr, va, te).to_string(index=False))

    tr2, va2, te2 = split(df, seed=42)
    reproducible = (
        tr.index.equals(tr2.index) and va.index.equals(va2.index) and te.index.equals(te2.index)
    )
    # dt is computed inside each episode: its first 5 rows must have dt == 0
    dt_inside_episode = bool((df.groupby("episode_id").head(5)["dt"] == 0).all())
    all_rows_used = len(tr) + len(va) + len(te) == len(df)

    seeds_ok = True
    for seed in SEEDS:
        try:
            split(build_dataset(seed), seed)
        except ValueError as exc:
            print(f"seed {seed}: {exc}")
            seeds_ok = False

    checks = {
        "no episode shared between splits (checked in split())": True,
        "same seed gives the same split": reproducible,
        "every row is in exactly one split": all_rows_used,
        "dt == 0 on the first 5 rows of every episode": dt_inside_episode,
        f"all scenario types in every split for seeds {SEEDS}": seeds_ok,
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())