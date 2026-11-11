"""Export the Edge model v1 and the ESP32 test set (brief 05, steps E and F).

Run after `python -m ia.compress`, from the repository root:
    python -m ia.export_edge [--variant chosen|brief]
Writes: models/edge/model_edge_v1.joblib, edge/model.h, edge/test_data.h
Also measures soft vote (scikit-learn) vs hard vote (what the generated C code does).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from micromlgen import port
from sklearn.ensemble import RandomForestClassifier

from ia.compress import X_of, fit, prepare
from ia.generator import FEATURES
from ia.metrics import delai_detection, evaluate

SEED = 42  # the deployed model comes from seed 42 (brief step D)
# variant selected by ia/compress.py on the validation split (rule: smallest within 0.01 of best F1)
CHOSEN = {"lever": "distille", "n": 4, "depth": 4, "ccp": 0.0}
BRIEF = {"lever": "reduit", "n": 8, "depth": 6, "ccp": 0.0}  # contract: about 8 trees, depth 6
EDGE = Path("edge")
MODEL_H, TEST_H = EDGE / "model.h", EDGE / "test_data.h"
MODEL_JOBLIB = Path("models") / "edge" / "model_edge_v1.joblib"
N_TEST = 500

C_HARNESS = r'''#include <cstdint>
#include <cstdio>
#define PROGMEM
#include "model.h"
#include "test_data.h"
int main() {
  Eloquent::ML::Port::RandomForest clf;
  for (int i = 0; i < NS; i++) {
    float x[NF];
    for (int j = 0; j < NF; j++) x[j] = X_TEST[i][j];
    std::printf("%d\n", clf.predict(x));
  }
  return 0;
}
'''


def hard_vote(rf: RandomForestClassifier, X: np.ndarray) -> np.ndarray:
    """Majority of the per-tree class decisions, ties to the lowest class index.
    Hypothesis about the generated C code, confirmed or not by the C test below."""
    votes = np.zeros((len(X), 3), dtype=int)
    rows = np.arange(len(X))
    for tree in rf.estimators_:
        votes[rows, tree.predict(X).astype(int)] += 1
    return votes.argmax(axis=1)


def check_header(text: str) -> dict[str, bool]:
    """Frozen C++ interface of the contract (section 7)."""
    idx = {int(i) for i in re.findall(r"x\[(\d+)\]", text)}
    return {
        "namespace Eloquent::ML::Port": all(f"namespace {n}" in text for n in ("Eloquent", "ML", "Port")),
        "class RandomForest": "class RandomForest" in text,
        "int predict(float *x)": "int predict(float *x)" in text,
        "features used within x[0]..x[4]": bool(idx) and idx <= set(range(len(FEATURES))),
    }


def write_test_header(X: np.ndarray, y: np.ndarray, path: Path) -> None:
    rows = ["{" + ", ".join(f"{v:.4f}f" for v in r) + "}" for r in X]
    labels = ", ".join(str(int(v)) for v in y)
    text = (f"#define NS {len(X)}\n#define NF {len(FEATURES)}\n"
            "const float X_TEST[NS][NF] PROGMEM = {\n" + ",\n".join(rows) + "\n};\n"
            f"const uint8_t Y_TEST[NS] PROGMEM = {{{labels}}};\n")
    path.write_text(text, encoding="utf-8", newline="\n")


def c_predictions() -> np.ndarray | None:
    """Compile edge/model.h with g++ and run it on test_data.h; None if no compiler."""
    gxx = shutil.which("g++")
    if gxx is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "harness.cpp", Path(tmp) / "harness.exe"
        src.write_text(C_HARNESS, encoding="utf-8")
        try:
            subprocess.run([gxx, "-std=c++11", "-I", str(EDGE.resolve()), str(src), "-o", str(exe)],
                           check=True, capture_output=True, text=True, timeout=120)
            out = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print("C harness failed:", getattr(exc, "stderr", exc))
            return None
    return np.array([int(v) for v in out.stdout.split()])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("chosen", "brief"), default="brief")
    args = parser.parse_args()

    tr, va, te, transfer, pseudo = prepare(SEED)
    models = {"chosen": fit(CHOSEN, SEED, tr, transfer, pseudo),
              "brief": fit(BRIEF, SEED, tr, transfer, pseudo)}

    rows = []
    for label, model in models.items():
        for sp, d in (("val", va), ("test", te)):
            X = X_of(d)
            soft, hard = model.predict(X), hard_vote(model, X)
            for mode, pred in (("soft", soft), ("hard", hard)):
                ev, (delay, _) = evaluate(d, pred), delai_detection(d, pred)
                rows.append({"variant": label, "split": sp, "vote": mode,
                             "f1_incendie": ev["f1_incendie"],
                             "fausses_alarmes": ev["taux_fausses_alarmes"],
                             "manques": ev["taux_manques"], "delai_s": delay,
                             "rows_soft_ne_hard": float(np.mean(soft != hard))})
    pd.set_option("display.width", 200)
    print(f"seed {SEED}, soft = scikit-learn, hard = per-tree vote like the C code [M]")
    print(pd.DataFrame(rows).round(4).to_string(index=False))

    rf = models[args.variant]
    MODEL_JOBLIB.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, MODEL_JOBLIB)
    EDGE.mkdir(exist_ok=True)
    with open(MODEL_H, "w", encoding="utf-8", newline="\n") as f:
        f.write(port(rf))
    checks = check_header(MODEL_H.read_text(encoding="utf-8"))

    # 500 test rows rounded to 4 decimals: exactly the values the C code will see
    idx = np.random.default_rng(0).choice(len(te), size=N_TEST, replace=False)
    Xs = np.round(X_of(te)[idx], 4)
    ys = te["y"].to_numpy()[idx]
    write_test_header(Xs, ys, TEST_H)
    soft, hard = rf.predict(Xs), hard_vote(rf, Xs)

    print(f"\nexported variant: {args.variant} ({rf.n_estimators} trees, depth {rf.max_depth}) [M]")
    print(f"model.h {MODEL_H.stat().st_size / 1024:.1f} Ko (C source, not the Flash footprint), "
          f"joblib {MODEL_JOBLIB.stat().st_size / 1024:.1f} Ko")
    print(f"accuracy on the {N_TEST} rows of test_data.h: soft {np.mean(soft == ys):.4f}, "
          f"hard {np.mean(hard == ys):.4f} [M]")
    print(f"soft vs hard disagree on {int(np.sum(soft != hard))}/{N_TEST} rows [M]")

    c_pred = c_predictions()
    if c_pred is None:
        print("SKIP C test: no usable g++ (the check will be done on the ESP32 with Rabah)")
    else:
        mism_hard, mism_soft = int(np.sum(c_pred != hard)), int(np.sum(c_pred != soft))
        print(f"C code vs hard-vote Python: {mism_hard} mismatches; vs soft-vote Python: {mism_soft} [M]")
        checks["C code equals hard-vote Python"] = mism_hard == 0
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())