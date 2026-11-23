# Déclaration d'usage de l'IA : Sid Ahmed Ferguene

- Outil : Claude (Anthropic)
- Usage : guide d'installation (WSL, Docker, Git), structure du schéma d'architecture, tableau des flux tiré du contrat
- Fichiers concernés : docs/outils_sidahmed.md, docs/schemas/
- Ce que j'ai vérifié moi-même : chaque QoS comparé à la section 5 du contrat, les versions des outils relevées sur ma machine, le schéma dessiné et relu par moi

## Mise à jour : infrastructure Docker
- Usage : code de cloud/main.py, fog/service/service.py, Dockerfiles et docker-compose.yml (adaptés du brief 02, avec deux ajouts : reconnexion MQTT et gestion des messages mal formés)
- Fichiers concernés : cloud/, fog/service/, fog/Dockerfile, fog/nodered/, docker-compose.yml
- Ce que j'ai vérifié moi-même : docker compose up sur ma machine, 4 services Up, /api/health, décision S4 reçue sur fog/resultats, ligne en base via /api/stats, versions Python et scikit-learn identiques au contrat
