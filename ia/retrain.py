"""Retraining after drift (brief 05, step I). Run: python -m ia.retrain

Offline demo: sensor ageing = gaz + SHIFT on freshly generated labelled episodes (y_true known).
Online mode: build `new` from GET /api/export rows that carry y_true (see ia.drift.recent_from_api).
Fits Fog and Cloud on train + new labelled data, evaluates on the OLD test and on UNSEEN drifted
data, publishes mv = 2 only if the checks pass. The compiled Edge model is NOT retrained:
it needs a new firmware (documented limit).
"""
from __future__ import annotations

import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

from ia.drift import KS_THRESHOLD, drift_report, reference_normal
from ia.generator import FEATURES, build_dataset
from ia.metrics import evaluate
from ia.publish_model import ROOT, publish
from ia.split import split

SEED, SHIFT, MV_NEW = 42, 400, 2
F1_ALERT = 0.90  # retraining criterion (a): rolling F1 below 0.90


def drifted(seed: int) -> pd.DataFrame:
    """Labelled episodes seen through an ageing gaz sensor (gaz + SHIFT, clipped to ADC range)."""
    d = build_dataset(seed).copy()
    d["gaz"] = np.clip(d["gaz"] + SHIFT, 0, 4095)
    return d


def X(d: pd.DataFrame) -> np.ndarray:
    return d[FEATURES].to_numpy(dtype=float)  # contract order


def new_models() -> dict:
    return {
        "fog": RandomForestClassifier(n_estimators=100, max_depth=12, random_state=SEED, n_jobs=-1),
        "cloud": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                                early_stopping=False, random_state=SEED),
    }


def main() -> int:
    tr, _, te = split(build_dataset(SEED), SEED)
    new = drifted(seed=11)          # labelled data received after the drift (used to retrain)
    new_eval = drifted(seed=12)     # other drifted data, NEVER used for fitting

    # 1. criterion (b): KS on normal rows
    ks = drift_report(reference_normal(SEED), new[new["y"] == 0])
    flagged = [f for f, v in ks.items() if v["derive"]]
    print("KS (normal rows):", {f: v["ks"] for f, v in ks.items()}, "-> drift on", flagged)

    # 2. criterion (a): v1 models on drifted data (F1 fire, fire = class 2)
    v1 = {l: joblib.load(ROOT / "models" / l / f"model_{l}_v1.joblib") for l in ("fog", "cloud")}
    before = {l: evaluate(new_eval, m.predict(X(new_eval))) for l, m in v1.items()}
    for l, r in before.items():
        print(f"v1 {l:5s} on drifted data: F1 fire {r['f1_incendie']:.4f}, "
              f"false alarms {r['taux_fausses_alarmes']:.4f}  [M]")
    need = bool(flagged) or any(r["f1_incendie"] < F1_ALERT for r in before.values())
    print("retraining needed:", need)

    # 3. retrain on train + new labelled data, then evaluate
    train_all = pd.concat([tr, new], ignore_index=True)
    ok_all = need
    for layer, m in new_models().items():
        m.fit(X(train_all), train_all["y"])
        old = evaluate(te, m.predict(X(te)))
        fresh = evaluate(new_eval, m.predict(X(new_eval)))
        print(f"v2 {layer:5s} old test: F1 {old['f1_incendie']:.4f} | drifted unseen: "
              f"F1 {fresh['f1_incendie']:.4f}, false alarms {fresh['taux_fausses_alarmes']:.4f}  [M]")
        good = fresh["f1_incendie"] >= before[layer]["f1_incendie"] and old["f1_incendie"] >= F1_ALERT
        ok_all = ok_all and good
        if need and good:
            path = ROOT / "models" / layer / f"model_{layer}_v{MV_NEW}.joblib"
            joblib.dump(m, path)
            publish(layer, path, MV_NEW, {
                "seed": SEED, "retrained_on": "train + drifted labelled data (gaz +400)",
                "f1_incendie_old_test": round(old["f1_incendie"], 4),
                "f1_incendie_drifted_unseen": round(fresh["f1_incendie"], 4),
                "taille_ko": round(path.stat().st_size / 1024, 1)})

    checks = {
        "drift flagged on gaz": "gaz" in flagged,
        "v2 not worse than v1 on drifted data, and F1 >= 0.90 on old test": ok_all,
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())