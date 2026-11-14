\# Déclaration d'usage de l'IA : Bensoula Abdelbahi



\## Outil

Claude (Anthropic), assistant conversationnel.



\## Usage

\- Explication des concepts (split par épisode, forêts aléatoires, métriques, compression, dérive).

\- Rédaction de code à partir du contrat v1.0 et du brief 05, puis relecture par moi.

\- Aide à la vérification des sorties de commandes.



\## Parties du projet concernées

| Fichier | Usage de l'IA |

|---|---|

| `ia/generator.py` | proposition de code, corrigé après le contrôle de contrat (ajout de `ecart\_h`) |

| `ia/check\_contract.py` | proposition de code, corrigé (dt mesuré pendant la montée) |

| `ia/make\_stubs.py`, `ia/check\_stubs.py` | proposition de code |

| `ia/requirements\*.txt` | versions tirées du contrat §8 |



\## Ce que j'ai vérifié et exécuté moi-même

\- Exécution de `python -m ia.make\_stubs` et `python -m ia.check\_stubs` : sorties conformes (stubs v0 générés, les 3 modèles se rechargent depuis le registre).

\- Contrôle de `edge/model\_stub.h` : classe `Eloquent::ML::Port::RandomForest`, `predict(float \*x)`, features `x\[0]` à `x\[4]`.

\- Rebase de ma branche `feat/bahi-ia` sur `main` et push.



\## Ce que j'ai modifié moi-même

\- À COMPLÉTER : changements que tu as faits toi-même dans le code.



\## Limites connues

\- Équivalence code C / Python non encore vérifiée (étape F).

\- Je dois pouvoir expliquer chaque ligne de `generator.py`, `train.py` et `metrics.py`.

