"""tools/common.py : code commun aux outils MQTT de Khelfa (contrat v1.0, section 5).

Règle du contrat : hôte, port et identifiants viennent TOUJOURS de la configuration
(variables d'environnement MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TLS, MQTT_CA),
jamais écrits en dur dans le code. Aucun mot de passe n'est stocké dans ce dépôt.
"""
import os
import sys
import time

import paho.mqtt.client as mqtt

P = 'm2i2a/equipe30/'                      # préfixe unique des topics (contrat, section 5)
CA_PAR_DEFAUT = 'fog/mosquitto/config/certs/ca.crt'


def charger_env(chemin):
    """Lit un fichier KEY=VALUE (une variable par ligne) et remplit os.environ.
    Une variable déjà définie dans le terminal N'EST PAS écrasée : le terminal gagne."""
    with open(chemin, encoding='utf-8') as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith('#') or '=' not in ligne:
                continue
            cle, val = ligne.split('=', 1)
            os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


def ajouter_arg_env(ap):
    """Ajoute --env-file à un ArgumentParser."""
    ap.add_argument('--env-file', default='',
                    help='fichier KEY=VALUE à charger (ex. tools/emulator.env)')


def appliquer_env_file(args):
    if getattr(args, 'env_file', ''):
        charger_env(args.env_file)


def config_broker():
    """Retourne (hôte, port, utilisateur, mot de passe, tls) lus dans l'environnement."""
    return (os.environ.get('MQTT_HOST', 'localhost'),
            int(os.environ.get('MQTT_PORT', '1883')),
            os.environ.get('MQTT_USER', ''),
            os.environ.get('MQTT_PASS', ''),
            os.environ.get('MQTT_TLS', '0') == '1')


def creer_client(client_id, user_par_defaut='', will=None):
    """Crée un client paho (API v2) configuré depuis l'environnement.

    - identifiants : posés seulement si MQTT_USER et MQTT_PASS sont non vides
      (un broker public anonyme comme broker.emqx.io n'en veut pas) ;
    - TLS : si MQTT_TLS=1, vérifie le certificat avec MQTT_CA (défaut : notre CA).
      MQTT_CA vide = magasin de certificats du système (cas d'un broker cloud public) ;
    - will : tuple (topic, payload) publié par le broker si on tombe sans prévenir.
    """
    cid = os.environ.get('MQTT_CLIENT_ID', client_id)
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    host, port, user, pwd, tls = config_broker()
    user = user or user_par_defaut
    if user and pwd:
        cli.username_pw_set(user, pwd)      # sinon : connexion anonyme (broker public)
    if tls:
        ca = os.environ.get('MQTT_CA', CA_PAR_DEFAUT)
        cli.tls_set(ca_certs=ca or None)
    if will:
        cli.will_set(will[0], will[1], qos=1, retain=True)
    return cli


def connecter(cli, essais=10, pause=3.0):
    """Se connecte au broker de l'environnement ; réessaie si le broker n'est pas prêt."""
    host, port, user, pwd, tls = config_broker()
    print(f"[broker] {host}:{port} tls={'oui' if tls else 'non'} "
          f"utilisateur={user or '(anonyme)'}", flush=True)
    if user and not pwd:
        print("[broker] ATTENTION : MQTT_USER défini sans MQTT_PASS -> connexion "
              "sans identifiants (normal sur un broker public, refusé sur le Mosquitto "
              "sécurisé).", flush=True)
    for k in range(1, essais + 1):
        try:
            cli.connect(host, port, keepalive=30)
            return
        except Exception as e:             # broker éteint, mauvais hôte, pas de réseau...
            print(f"[broker] connexion impossible ({e}), essai {k}/{essais}", flush=True)
            time.sleep(pause)
    sys.exit("Impossible de joindre le broker : vérifie MQTT_HOST / MQTT_PORT.")
