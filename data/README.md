\# Jeu de données SmartFire-30 v1



Jeu \*\*synthétique\*\* pour la détection d'incendie (classes 0 normal, 1 perturbation, 2 incendie).

Aucun capteur réel n'a été utilisé : toutes les valeurs sont produites par `ia/generator.py`.



\## Régénérer le jeu



Commande : `python -m ia.make\_dataset` (graine 42, fichier produit : `data/dataset\_v1.csv`).

Le générateur est déterministe : même graine, mêmes données.



\## Variables



| Colonne | Type | Unité / plage | Rôle |

|---|---|---|---|

| `t` | réel | °C, -10 à 120 | feature |

| `h` | réel | %, 0 à 100 | feature |

| `gaz` | entier | ADC 12 bits, 0 à 4095 | feature |

| `flame` | entier | 0 ou 1 | feature |

| `dt` | réel | °C par seconde, (t(n) - t(n-5)) / 5, 0 pendant les 5 premières secondes | feature |

| `y` | entier | 0, 1 ou 2 | label |

| `episode\_id` | entier | identifiant de l'épisode | métadonnée (jamais une feature) |

| `kind` | texte | normal, cuisson, vapeur, incendie, couvant | métadonnée (jamais une feature) |

| `split` | texte | train, val, test | métadonnée, découpage de la graine 42 |



Ordre des features pour tous les modèles : `\[t, h, gaz, flame, dt]` (contrat v1.0, section 4).

Fréquence : 1 mesure par seconde. Les valeurs sont déjà dans l'espace filtré par l'Edge (médiane glissante sur 5 mesures, vote sur 3 pour `flame`) : le jeu ne contient pas de bruit brut de capteur.



\## Méthode de génération



\- Un \*\*épisode\*\* est une suite de mesures à 1 Hz, de 90 à 239 secondes.

\- Cinq types : `normal`, `cuisson`, `vapeur`, `incendie`, `couvant` (feu sans flamme).

\- Un épisode part d'un niveau normal avec un petit bruit gaussien. Pour les types non normaux, une \*\*rampe\*\* monte de 0 à 1 en 20 à 60 secondes à partir d'un instant aléatoire, et chaque capteur reçoit un écart proportionnel à la rampe.

\- Labels : `y` reste à 0 tant que la rampe est inférieure ou égale à 0,15, puis passe à 1 (cuisson, vapeur) ou 2 (incendie, couvant). Le début d'un épisode ressemble à du normal et est donc étiqueté normal.

\- `flame` vaut 1 environ 85 % du temps pour l'incendie avec flamme, 0 pour les autres types.

\- `dt` est calculé \*\*à l'intérieur de chaque épisode\*\*, jamais entre deux épisodes.

\- Bornes physiques : `t` dans \[-10, 120], `h` dans \[0, 100], `gaz` entier dans \[0, 4095].

\- Paramètres exacts (amplitudes, bruit) : voir les constantes de `ia/generator.py`.

\- Contrôle automatique des plages contre le contrat (section 4) : `python -m ia.check\_contract`.



\## Contenu \[M]



| Élément | Valeur |

|---|---|

| Lignes | 82 829 |

| Épisodes | 510 |

| Épisodes normal / cuisson / vapeur / incendie / couvant | 150 / 100 / 100 / 120 / 40 |

| Lignes classe 0 / 1 / 2 | 36 351 / 25 116 / 21 362 |



Découpage \*\*par épisode\*\* (`ia/split.py`, graine 42) :



| Jeu | Épisodes | Lignes | Épisodes couvant |

|---|---|---|---|

| train | 357 | 58 550 | 26 |

| val | 76 | 11 650 | 8 |

| test | 77 | 12 629 | 6 |



\## Prévention des fuites



\- Séparation par épisode : un épisode entier est dans un seul jeu (vérifié par `python -m ia.check\_split`).

\- `dt` calculé à l'intérieur de chaque épisode (vérifié : `dt == 0` sur les 5 premières lignes de chaque épisode).

\- `episode\_id`, `kind` et `split` ne sont jamais utilisés comme features.

\- Les modèles à arbres n'ont pas de normalisation : aucun prétraitement n'est ajusté sur le test.

\- Les hyperparamètres seront réglés sur la validation seulement, le test servira une seule fois.



\## Hypothèses et limites



\- Les ordres de grandeur sont des \*\*conventions du projet\*\* (contrat v1.0, section 4), pas des mesures réelles ni des normes.

\- Les zones des classes se chevauchent volontairement : c'est ce qui rend la fusion multi-capteurs utile.

\- Les plages de `dt` du contrat décrivent la \*\*montée\*\* d'un événement. Une fois la rampe terminée, la température se stabilise et `dt` retombe vers 0.

\- Jeu synthétique : bruit simplifié, aucune panne de capteur (`valid` vaut toujours 1), aucune dérive.

\- Le jeu de test ne contient que 6 épisodes `couvant` : les métriques sur le feu couvant sont peu précises.

\- Passage au réel : collecte de mesures de feux contrôlés et calibration des capteurs.

