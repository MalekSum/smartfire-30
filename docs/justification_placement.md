# Justification du placement des fonctions (Edge, Fog, Cloud)

Critères : latence, bande passante, sécurité, autonomie. Version brouillon : les
arguments sont qualitatifs, les chiffres viendront des mesures (étiquettes [M], [I], [E]).

## Placement retenu (scénario S4 hybride)

| Fonction | Couche | Pourquoi |
|---|---|---|
| Acquisition, filtrage, validité des capteurs | Edge | Au plus près du capteur ; la médiane sur 5 et le vote sur 3 suppriment les valeurs aberrantes avant l'envoi ; le champ valid évite de transmettre des mesures inutilisables. |
| Classification légère et alarme locale | Edge | Latence minimale ; autonomie : l'alarme fonctionne sans Wi-Fi, sans broker et sans Cloud (innovation C) ; modèle limité par la mémoire de l'ESP32. |
| Confirmation et réduction des fausses alarmes | Fog | Modèle plus riche, regarde plusieurs instants ; reste local (confidentialité, faible latence). |
| Tampon en cas de coupure du Cloud | Fog | Le Fog garde les données (file out_q) et les renvoie à la reconnexion ; l'Edge n'a pas la mémoire nécessaire. |
| Stockage global, entraînement, versionnement, dérive | Cloud | Puissance de calcul, vision d'ensemble, historique ; fonctions non urgentes, une panne n'empêche pas l'alarme. |

## Alternatives

| Scénario | Avantage | Limite |
|---|---|---|
| S1 tout-Cloud | Modèle le plus puissant, rien dans l'ESP32 | Latence et dépendance au réseau : sans Cloud, plus de décision. |
| S2 Fog | Décision locale, modèle moyen | Dépend de la passerelle Fog. |
| S3 tout-Edge | Autonome, sans dépendance | Modèle limité par la mémoire, pas de confirmation. |
| S4 hybride (retenu) | L'Edge alarme seul, le Fog confirme | Plus de composants à exploiter ; compromis assumé. |

## Argument bande passante

À 1 Hz, un nœud produit 86 400 mesures par jour [E]. En S4, l'Edge publie une fois
toutes les 10 s tant que y_edge = 0, soit environ 8 640 mesures par jour dans une
journée calme [E]. À confirmer par la mesure réseau (reseau.csv, Khelfa).

## À compléter avec les mesures

- Latence par scénario : docs/resultats/latence.csv (Khelfa)
- Débit par scénario : docs/resultats/reseau.csv (Khelfa)
- Qualité des modèles par couche : docs/resultats/qualite.csv (Bahi)
- Coûts par scénario : docs/resultats/cout.csv (Sid Ahmed)
