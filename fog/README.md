# Fog : service d'inférence, broker et dashboard

Contenu : service/ (service Python), mosquitto/config/ (broker, Khelfa), nodered/ (dashboard), Dockerfile (service).

## Lancement
Depuis la racine du dépôt :
    cp .env.example .env     (renseigner CLOUD_API_KEY dans .env, jamais dans Git)
    docker compose up -d --build
    docker compose ps        (4 services Up)
    docker compose logs -f fog
Dashboard : http://localhost:1880/ui  (éditeur : http://localhost:1880)
Arrêt le soir : docker compose stop. Ne jamais utiliser "down -v" (efface le dashboard et la base).

## Service d'inférence (service/service.py)
Variables : MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TLS, CLOUD_URL, CLOUD_API_KEY (lues dans .env, aucune valeur en dur).
Il s'abonne à edge/capteurs (QoS 0) et edge/commande/mode (QoS 1), et publie fog/resultats (QoS 1), fog/statut (QoS 1, retained, Last Will) et edge/commande/modele (QoS 1, retained). Préfixe : m2i2a/equipe30/.
Comportement selon le scénario :
| Scénario | Décision du Fog |
|---|---|
| S1 | relaie la mesure au Cloud (POST /api/infer) ; si le Cloud est coupé, pas de décision (y_fog = -1) |
| S2 et S4 | infère avec le modèle Fog ; en S4, confirme = (y_fog == 2) |
| S3 | ne décide pas : y_final = y_edge |
Trois fils d'exécution : réception MQTT ; vérification de la version du modèle toutes les 30 s (rechargement à chaud, message "Modèle Fog chargé, version N") ; envoi au Cloud depuis un tampon de 10 000 éléments (aucune mesure perdue si le Cloud est coupé, renvoi à la reconnexion).
Le modèle Edge compilé en C ne se met pas à jour à chaud : seuls mv, n_confirm et seuil_classique le sont (edge/commande/modele).

## Broker
Développement : le Fog et le dashboard utilisent le broker public broker.emqx.io:1883 (option A du contrat). Ce broker n'a aucune authentification : n'importe qui connaissant le préfixe peut lire ou injecter des mesures. Aucune donnée personnelle dans les messages.
Preuves de sécurité (comptes, ACL, TLS) : Mosquitto local (service mosquitto), avec MQTT_HOST=mosquitto.

## Dashboard Node-RED
Flux : nodered/flows.json, embarqué dans l'image (Dockerfile) avec node-red-dashboard 3.6.6.
Contenu : décision (vert, orange, rouge), courbes des 10 dernières minutes, compteurs (GET /api/stats toutes les 5 s), états Edge, Fog et Cloud, versions des modèles, sélecteur de scénario, journal des alertes.
Après une modification dans l'éditeur, ré-exporter le flux : docker compose cp nodered:/data/flows.json fog/nodered/flows.json
Limites : le bloc Décision garde la dernière décision reçue ; le broker du dashboard est écrit dans le nœud de configuration (à changer pour le Mosquitto sécurisé, identifiants hors Git).
