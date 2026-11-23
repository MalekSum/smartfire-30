# SmartFire-30 : service d'inférence du Fog (contrat v1.0, sections 2, 5 et 6)
import os, json, time, queue, threading
import joblib, requests
import paho.mqtt.client as mqtt

P = 'm2i2a/equipe30/'                      # préfixe unique des topics
FEATURES = ['t', 'h', 'gaz', 'flame', 'dt']  # ordre imposé par le contrat
CLOUD = os.environ.get('CLOUD_URL', 'http://cloud:8000')
HDR = {'X-API-Key': os.environ.get('CLOUD_API_KEY', '')}

# État du service : scénario actif, modèle chargé, versions
st = {'mode': 'S4', 'model': None, 'mv': 0, 'mv_edge_pub': -1}
out_q = queue.Queue(maxsize=10000)         # tampon vers le Cloud


def refresh_model(cli):
    """Interroge la version, télécharge le modèle Fog si elle a changé."""
    v = requests.get(CLOUD + '/api/modele/version', timeout=3).json()
    if v['fog'] != st['mv']:
        r = requests.get(CLOUD + '/api/modele/latest',
                         params={'couche': 'fog'}, timeout=15)
        r.raise_for_status()
        with open('/tmp/model_fog.joblib', 'wb') as f:
            f.write(r.content)
        st['model'] = joblib.load('/tmp/model_fog.joblib')
        st['mv'] = v['fog']
        print('Modèle Fog chargé, version', st['mv'], flush=True)
    if v['edge'] != st['mv_edge_pub']:     # annonce la version Edge aux nœuds
        cmd = {'mv': v['edge'], 'n_confirm': 2, 'seuil_classique': 2000}
        cli.publish(P + 'edge/commande/modele', json.dumps(cmd),
                    qos=1, retain=True)
        st['mv_edge_pub'] = v['edge']


def model_loop(cli):
    """Vérifie la version du modèle toutes les 30 s (rechargement à chaud)."""
    while True:
        try:
            refresh_model(cli)
        except Exception as e:
            print('Cloud injoignable pour le modèle :', e, flush=True)
        time.sleep(30)


def cloud_worker():
    """Envoie les enregistrements au Cloud ; garde l'élément tant que l'envoi échoue."""
    while True:
        rec = out_q.get()
        while True:
            try:
                requests.post(CLOUD + '/api/mesures', json=rec, headers=HDR,
                              timeout=3).raise_for_status()
                break
            except Exception:
                time.sleep(2)


def handle(cli, d):
    """Traite une mesure : décision selon le scénario, publication, mise en file."""
    t0 = time.perf_counter()
    mode = st['mode']
    y_fog, src = -1, 'fog'
    if d.get('valid', 1) == 1:             # mesure invalide : modèles ignorés
        x = [[d[f] for f in FEATURES]]
        if mode == 'S1':                   # tout-Cloud : le Fog relaie
            src = 'cloud'
            try:
                y_fog = int(requests.post(CLOUD + '/api/infer', json=d,
                                          headers=HDR, timeout=2).json()['y'])
            except Exception:
                y_fog = -1                 # Cloud coupé : pas de décision en S1
        elif mode in ('S2', 'S4') and st['model'] is not None:
            y_fog = int(st['model'].predict(x)[0])
    if mode == 'S3':                       # tout-Edge : le Fog ne décide pas
        src, y_final = 'edge', d.get('y_edge', -1)
    else:
        y_final = y_fog
    confirme = (y_final == 2)
    res = {'seq': d['seq'], 'ts': d['ts'], 'mode': mode, 'y_fog': y_fog,
           'y_edge': d.get('y_edge', -1), 'confirme': confirme, 'src': src,
           'mv_fog': st['mv'],
           'lat_fog_ms': round((time.perf_counter() - t0) * 1000, 2)}
    cli.publish(P + 'fog/resultats', json.dumps(res), qos=1)
    rec = dict(d, y_fog=y_fog, y_final=y_final, confirme=int(confirme),
               mv_fog=st['mv'])
    try:
        out_q.put_nowait(rec)
    except queue.Full:
        pass


def on_connect(cli, userdata, flags, rc, props):
    print('Connecté à Mosquitto, code', rc, flush=True)
    cli.publish(P + 'fog/statut', 'online', qos=1, retain=True)
    cli.subscribe([(P + 'edge/capteurs', 0), (P + 'edge/commande/mode', 1)])


def on_message(cli, userdata, msg):
    try:
        if msg.topic.endswith('commande/mode'):
            st['mode'] = msg.payload.decode().strip()
            print('Scénario actif :', st['mode'], flush=True)
        else:
            handle(cli, json.loads(msg.payload))
    except Exception as e:                 # un message mal formé ne doit pas tuer le service
        print('Message ignoré :', e, flush=True)


cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='fog30-svc')
cli.username_pw_set(os.environ.get('MQTT_USER', ''),
                    os.environ.get('MQTT_PASS', ''))
if os.environ.get('MQTT_TLS', '0') == '1':
    cli.tls_set()
cli.will_set(P + 'fog/statut', 'offline', qos=1, retain=True)  # Last Will
cli.on_connect, cli.on_message = on_connect, on_message

# Ajout par rapport au brief : on réessaie tant que le broker n'est pas prêt
while True:
    try:
        cli.connect(os.environ.get('MQTT_HOST', 'mosquitto'),
                    int(os.environ.get('MQTT_PORT', '1883')))
        break
    except Exception as e:
        print('Mosquitto pas prêt, nouvel essai dans 3 s :', e, flush=True)
        time.sleep(3)

threading.Thread(target=model_loop, args=(cli,), daemon=True).start()
threading.Thread(target=cloud_worker, daemon=True).start()
cli.loop_forever()
