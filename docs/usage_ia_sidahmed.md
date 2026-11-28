# Déclaration d'usage de l'IA : Sid Ahmed Ferguene

- Outil : Claude (Anthropic)
- Usage : guide d'installation (WSL, Docker, Git), structure du schéma d'architecture, tableau des flux tiré du contrat
- Fichiers concernés : docs/outils_sidahmed.md, docs/schemas/
- Ce que j'ai vérifié moi-même : chaque QoS comparé à la section 5 du contrat, les versions des outils relevées sur ma machine, le schéma dessiné et relu par moi

## Mise à jour : infrastructure Docker
- Usage : code de cloud/main.py, fog/service/service.py, Dockerfiles et docker-compose.yml (adaptés du brief 02, avec deux ajouts : reconnexion MQTT et gestion des messages mal formés)
- Fichiers concernés : cloud/, fog/service/, fog/Dockerfile, fog/nodered/, docker-compose.yml
- Ce que j'ai vérifié moi-même : docker compose up sur ma machine, 4 services Up, /api/health, décision S4 reçue sur fog/resultats, ligne en base via /api/stats, versions Python et scikit-learn identiques au contrat

## Mise à jour : justification du placement
- Usage : structure du tableau docs/justification_placement.md (fonctions, couches, alternatives S1 à S4)
- Ce que j'ai vérifié moi-même : arguments comparés au contrat (sections 2 et 3), calcul 86 400 et 8 640 mesures par jour

## Mise à jour : bascule du Fog sur le broker public de développement
- Usage : aide au guidage pas à pas (lecture du code de fog/service/service.py, commandes de test, modification de MQTT_HOST dans le .env local)
- Fichiers concernés : .env local (non versionné), docs/outils_sidahmed.md
- Ce que j'ai vérifié moi-même : connexion à broker.emqx.io en anonyme puis avec l'utilisateur fog30 (mot de passe vide) par mosquitto_pub/sub ; après la bascule, une mesure publiée sur m2i2a/equipe30/edge/capteurs a donné une décision sur fog/resultats (y_fog 2, confirme true) et le compteur total de /api/stats est passé de 4 à 5 ; versions Node-RED relevées dans les logs du conteneur

## Mise à jour : tableau de bord Node-RED
- Usage : conception des flux Node-RED du tableau de bord (fog/nodered/flows.json) à partir de mon export, avec explication des nœuds
- Fichiers concernés : fog/nodered/flows.json, simulation/captures/
- Ce que j'ai vérifié moi-même : flux chargé dans Node-RED, décisions normal, perturbation et incendie affichées, compteurs relevés avant et après chaque mesure (règle des fausses alarmes évitées vérifiée), Cloud coupé (affichage hors ligne et tirets), Fog coupé (offline par Last Will)
- Dockerfile Node-RED : copie du flux dans l'image et version du dashboard figée (3.6.6) ; vérifié par un build, les logs de démarrage (dashboard 3.6.6, flux chargé depuis /data/flows.json) et un accès à /ui sur une image de test (port 1881).
