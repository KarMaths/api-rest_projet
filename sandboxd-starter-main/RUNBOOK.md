# Runbook sandboxd

## 1. Une sandbox reste bloquée en pending

**Symptômes** : `GET /v1/sandboxes/{id}` renvoie `"status": "pending"` depuis plus d'une minute.

**Diagnostic**
- `docker ps -a --filter label=sandboxd.id=<id>` : le conteneur existe-t-il ?
- logs de sandboxd (lignes JSON) : erreur Docker pendant la création ?
- `docker images` : l'image est-elle téléchargée ? Un premier `pull` peut être long.
- `curl localhost:8000/readyz` : Docker répond-il ?

**Correction**
- Télécharger les images à l'avance : `docker pull python:3.12-slim node:22-slim alpine:3.20`.
- Supprimer la sandbox (`DELETE`) puis la recréer.
- Si Docker ne répond pas : voir la situation 2.

## 2. Docker indisponible

**Symptômes** : `/readyz` renvoie 503 ; les créations passent en `failed` ; erreurs 500 sur exec.

**Diagnostic**
- `docker info` dans le terminal : erreur de connexion ?
- Sous Windows : Docker Desktop est-il lancé ? Intégration WSL activée pour Ubuntu ?
- `ls -l /var/run/docker.sock` : le socket existe-t-il ? (`DOCKER_SOCKET` sinon)

**Correction**
- Relancer Docker Desktop (ou `sudo systemctl restart docker` sous Linux).
- Attendre que `/readyz` repasse à 200, puis relancer les créations échouées.
- Les sandboxes en mémoire sont perdues si sandboxd redémarre : `make clean` supprime les conteneurs orphelins.

## 3. Rotation de la clé opérateur

**Quand** : clé exposée (commit, capture d'écran, log) ou rotation planifiée.

**Diagnostic** : chercher la clé dans l'historique (`git log -p | grep <début de la clé>`), vérifier `audit.log` pour des actions suspectes.

**Correction**
1. Générer une nouvelle clé : `python3 -c "import secrets; print(secrets.token_hex(32))"`.
2. La mettre dans `.env` (`SANDBOXD_API_KEY=`), redémarrer sandboxd (`make run`).
3. Donner la nouvelle clé aux opérateurs et à la CI ; l'ancienne renvoie 401.
4. Changer aussi `SANDBOXD_JWT_SECRET` si elle a pu fuiter : tous les jetons d'agent deviennent invalides (401).
