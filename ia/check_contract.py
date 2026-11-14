"""ia/check_contract.py : compare le générateur au tableau « ordres de grandeur » (contrat §4).
On évalue le PLATEAU (10 dernières secondes de chaque épisode), car le début de montée
traverse forcément des valeurs intermédiaires."""
import numpy as np
import pandas as pd
from ia.generator import episode

PLAGES = {   # (min, max) copiés du contrat v1.0, section 4
    'normal':   {'t': (18, 32), 'h': (30, 70), 'gaz': (150, 800),   'flame': (0, 0), 'dt': (-0.1, 0.1)},
    'cuisson':  {'t': (24, 40), 'h': (30, 60), 'gaz': (1500, 3000), 'flame': (0, 0), 'dt': (0, 0.3)},
    'vapeur':   {'t': (26, 35), 'h': (75, 98), 'gaz': (800, 1800),  'flame': (0, 0), 'dt': (0, 0.2)},
    'incendie': {'t': (40, 120), 'h': (10, 40), 'gaz': (2500, 4095), 'flame': (0, 1), 'dt': (0.5, 5)},
    'couvant':  {'t': (35, 60), 'h': (20, 50), 'gaz': (2000, 3500), 'flame': (0, 0), 'dt': (0.3, 1.5)},
}


def main(n_ep=200, n=200, seed=0, plateau=10):
    """t, h, gaz, flame : évalués sur le PLATEAU (10 dernières s).
    dt : évalué pendant la MONTÉE (gaz entre 20 % et 90 % de son augmentation totale),
    car sur le plateau la température est stable donc dt est proche de 0."""
    rng = np.random.default_rng(seed)
    for kind, plages in PLAGES.items():
        plat, mont = [], []
        for _ in range(n_ep):
            d = episode(kind, n, rng)
            if kind == 'normal':
                plat.append(d)
                mont.append(d)
            else:
                plat.append(d.iloc[-plateau:])
                g = d['gaz'].to_numpy(dtype=float)
                g_debut = np.median(g[:5])                 # niveau de départ
                g_fin = g[-plateau:].mean()                # niveau du plateau
                frac = (g - g_debut) / max(g_fin - g_debut, 1.0)   # avancement 0 -> 1
                mont.append(d[(frac > 0.2) & (frac < 0.9)])
        df_plat, df_mont = pd.concat(plat), pd.concat(mont)
        print(f"\n=== {kind} (plateau : {len(df_plat)} lignes ; montée : {len(df_mont)} lignes) ===")
        for f, (lo, hi) in plages.items():
            df = df_mont if f == 'dt' else df_plat
            v = df[f].to_numpy()
            pct = 100 * np.mean((v >= lo) & (v <= hi))
            src = 'montée ' if f == 'dt' else 'plateau'
            print(f"  {f:5s} [{src}] min={v.min():9.3f} max={v.max():9.3f}  dans [{lo}, {hi}] : {pct:5.1f} %")
        if kind == 'incendie':
            print(f"  flame moyen (plateau) = {df_plat['flame'].mean():.2f} (contrat : environ 0.85)")
if __name__ == '__main__':
    main()