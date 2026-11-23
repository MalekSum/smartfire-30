# SmartFire-30 : API Cloud (FastAPI + SQLite), conforme au contrat v1.0 section 6
import os, json, time, pathlib, sqlite3
import joblib
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

# Configuration lue dans l'environnement (jamais écrite en dur)
DB = os.environ.get('DB_PATH', '/data/cloud.db')
MODELS = pathlib.Path(os.environ.get('MODELS_DIR', '/models'))
KEY = os.environ.get('CLOUD_API_KEY', '')
FEATURES = ['t', 'h', 'gaz', 'flame', 'dt']  # ordre imposé par le contrat

app = FastAPI(title='SmartFire-30 Cloud')

# Base SQLite : le dossier doit exister, puis on crée la table si besoin
os.makedirs(os.path.dirname(DB), exist_ok=True)
db = sqlite3.connect(DB, check_same_thread=False)
db.execute('''CREATE TABLE IF NOT EXISTS mesures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recu_at INTEGER, ts INTEGER, seq INTEGER, mode TEXT,
    t REAL, h REAL, gaz INTEGER, flame INTEGER, dt REAL, valid INTEGER,
    y_edge INTEGER, a_seuil INTEGER, y_fog INTEGER, y_final INTEGER,
    confirme INTEGER, mv_edge INTEGER, mv_fog INTEGER, y_true INTEGER)''')
db.execute('CREATE INDEX IF NOT EXISTS idx_ts ON mesures(ts)')
db.commit()

# Cache du modèle Cloud : on ne recharge que si la version change
cache = {'mv': -1, 'model': None}


def auth(k):
    """Refuse la requête si une clé API est configurée et qu'elle ne correspond pas."""
    if KEY and k != KEY:
        raise HTTPException(status_code=401, detail='clé API invalide')


def registry():
    """Lit models/registry.json (versions courantes de chaque couche)."""
    return json.loads((MODELS / 'registry.json').read_text())


@app.get('/api/health')
def health():
    return {'ok': True}


@app.post('/api/mesures')
def mesures(m: dict, x_api_key: str = Header(default='')):
    """Enregistre une mesure enrichie de la décision du Fog."""
    auth(x_api_key)
    row = (int(time.time()), m.get('ts'), m.get('seq'), m.get('mode'),
           m.get('t'), m.get('h'), m.get('gaz'), m.get('flame'), m.get('dt'),
           m.get('valid', 1), m.get('y_edge', -1), m.get('a_seuil', 0),
           m.get('y_fog', -1), m.get('y_final', -1), m.get('confirme', 0),
           m.get('mv'), m.get('mv_fog'), m.get('y_true'))
    db.execute('INSERT INTO mesures (recu_at, ts, seq, mode, t, h, gaz, flame, dt,'
               ' valid, y_edge, a_seuil, y_fog, y_final, confirme, mv_edge, mv_fog,'
               ' y_true) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', row)
    db.commit()
    return {'ok': True}


@app.post('/api/infer')
def infer(m: dict, x_api_key: str = Header(default='')):
    """Scénario S1 : le Cloud calcule la décision avec le modèle cloud."""
    auth(x_api_key)
    reg = registry()['cloud']
    if reg['mv'] != cache['mv']:  # nouvelle version : on recharge
        cache['model'] = joblib.load(MODELS / 'cloud' / reg['file'])
        cache['mv'] = reg['mv']
    y = int(cache['model'].predict([[m[f] for f in FEATURES]])[0])
    return {'y': y, 'mv': cache['mv']}


@app.get('/api/modele/version')
def version():
    r = registry()
    return {k: r[k]['mv'] for k in ('edge', 'fog', 'cloud')}


@app.get('/api/modele/latest')
def latest(couche: str = 'fog'):
    """Renvoie le fichier du dernier modèle (le Fog le télécharge ici)."""
    if couche not in ('fog', 'cloud'):
        raise HTTPException(status_code=400, detail='couche inconnue')
    return FileResponse(MODELS / couche / registry()[couche]['file'])


@app.get('/api/stats')
def stats():
    """Agrégats pour le dashboard."""
    q = lambda sql: db.execute(sql).fetchone()[0]
    return {
        'total': q('SELECT COUNT(*) FROM mesures'),
        'alertes': q('SELECT COUNT(*) FROM mesures WHERE y_final = 2'),
        'fausses_alarmes_evitees': q(
            'SELECT COUNT(*) FROM mesures WHERE a_seuil = 1 AND y_final IN (0, 1)'),
        'desaccords_edge_fog': q(
            'SELECT COUNT(*) FROM mesures '
            'WHERE y_edge >= 0 AND y_fog >= 0 AND y_edge != y_fog'),
        'derniere_reception': q('SELECT MAX(recu_at) FROM mesures'),
    }


@app.get('/api/export')
def export(limit: int = 1000):
    """Dernières mesures en JSON (utilisé par le script de dérive de Bahi)."""
    cur = db.execute('SELECT * FROM mesures ORDER BY id DESC LIMIT ?', (limit,))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
