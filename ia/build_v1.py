"""Train the deployed Fog and Cloud models v1 (seed 42) and publish all 3 layers.

Run from the repository root: python -m ia.build_v1
Hyperparameters are those of the brief, not tuned. Models are fitted on train only.
The test set is read for the final figures only (not for any choice).
"""
from __future__ import annotations

import json
import pathlib
import sys

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

from ia.generator import FEATURES, build_dataset
from ia.metrics import evaluate
from ia.publish_model import REGISTRY, ROOT, publish
from ia.split import split

SEED, MV = 42, 1


def main() -> int:
    df = build_dataset(SEED)
    tr, va, te = split(df, SEED)
    X = lambda d: d[FEATURES].to_numpy(dtype=float)  # order imposed by the contract

    models = {
        "fog": RandomForestClassifier(n_estimators=100, max_depth=12, random_state=SEED, n_jobs=-1),
        # early_stopping=False: same deviation from the brief as in train.py
        "cloud": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                                early_stopping=False, random_state=SEED),
    }
    for layer, m in models.items():
        m.fit(X(tr), tr["y"])
        path = ROOT / "models" / layer / f"model_{layer}_v{MV}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(m, path)
        r = evaluate(te, m.predict(X(te)))
        metrics = {"seed": SEED, "split": "test", "f1_incendie": round(r["f1_incendie"], 4),
                   "taux_fausses_alarmes": round(r["taux_fausses_alarmes"], 4),
                   "taille_ko": round(path.stat().st_size / 1024, 1)}
        publish(layer, path, MV, metrics)
        print(f"{layer:5s} v{MV}: {metrics}")

    # edge: model_edge_v1.joblib already exported by ia.export_edge (variant brief)
    edge_path = ROOT / "models" / "edge" / f"model_edge_v{MV}.joblib"
    edge = joblib.load(edge_path)
    r = evaluate(te, edge.predict(X(te)))
    publish("edge", edge_path, MV, {
        "seed": SEED, "split": "test", "variant": "8 trees, depth 6", "model_h": "edge/model.h",
        "f1_incendie": round(r["f1_incendie"], 4),
        "taux_fausses_alarmes": round(r["taux_fausses_alarmes"], 4),
        "taille_ko": round(edge_path.stat().st_size / 1024, 1)})
    print(f"edge  v{MV}: published")

    # acceptance checks
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checks = {
        "registry has edge, fog, cloud": set(reg) == {"edge", "fog", "cloud"},
        "mv == 1 for the 3 layers": all(reg[k]["mv"] == MV for k in reg),
        "files exist and reload": all(
            joblib.load(ROOT / "models" / k / reg[k]["file"]) is not None for k in reg),
        "fog predicts class 0 on a normal case": int(
            joblib.load(ROOT / "models" / "fog" / reg["fog"]["file"]).predict(
                np.array([[24.0, 45.0, 400, 0, 0.0]]))[0]) == 0,
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())