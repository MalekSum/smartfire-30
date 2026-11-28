# Cloud : API FastAPI + SQLite

Rôle : stocker les mesures, servir les modèles au Fog (REST), calculer une décision en S1.
Code : main.py. Image : Dockerfile (Python 3.11, versions de ia/requirements-runtime.txt).

## Lancement
Depuis la racine du dépôt :
    cp .env.example .env     (puis renseigner CLOUD_API_KEY dans .env, jamais dans Git)
    docker compose up -d --build cloud
    curl http://localhost:8000/api/health
Documentation automatique : http://localhost:8000/docs

## Variables d'environnement
| Variable | Rôle | Valeur par défaut |
|---|---|---|
| CLOUD_API_KEY | clé exigée dans l'en-tête X-API-Key pour les écritures (si vide, tout est accepté : développement seulement) | vide |
| DB_PATH | fichier SQLite | /data/cloud.db (volume cloud_data) |
| MODELS_DIR | dossier des modèles | /models (monté depuis ./models) |

## Routes (contrat v1.0, section 6)
| Méthode et chemin | Clé API | Rôle |
|---|---|---|
| GET /api/health | non | renvoie {"ok": true} |
| POST /api/mesures | oui | enregistre une mesure enrichie de la décision du Fog |
| POST /api/infer | oui | scénario S1 : renvoie {"y", "mv"} calculé par le modèle cloud |
| GET /api/modele/version | non | versions courantes edge, fog, cloud (lues dans models/registry.json) |
| GET /api/modele/latest?couche=fog ou cloud | non | fichier .joblib de la couche demandée |
| GET /api/stats | non | total, alertes, fausses alarmes évitées, désaccords Edge/Fog, dernière réception |
| GET /api/export?limit=1000 | non | dernières mesures en JSON (script de dérive) |

## Base de données
Table mesures : id (numéro de ligne automatique), recu_at, ts, seq, mode, t, h, gaz, flame, dt, valid, y_edge, a_seuil, y_fog, y_final, confirme, mv_edge, mv_fog, y_true. Index sur ts.
Fausse alarme évitée : a_seuil = 1 et y_final vaut 0 ou 1.

## Limites connues
- Garantie "au moins une fois" : si la réponse du Cloud se perd, le Fog renvoie la mesure et un doublon est possible.
- Les routes de lecture ne demandent pas de clé API.
- Une mesure sans décision (y_final = -1) n'est pas comptée dans les fausses alarmes évitées.
