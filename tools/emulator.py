"""tools/emulator.py : nœud Edge émulé en Python (brief Khelfa, étape E ; contrat v1.0).

Joue le rôle de l'ESP32 pour les tests de masse (charge, anomalies, dérive, coupures).
Il COMPLÈTE le Wokwi de Rabah, il ne le remplace pas.

Lancement (depuis la racine du dépôt) :
    python -m tools.emulator --kind incendie --n 120
    python -m tools.emulator --plan normal:300,incendie:60 --edge-model models/edge/model_edge_v1.joblib

Broker : lu dans l'environnement, jamais dans le code (contrat, section 5) :
    MQTT_HOST (défaut localhost)  MQTT_PORT (défaut 1883)
    MQTT_USER / MQTT_PASS (vides = connexion anonyme)  MQTT_TLS=1  MQTT_CA=<ca.crt>
Exemples :
    # broker public de la phase Wokwi (aucun mot de passe, préfixe d'équipe obligatoire)
    MQTT_HOST=broker.emqx.io MQTT_PORT=1883 python -m tools.emulator --kind incendie
    # Mosquitto local sécurisé
    MQTT_HOST=localhost MQTT_USER=edge30 MQTT_PASS=... python -m tools.emulator
"""
import argparse
import json
import threading
import time

import joblib
import numpy as np

from ia.generator import episode, FEATURES
from tools.common import (P, ajouter_arg_env, appliquer_env_file, connecter,
                          creer_client)

MODES = ('S1', 'S2', 'S3', 'S4')
KINDS = ('normal', 'cuisson', 'vapeur', 'incendie', 'couvant')


def lire_args():
    ap = argparse.ArgumentParser(description="Nœud Edge émulé SmartFire-30")
    ap.add_argument('--kind', default='incendie', choices=KINDS)
    ap.add_argument('--n', type=int, default=120, help="nombre de mesures (1 par épisode)")
    ap.add_argument('--plan', default='',
                    help="enchaîne des épisodes, ex. normal:300,incendie:60 "
                         "(remplace --kind et --n)")
    ap.add_argument('--rate', type=float, default=1.0, help="messages par seconde")
    ap.add_argument('--mode', default='auto',
                    help="S1..S4, ou 'auto' = suit le message retained "
                         "edge/commande/mode (défaut S4 s'il n'y en a pas)")
    ap.add_argument('--edge-model', default='',
                    help="ex. models/edge/model_edge_v1.joblib (sinon y_edge = -1)")
    ap.add_argument('--mv', type=int, default=1, help="version du modèle Edge annoncée")
    ap.add_argument('--derive', default='', help="ex. gaz:400 : simule le vieillissement d'un capteur")
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--no-statut', action='store_true',
                    help="ne publie pas edge/statut (si le Wokwi tourne en même temps)")
    ajouter_arg_env(ap)
    return ap.parse_args()


def construire_donnees(a):
    """Retourne un DataFrame de mesures (t h gaz flame dt y) selon --plan ou --kind/--n."""
    import pandas as pd
    rng = np.random.default_rng(a.seed)
    if a.plan:
        parts = []
        for seg in a.plan.split(','):
            kind, n = seg.split(':')
            parts.append(episode(kind.strip(), int(n), rng))
        df = pd.concat(parts, ignore_index=True)
    else:
        df = episode(a.kind, a.n, rng)
    if a.derive:
        col, off = a.derive.split(':')
        df[col] = df[col] + float(off)
    return df


