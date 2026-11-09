"""ia/generator.py : générateur d'épisodes SmartFire-30 (contrat v1.0, sections 3 et 4).
Données SYNTHÉTIQUES : les plages sont des conventions du projet, pas des mesures réelles."""
import numpy as np
import pandas as pd

FEATURES = ['t', 'h', 'gaz', 'flame', 'dt']          # ordre imposé pour tous les modèles
CLASSES = {0: 'normal', 1: 'perturbation', 2: 'incendie'}


def episode(kind, n, rng):
    """Un épisode = n mesures à 1 Hz.
    kind : normal | cuisson | vapeur | incendie | couvant
    rng  : np.random.default_rng(seed)  (reproductibilité)
    Retourne un DataFrame aux colonnes t, h, gaz, flame, dt, y (signature imposée)."""
    if kind not in ('normal', 'cuisson', 'vapeur', 'incendie', 'couvant'):
        raise ValueError(f"kind inconnu : {kind}")
    k = np.arange(n)                                   # 0, 1, ..., n-1 (secondes)

    # --- 1. Base « normale » : niveau fixe (t0, h0, g0) tiré au hasard + bruit gaussien ---
    t0 = rng.uniform(18, 30)
    h0 = rng.uniform(30, 65)
    g0 = rng.uniform(150, 700)
    t = t0 + rng.normal(0, 0.15, n)
    h = h0 + rng.normal(0, 0.8, n)
    g = g0 + rng.normal(0, 25, n)
    flame = np.zeros(n, dtype=int)
    y = np.zeros(n, dtype=int)

    def ecart_h(lo, hi):
        """Écart de h pour atteindre une CIBLE tirée dans [lo, hi] du contrat.
        Positif = h monte, négatif = h descend ; nul si h0 est déjà dans la plage."""
        cible = rng.uniform(lo, hi)
        if h0 < lo:
            return cible - h0
        if h0 > hi:
            return cible - h0
        return 0.0

    # --- 2. Perturbation / incendie : montée progressive ramp de 0 à 1 ---
    if kind != 'normal':
        start = rng.uniform(5, max(6, 0.3 * n))        # instant de début de l'événement
        ramp = np.clip((k - start) / rng.uniform(20, 60), 0, 1)   # montée sur 20-60 s

        if kind == 'cuisson':                          # fumée forte, humidité inchangée
            t = t + ramp * rng.uniform(2, 12)
            g = g + ramp * rng.uniform(1100, 2300)
            y = np.where(ramp > 0.15, 1, 0)
        elif kind == 'vapeur':                         # humidité forte (cible 75-98), fumée moyenne
            t = t + ramp * rng.uniform(1, 8)
            h = np.minimum(h + ramp * ecart_h(75, 98), 98)
            g = g + ramp * rng.uniform(300, 1300)
            y = np.where(ramp > 0.15, 1, 0)
        elif kind == 'incendie':                       # chaleur + fumée + flamme (~85 %), h cible 10-40
            t = t + ramp ** 1.5 * rng.uniform(25, 90)  # montée accélérée (puissance 1.5)
            h = h + ramp * ecart_h(10, 40)
            g = g + ramp * rng.uniform(2000, 3400)
            flame = ((rng.random(n) < 0.85) & (ramp > 0.3)).astype(int)
            y = np.where(ramp > 0.15, 2, 0)
        elif kind == 'couvant':                        # feu couvant : SANS flamme, h cible 20-50
            t = t + ramp * rng.uniform(10, 35)
            h = h + ramp * ecart_h(20, 50)
            g = g + ramp * rng.uniform(1500, 2800)
            y = np.where(ramp > 0.15, 2, 0)

    # --- 3. Bornes physiques du contrat (plages valides) ---
    t = np.clip(t, -10, 120)
    h = np.clip(h, 0, 100)
    g = np.clip(np.round(g), 0, 4095).astype(int)      # ADC 12 bits

    # --- 4. dt = (t(n) - t(n-5)) / 5 ; 0 pendant les 5 premières secondes (comme le firmware) ---
    dt = np.zeros(n)
    dt[5:] = (t[5:] - t[:-5]) / 5

    return pd.DataFrame({'t': t, 'h': h, 'gaz': g, 'flame': flame, 'dt': dt, 'y': y})
def build_dataset(seed=42, counts=None):
    """Concatène des épisodes. episode_id sert à séparer train/test PAR ÉPISODE (pas de fuite)."""
    counts = counts or {'normal': 150, 'cuisson': 100, 'vapeur': 100,
                        'incendie': 120, 'couvant': 40}
    rng = np.random.default_rng(seed)
    parts, eid = [], 0
    for kind, c in counts.items():
        for _ in range(c):
            d = episode(kind, int(rng.integers(90, 240)), rng)   # durée 90 à 239 s
            d['episode_id'] = eid
            d['kind'] = kind
            parts.append(d)
            eid += 1
    return pd.concat(parts, ignore_index=True)


if __name__ == '__main__':                             # petit test rapide
    df = build_dataset()
    print(df.shape)
    print(df['y'].value_counts().sort_index())
    print(df.groupby('kind')[FEATURES].mean().round(2))