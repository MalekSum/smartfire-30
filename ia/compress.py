"""Compress the Edge model and measure the loss (brief 05, step E).

Levers: (1) fewer trees / shallower ("reduit"), (2) cost-complexity pruning ("elague"),
(3) distillation: Edge trained on labels given by the Cloud model ("distille").
Selection uses the VALIDATION split only; the test split is used once, for the chosen variant.
Run after `python -m ia.train`:  python -m ia.compress
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI: figures are saved to a file
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

from ia.generator import FEATURES, build_dataset
from ia.metrics import evaluate
from ia.split import split
from ia.train import CONTRACT_COLUMNS, EXTRA_COLUMNS, OUT as QUALITE, make_row, size_ko

SEEDS = (1, 2, 3, 4, 5)
TREES = (4, 8, 16)
DEPTHS = (4, 5, 6, 7, 8)
CCP_ALPHAS = (0.0002, 0.0005, 0.001, 0.002)
TOLERANCE = 0.01          # fixed BEFORE looking at the results: smaller than the seed std (~0.025)
TRANSFER_OFFSET = 100     # distillation set = generator output of seed + 100 (labels ignored)
FINAL = "edge_compresse"
SWEEP = Path("docs") / "resultats" / "compression_balayage.csv"
FIG = Path("docs") / "resultats" / "taille_vs_f1.png"


def configs() -> list[dict]:
    out = []
    for n in TREES:
        for d in DEPTHS:
            out.append({"lever": "reduit", "n": n, "depth": d, "ccp": 0.0})
            out.append({"lever": "distille", "n": n, "depth": d, "ccp": 0.0})
    out += [{"lever": "elague", "n": 8, "depth": None, "ccp": a} for a in CCP_ALPHAS]
    return out


def name_of(c: dict) -> str:
    depth = "none" if c["depth"] is None else c["depth"]
    return f"{c['lever']}_t{c['n']}_d{depth}" + (f"_a{c['ccp']}" if c["ccp"] else "")


def X_of(d: pd.DataFrame):
    return d[FEATURES].to_numpy(dtype=float)


def n_nodes(model) -> int:
    """Total number of tree nodes: a proxy of the size of the C code."""
    return int(sum(e.tree_.node_count for e in model.estimators_))


def prepare(seed: int):
    """Split + teacher (Cloud-type model, trained on train only) + labelled transfer set."""
    tr, va, te = split(build_dataset(seed), seed)
    teacher = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                             early_stopping=False, random_state=seed)
    teacher.fit(X_of(tr), tr["y"].to_numpy())
    transfer = X_of(build_dataset(seed + TRANSFER_OFFSET))  # the generator's own labels are NOT used
    return tr, va, te, transfer, teacher.predict(transfer)


def fit(c: dict, seed: int, tr, transfer, pseudo):
    model = RandomForestClassifier(n_estimators=c["n"], max_depth=c["depth"],
                                   ccp_alpha=c["ccp"], random_state=seed, n_jobs=-1)
    if c["lever"] == "distille":
        return model.fit(transfer, pseudo)
    return model.fit(X_of(tr), tr["y"].to_numpy())


def sweep(cfgs: list[dict]):
    rows, cache = [], {}
    for seed in SEEDS:
        cache[seed] = prepare(seed)
        tr, va, _, transfer, pseudo = cache[seed]
        for c in cfgs:
            m = fit(c, seed, tr, transfer, pseudo)
            ev = evaluate(va, m.predict(X_of(va)))
            rows.append({"config": name_of(c), "lever": c["lever"], "seed": seed,
                         "n_nodes": n_nodes(m), "taille_ko": size_ko(m),
                         "f1_incendie": ev["f1_incendie"],
                         "taux_fausses_alarmes": ev["taux_fausses_alarmes"],
                         "taux_manques": ev["taux_manques"]})
        print(f"seed {seed} swept", flush=True)
    return pd.DataFrame(rows), cache


def plot(agg: pd.DataFrame, lever: pd.Series, chosen: str, q: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for lv, color in (("reduit", "tab:blue"), ("elague", "tab:green"), ("distille", "tab:orange")):
        a = agg[agg["config"].map(lever) == lv]
        ax.scatter(a["ko"], a["f1"], s=28, color=color, label=lv)
    best = agg[agg["config"] == chosen].iloc[0]
    ax.scatter(best["ko"], best["f1"], s=150, facecolors="none", edgecolors="black",
               linewidths=2, label=f"chosen: {chosen}")
    ref = q[q["split"] == "val"].groupby("modele").agg(ko=("taille_ko", "mean"), f1=("f1_incendie", "mean"))
    for m in ("baseline_arbre", "edge_rf", "fog_rf", "cloud_hgb"):
        ax.scatter(ref.loc[m, "ko"], ref.loc[m, "f1"], marker="s", color="tab:red")
        ax.annotate(m, (ref.loc[m, "ko"], ref.loc[m, "f1"]), fontsize=8,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlabel("serialised size (Ko, joblib, log scale)")
    ax.set_ylabel("F1 fire, validation (mean over 5 seeds)")
    ax.set_title("Size vs quality of the Edge model variants")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=120)


def main() -> int:
    cfgs = configs()
    by_name = {name_of(c): c for c in cfgs}
    sw, cache = sweep(cfgs)
    sw.round(6).to_csv(SWEEP, index=False, lineterminator="\n")

    agg = sw.groupby("config").agg(f1=("f1_incendie", "mean"), fa=("taux_fausses_alarmes", "mean"),
                                   nodes=("n_nodes", "mean"), ko=("taille_ko", "mean")).reset_index()
    # rule: smallest model (fewest nodes) whose mean val F1 is within TOLERANCE of the best
    eligible = agg[agg["f1"] >= agg["f1"].max() - TOLERANCE]
    chosen = eligible.sort_values(["nodes", "f1"], ascending=[True, False]).iloc[0]["config"]

    pd.set_option("display.width", 200)
    print(f"\nvalidation, mean over seeds {SEEDS} [M]  (rule: smallest within {TOLERANCE} of best F1)")
    print(agg.sort_values("nodes").round(4).to_string(index=False))
    print(f"\nchosen: {chosen}")

    # the test split is used here, once, for the chosen variant only
    c = by_name[chosen]
    rows = []
    for seed in SEEDS:
        tr, va, te, transfer, pseudo = cache[seed]
        m = fit(c, seed, tr, transfer, pseudo)
        size = size_ko(m)
        for sp, d in (("val", va), ("test", te)):
            rows.append(make_row(FINAL, sp, seed, d, m.predict(X_of(d)), size))
    q = pd.read_csv(QUALITE)
    q = q[q["modele"] != FINAL]
    new = pd.DataFrame(rows)[CONTRACT_COLUMNS + EXTRA_COLUMNS].round(6)
    q = pd.concat([q[CONTRACT_COLUMNS + EXTRA_COLUMNS], new], ignore_index=True)
    q.to_csv(QUALITE, index=False, lineterminator="\n")

    test = q[q["split"] == "test"].pivot_table(index="seed", columns="modele", values="f1_incendie")
    for label, col in (("edge_rf (brief)", "edge_rf"), (FINAL, FINAL)):
        loss = test["fog_rf"] - test[col]
        print(f"compression loss, F1 fire test, fog_rf - {label}: "
              f"{loss.mean():+.4f} +/- {loss.std():.4f} over seeds (per-seed paired) [M]")
    sizes = q[q["split"] == "test"].groupby("modele")["taille_ko"].mean()
    print(f"size Ko: fog_rf {sizes['fog_rf']:.1f} -> edge_rf {sizes['edge_rf']:.1f} -> {FINAL} {sizes[FINAL]:.1f} [M]")

    lever = sw.drop_duplicates("config").set_index("config")["lever"]
    plot(agg, lever, chosen, q)
    checks = {
        f"{len(cfgs)} configs x {len(SEEDS)} seeds in the sweep": len(sw) == len(cfgs) * len(SEEDS),
        "qualite.csv has 60 rows (50 + 10)": len(q) == 60,
        "figure written": FIG.exists(),
    }
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())