def main():
    a = lire_args()
    appliquer_env_file(a)
    if a.mode != 'auto' and a.mode not in MODES:
        raise SystemExit("--mode doit valoir auto, S1, S2, S3 ou S4")

    df = construire_donnees(a)
    model = joblib.load(a.edge_model) if a.edge_model else None

    etat = {'mode': a.mode if a.mode != 'auto' else 'S4'}
    mode_recu = threading.Event()

    will = None if a.no_statut else (P + 'edge/statut', 'offline')     # Last Will (contrat)
    cli = creer_client('edge30-emul', user_par_defaut='edge30', will=will)

    def on_connect(c, userdata, flags, rc, props):
        print('[emul] connecté, code', rc, flush=True)
        if rc != 0:
            return
        c.subscribe(P + 'edge/commande/mode', qos=1)       # on suit le scénario actif
        if not a.no_statut:
            c.publish(P + 'edge/statut', 'online', qos=1, retain=True)

    def on_message(c, userdata, msg):
        m = msg.payload.decode(errors='ignore').strip()
        if m in MODES:
            if a.mode == 'auto' and etat['mode'] != m:
                print('[emul] scénario actif :', m, flush=True)
            if a.mode == 'auto':
                etat['mode'] = m
            mode_recu.set()

    cli.on_connect, cli.on_message = on_connect, on_message
    connecter(cli)
    cli.loop_start()
    if a.mode == 'auto':
        mode_recu.wait(2.0)                                # laisse arriver le retained
    print(f"[emul] mode de départ : {etat['mode']} "
          f"({'suivi du broker' if a.mode == 'auto' else 'imposé'}), "
          f"{len(df)} mesures à {a.rate}/s", flush=True)

    n_msg = n_alerte = 0
    t_debut = time.time()
    try:
        for i in range(len(df)):
            mode = etat['mode']
            r = df.iloc[i]
            x = [float(r[f]) for f in FEATURES]
            y_edge = -1
            if model is not None and mode in ('S3', 'S4'):
                y_edge = int(model.predict([x])[0])
            msg = {'id': 'edge30-emul', 'seq': i, 'ts': int(time.time()), 'mode': mode,
                   't': round(x[0], 2), 'h': round(x[1], 2),
                   'gaz': int(x[2]), 'flame': int(x[3]), 'dt': round(x[4], 3),
                   'valid': 1, 'mv': a.mv, 'y_edge': y_edge,
                   'a_seuil': int(x[2] >= 2000),           # détecteur classique (contrat)
                   'y_true': int(r['y'])}                  # vérité terrain : émulateur seulement
            # règle d'émission du contrat (S1/S2 : chaque mesure ; S3 : battement /10 s ;
            # S4 : chaque seconde sauf si tout va bien, alors /10 s)
            envoyer = (mode in ('S1', 'S2')
                       or (mode == 'S3' and i % 10 == 0)
                       or (mode == 'S4' and (y_edge != 0 or i % 10 == 0)))
            if envoyer:
                cli.publish(P + 'edge/capteurs', json.dumps(msg), qos=0)
                n_msg += 1
            if y_edge == 2:                                # alerte : QoS 1, à ne pas perdre
                cli.publish(P + 'edge/alerte',
                            json.dumps({'id': 'edge30-emul', 'seq': i, 'ts': msg['ts'],
                                        'niveau': 2, 'source': 'edge'}), qos=1)
                n_alerte += 1
            # cadence régulière (corrige la dérive due au temps de calcul)
            reste = t_debut + (i + 1) / a.rate - time.time()
            if reste > 0:
                time.sleep(reste)
    except KeyboardInterrupt:
        print('\n[emul] arrêt demandé', flush=True)
    finally:
        if not a.no_statut:                                # un arrêt propre ne déclenche
            try:                                           # pas le Last Will : on le publie
                cli.publish(P + 'edge/statut', 'offline',
                            qos=1, retain=True).wait_for_publish(2)
            except Exception:
                pass                                       # broker déjà coupé : le Last Will s'en charge
        time.sleep(0.3)
        cli.loop_stop()
        cli.disconnect()
    print(f"[emul] terminé : {n_msg} mesures publiées, {n_alerte} alertes envoyées "
          f"en {time.time() - t_debut:.1f} s", flush=True)


if __name__ == '__main__':
    main()
