"""Episode-level train/validation/test split (brief 05, step C).

Rows of one episode are almost identical from one second to the next, so the
split is done on whole episodes to avoid leakage between train and test.
"""
from __future__ import annotations

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

REQUIRED_KINDS = frozenset({"normal", "cuisson", "vapeur", "incendie", "couvant"})
REQUIRED_COLUMNS = ("episode_id", "kind", "y")


def split(df: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (train, val, test) = 70 % / 15 % / 15 % of the episodes."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")

    # 70 % of the episodes for training, 30 % kept aside
    first = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=seed)
    tr_idx, rest_idx = next(first.split(df, groups=df["episode_id"]))
    d_tr, d_rest = df.iloc[tr_idx], df.iloc[rest_idx]

    # the 30 % is halved: 15 % validation, 15 % test
    second = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=seed)
    va_idx, te_idx = next(second.split(d_rest, groups=d_rest["episode_id"]))
    d_va, d_te = d_rest.iloc[va_idx], d_rest.iloc[te_idx]

    check_split(d_tr, d_va, d_te)
    return d_tr, d_va, d_te


def check_split(tr: pd.DataFrame, va: pd.DataFrame, te: pd.DataFrame) -> None:
    """Raise ValueError on leakage or when a split lacks a scenario type."""
    sets = {
        "train": set(tr["episode_id"]),
        "val": set(va["episode_id"]),
        "test": set(te["episode_id"]),
    }
    names = list(sets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = sets[a] & sets[b]
            if common:
                raise ValueError(f"leakage: {len(common)} episodes in both {a} and {b}")

    for name, d in (("train", tr), ("val", va), ("test", te)):
        absent = REQUIRED_KINDS - set(d["kind"])
        if absent:
            raise ValueError(f"{name} lacks scenario types {sorted(absent)}: change the seed")


def summarize(tr: pd.DataFrame, va: pd.DataFrame, te: pd.DataFrame) -> pd.DataFrame:
    """Counts per split: episodes, rows, episodes per scenario type, rows per class."""
    rows = []
    for name, d in (("train", tr), ("val", va), ("test", te)):
        per_kind = d.groupby("kind")["episode_id"].nunique()
        row = {"split": name, "episodes": int(d["episode_id"].nunique()), "rows": len(d)}
        row.update({f"ep_{k}": int(per_kind.get(k, 0)) for k in sorted(REQUIRED_KINDS)})
        row.update({f"y{c}": int((d["y"] == c).sum()) for c in (0, 1, 2)})
        rows.append(row)
    return pd.DataFrame(rows)