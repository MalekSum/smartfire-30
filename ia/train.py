"""Compare the classic detector and the models on the episode split (brief 05, step D).

Run from the repository root: python -m ia.train
Writes docs/resultats/qualite.csv (contract section 9 column order, extra columns at the end).
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier

from ia.generator import FEATURES, build_dataset
from ia.metrics import delai_detection, evaluate
from ia.split import split

SEEDS = (1, 2, 3, 4, 5)   # mean and std over these seeds; the deployed model (seed 42) comes in steps G/H
SEUIL_CLASSIQUE = 2000    # contract section 3
OUT = Path("docs") / "resultats" / "qualite.csv"
CONTRACT_COLUMNS = ["modele", "split", "precision", "rappel", "f1_macro", "f1_incendie",
                    "taux_fausses_alarmes", "delai_detection_s", "taille_ko", "seed"]
EXTRA_COLUMNS = ["fa_perturbation", "taux_manques", "incendies_manques"]
SUMMARY_COLUMNS = ["f1_incendie", "taux_fausses_alarmes", "fa_perturbation",
                   "taux_manques", "delai_detection_s", "taille_ko"]


def make_models(seed: int) -> dict:
    """Hyperparameters of the brief, not tuned yet."""
    return {
        "baseline_arbre": DecisionTreeClassifier(max_depth=4, random_state=seed),
        "edge_rf": RandomForestClassifier(n_estimators=8, max_depth=6, random_state=seed),
        "fog_rf": RandomForestClassifier(n_estimators=100, max_depth=12, random_state=seed, n_jobs=-1),
        # early_stopping=False: do the 300 iterations of the brief; the default would hold out
        # 10 % of the training rows at random, rows of the same episode being near-duplicates
        "cloud_hgb": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                                    early_stopping=False, random_state=seed),
    }


def size_ko(model) -> float:
    """Size of the serialised model in Ko (joblib), measured in memory."""
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return round(buf.getbuffer().nbytes / 1024, 1)


def make_row(name: str, sp: str, seed: int, d: pd.DataFrame, pred, size: float) -> dict:
    delay, missed = delai_detection(d, pred)
    return {"modele": name, "split": sp, "seed": seed, "delai_detection_s": delay,
            "taille_ko": size, "incendies_manques": missed, **evaluate(d, pred)}


def run_seed(seed: int) -> list[dict]:
    tr, va, te = split(build_dataset(seed), seed)
    X = lambda d: d[FEATURES].to_numpy(dtype=float)
    rows = []
    for sp, d in (("val", va), ("test", te)):
        pred = np.where(d["gaz"].to_numpy() >= SEUIL_CLASSIQUE, 2, 0)  # classic detector
        rows.append(make_row("detecteur_seuil", sp, seed, d, pred, math.nan))
    for name, model in make_models(seed).items():
        model.fit(X(tr), tr["y"].to_numpy())  # fitted on train only
        size = size_ko(model)
        for sp, d in (("val", va), ("test", te)):
            rows.append(make_row(name, sp, seed, d, model.predict(X(d)), size))
    return rows


def mean_std(s: pd.Series) -> str:
    return f"{s.mean():.3f} +/- {s.std():.3f}"  # sample std (ddof=1) over the seeds


def main() -> int:
    rows: list[dict] = []
    for seed in SEEDS:
        rows += run_seed(seed)
        print(f"seed {seed} done", flush=True)
    out = pd.DataFrame(rows)[CONTRACT_COLUMNS + EXTRA_COLUMNS].round(6)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, lineterminator="\n")

    test = out[out["split"] == "test"]
    table = pd.DataFrame({c: test.groupby("modele", sort=False)[c].apply(mean_std)
                          for c in SUMMARY_COLUMNS})
    pd.set_option("display.width", 220)
    print(f"\ntest split, mean +/- std over seeds {SEEDS} [M]")
    print(table.to_string())

    no_gap = out.drop(columns=["taille_ko", "delai_detection_s"]).isna().sum().sum() == 0
    checks = {
        f"{len(out)} rows = 5 models x 2 splits x {len(SEEDS)} seeds": len(out) == 5 * 2 * len(SEEDS),
        "columns start with the contract order": list(out.columns[:10]) == CONTRACT_COLUMNS,
        "no missing metric value": bool(no_gap),
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    print(f"written: {OUT}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())