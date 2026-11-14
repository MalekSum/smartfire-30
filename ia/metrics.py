"""Quality metrics for SmartFire-30 (brief 05, step D).

Self-test with hand-checkable numbers: python -m ia.metrics
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

N_CONFIRM = 2  # contract section 3: the alarm needs 2 consecutive "2" decisions


def evaluate(df: pd.DataFrame, y_pred) -> dict[str, float]:
    """Per-row metrics; class 2 (fire) is the positive class."""
    y = df["y"].to_numpy()
    y_pred = np.asarray(y_pred)
    if y.shape != y_pred.shape:
        raise ValueError(f"shape mismatch: {y.shape} vs {y_pred.shape}")
    p, r, f1, _ = precision_recall_fscore_support(y, y_pred, labels=[0, 1, 2], zero_division=0)
    pert, fire = y == 1, y == 2
    return {
        "precision": float(p[2]),
        "rappel": float(r[2]),
        "f1_macro": float(f1.mean()),
        "f1_incendie": float(f1[2]),
        # share of non-fire rows predicted as fire
        "taux_fausses_alarmes": float(np.mean(y_pred[y != 2] == 2)),
        # same, restricted to class 1 (cooking, steam): what SmartFire must beat
        "fa_perturbation": float(np.mean(y_pred[pert] == 2)) if pert.any() else math.nan,
        # share of fire rows not predicted as fire
        "taux_manques": float(np.mean(y_pred[fire] != 2)),
    }


def delai_detection(df: pd.DataFrame, y_pred, n_confirm: int = N_CONFIRM) -> tuple[float, int]:
    """Mean delay (s) between the first fire label and the first confirmed alarm,
    and the number of fire episodes never detected."""
    tmp = pd.DataFrame({"episode_id": df["episode_id"].to_numpy(),
                        "y": df["y"].to_numpy(), "p": np.asarray(y_pred)})
    delays: list[int] = []
    missed = 0
    for _, g in tmp.groupby("episode_id", sort=False):  # rows are chronological in an episode
        y, p = g["y"].to_numpy(), g["p"].to_numpy()
        if not (y == 2).any():
            continue
        onset, run, found = int(np.argmax(y == 2)), 0, None
        for i in range(onset, len(p)):
            run = run + 1 if p[i] == 2 else 0
            if run >= n_confirm:
                found = i - onset
                break
        if found is None:
            missed += 1
        else:
            delays.append(found)
    return (float(np.mean(delays)) if delays else math.nan), missed


def _selftest() -> None:
    df = pd.DataFrame({"episode_id": [0] * 6, "y": [0, 0, 2, 2, 2, 2]})
    pred = [0, 2, 0, 2, 2, 2]
    m = evaluate(df, pred)
    # predicted 2 on rows 1,3,4,5 (4 rows), 3 of them true fire: precision 3/4 ; recall 3/4
    assert m["precision"] == 0.75 and m["rappel"] == 0.75
    assert m["taux_fausses_alarmes"] == 0.5   # non-fire rows 0,1 -> predictions [0, 2]
    assert m["taux_manques"] == 0.25          # fire rows 2..5 -> predictions [0, 2, 2, 2]
    assert math.isnan(m["fa_perturbation"])   # no class 1 row
    assert delai_detection(df, pred) == (2.0, 0)  # onset 2, run reaches 2 at row 4
    mean, missed = delai_detection(df, [0] * 6)
    assert math.isnan(mean) and missed == 1
    print("OK   metrics self-test (hand-computed values)")


if __name__ == "__main__":
    _selftest()