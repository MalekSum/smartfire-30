"""ia/make_stubs.py : génère les modèles PROVISOIRES (v0) pour débloquer Rabah et Sid Ahmed.
Entraînement rapide sur un sous-ensemble, sans réglage : seul le FORMAT compte ici."""
import json
import pathlib

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from micromlgen import port

from ia.generator import FEATURES, build_dataset

SEED = 42
RACINE = pathlib.Path(__file__).resolve().parent.parent      # = E:\ia-iot\smartfire-30


def main():
    # 1. Jeu réduit : petits effectifs d'épisodes (rapide, ~20-30 % du jeu complet)
    counts = {'normal': 40, 'cuisson': 30, 'vapeur': 30, 'incendie': 35, 'couvant': 15}
    df = build_dataset(seed=SEED, counts=counts)
    X = df[FEATURES].to_numpy(dtype=float)       # ordre imposé : t, h, gaz, flame, dt
    y = df['y'].to_numpy()
    print(f"Jeu stub : {X.shape[0]} lignes, classes {np.unique(y)}")

    # 2. Trois modèles (hyperparamètres du brief pour edge et cloud, fog allégé)
    edge = RandomForestClassifier(n_estimators=8, max_depth=6, random_state=SEED).fit(X, y)
    fog = RandomForestClassifier(n_estimators=30, max_depth=10, random_state=SEED, n_jobs=-1).fit(X, y)
    cloud = HistGradientBoostingClassifier(max_iter=50, random_state=SEED).fit(X, y)

    # 3. Sauvegarde joblib (noms imposés par le contrat, section 7)
    chemins = {
        'edge': RACINE / 'models' / 'edge' / 'model_edge_v0.joblib',
        'fog': RACINE / 'models' / 'fog' / 'model_fog_v0.joblib',
        'cloud': RACINE / 'models' / 'cloud' / 'model_cloud_v0.joblib',
    }
    for nom, m in (('edge', edge), ('fog', fog), ('cloud', cloud)):
        chemins[nom].parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(m, chemins[nom])
        print(f"{nom:5s} -> {chemins[nom].name} : {chemins[nom].stat().st_size / 1024:.1f} Ko [M]")

    # 4. Export C du modèle Edge (interface figée : Eloquent::ML::Port::RandomForest)
    code_c = port(edge)
    sortie_h = RACINE / 'edge' / 'model_stub.h'
    sortie_h.write_text(code_c, encoding='utf-8')
    print(f"model_stub.h : {sortie_h.stat().st_size / 1024:.1f} Ko [M]")

    # 5. registry.json : les trois clés edge, fog, cloud (contrat, section 7)
    registre = {
        'edge':  {'mv': 0, 'file': 'model_edge_v0.joblib',  'metrics': {'note': 'stub'}},
        'fog':   {'mv': 0, 'file': 'model_fog_v0.joblib',   'metrics': {'note': 'stub'}},
        'cloud': {'mv': 0, 'file': 'model_cloud_v0.joblib', 'metrics': {'note': 'stub'}},
    }
    (RACINE / 'models' / 'registry.json').write_text(json.dumps(registre, indent=2), encoding='utf-8')
    print("registry.json écrit")


if __name__ == '__main__':
    main()