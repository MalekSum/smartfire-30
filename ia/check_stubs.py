"""ia/check_stubs.py : recharge les stubs depuis le registre, comme le fera le Cloud de Sid Ahmed."""
import json
import pathlib

import joblib
import numpy as np

RACINE = pathlib.Path(__file__).resolve().parent.parent

reg = json.loads((RACINE / 'models' / 'registry.json').read_text(encoding='utf-8'))
assert set(reg) == {'edge', 'fog', 'cloud'}, "le registre doit contenir edge, fog, cloud"

# Ordre des features : t, h, gaz, flame, dt  (exemples tirés du tableau du contrat, section 4)
exemples = {
    'normal':   [24.0, 45.0, 400, 0, 0.0],
    'cuisson':  [32.0, 45.0, 2200, 0, 0.1],
    'vapeur':   [30.0, 90.0, 1300, 0, 0.1],
    'incendie': [80.0, 25.0, 3500, 1, 2.0],
    'couvant':  [48.0, 35.0, 2800, 0, 0.8],
}
X = np.array(list(exemples.values()), dtype=float)

for couche, info in reg.items():
    modele = joblib.load(RACINE / 'models' / couche / info['file'])
    print(f"{couche:5s} v{info['mv']} ({info['file']}) ->", dict(zip(exemples, modele.predict(X))))