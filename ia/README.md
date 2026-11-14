\# ia/ : volet intelligence artificielle (E7), Bensoula Abdelbahi



Tout se lance depuis la racine du dépôt, avec le venv actif : `python -m ia.<script>`.

Python 3.11 ; numpy 1.26.4, scikit-learn 1.5.2, joblib 1.4.2 (contrat §8). Installation : `pip install -r ia/requirements.txt`.

Données \*\*synthétiques\*\* (conventions du contrat §4), pas de mesures réelles. Tous les chiffres sont \[M] sauf mention contraire.



\## Scripts, dans l'ordre logique



| Script | Rôle | Sortie |

|---|---|---|

| `generator.py` | génère des épisodes (`episode(kind, n, rng)`, importé par l'émulateur) | DataFrame |

| `check\_contract.py` | compare les plages générées au contrat §4 | `docs/resultats/check\_contract\_v1.txt` |

| `make\_stubs.py`, `check\_stubs.py` | modèles provisoires v0 | `models/\*/model\_\*\_v0.joblib`, `edge/model\_stub.h` |

| `split.py`, `check\_split.py` | découpage 70/15/15 \*\*par épisode\*\*, contrôles anti-fuite | n/a |

| `make\_dataset.py` | écrit le jeu v1 (graine 42) | `data/dataset\_v1.csv` |

| `notebooks/build\_01\_exploration.py` | construit et exécute le notebook | `notebooks/01\_exploration.ipynb` |

| `metrics.py` | précision, rappel, F1, fausses alarmes, délai de détection | n/a |

| `train.py` | compare seuil, arbre, Edge, Fog, Cloud sur 5 graines | `docs/resultats/qualite.csv` |

| `compress.py` | balayage de compression de l'Edge | `compression\_balayage.csv`, `taille\_vs\_f1.png` |

| `export\_edge.py` | export C du modèle Edge et contrôle C/Python | `edge/model.h`, `edge/test\_data.h`, `models/edge/model\_edge\_v1.joblib` |

| `publish\_model.py` | met à jour `models/registry.json` | registre |

| `build\_v1.py` | entraîne Fog et Cloud v1 (graine 42) et publie les 3 couches | `models/\*/model\_\*\_v1.joblib` |

| `drift.py` | distance KS sur les mesures normales (seuil 0,2) | rapport console |

| `retrain.py` | ré-entraînement après dérive, publication v2 | `models/fog`, `models/cloud` en v2 |



`compression\_balayage.csv` n'est pas dans la liste du contrat §9 : c'est un fichier d'appui à `qualite.csv`.



\## Principes



\- Split par épisode : les secondes voisines sont quasi identiques, un split par ligne gonflerait les scores (fuite).

\- `episode\_id`, `kind`, `split` sont des métadonnées, jamais des features. Ordre des features : `\[t, h, gaz, flame, dt]`.

\- Hyperparamètres du brief non réglés ; tout réglage se décide sur `val`, le test sert aux chiffres finaux.

\- Le C de micromlgen vote à raison d'un vote par arbre (vote dur) ; scikit-learn moyenne les probabilités (vote doux). Sur les 500 lignes de `test\_data.h` : 0 écart entre le C et Python.



\## Résultats (test, moyenne sur 5 graines)



| Modèle | F1 incendie | Fausses alarmes | Incendies manqués |

|---|---|---|---|

| Détecteur à seuil | 0,776 ± 0,055 | 0,101 | 0,169 |

| Arbre profondeur 4 | 0,960 ± 0,033 | 0,005 | 0,060 |

| Edge (8 arbres, prof. 6) | 0,971 ± 0,023 | 0,005 | 0,043 |

| Fog (100 arbres, prof. 12) | 0,968 ± 0,026 | 0,007 | 0,044 |

| Cloud (gradient boosting) | 0,963 ± 0,025 | 0,009 | 0,048 |



\- Edge, arbre, Fog et Cloud ne sont pas classables : leurs écarts sont inférieurs à l'écart-type.

\- Perte de compression (F1 incendie, Fog moins Edge) : -0,003 ± 0,006, soit aucune perte mesurable. Tailles joblib : 6 139 Ko contre 56 Ko.

\- Edge déployé (graine 42) : 494/500 = 0,9880 sur `test\_data.h`, que l'ESP32 simulé doit retrouver.

\- Dérive (gaz +400) : KS 0,73 sur `gaz`, sous 0,13 ailleurs. Fog v1 F1 0,953, v2 0,968 sur données dérivées inconnues.



\## Limites



Jeu synthétique facile à séparer ; seulement 6 épisodes `couvant` dans le test ; la vapeur reste sous `gaz` 2000 ; `y\_true` n'existe qu'en simulation ; l'Edge compilé exige un nouveau firmware pour être mis à jour ; Flash/RAM de l'ESP32 non mesurées (compilation Wokwi, Rabah).

