# Rapport d'attaque

Une fiche par faille trouvée ou subie : reproduction, impact, correctif, test.

## Fiche 1 : sortir de /workspace avec `..`

- **Reproduction** : `GET /v1/sandboxes/{id}/files?path=../etc/passwd`
- **Impact** : lire n'importe quel fichier du conteneur.
- **Correctif** : `safe_path()` refuse les chemins absolus, les segments `..` et les dossiers (400).
- **Test** : la requête renvoie 400 `invalid-path`.

## Fiche 2 : nom de fichier géant (trouvée par Schemathesis)

- **Reproduction** : `PUT /files?path=000…0` (plus de 4000 caractères).
- **Impact** : erreur 500, l'API plante sur une entrée d'utilisateur.
- **Correctif** : tout nom de plus de 255 caractères est refusé en 400.
- **Test** : `make test-contract` passe (541/541).

## Fiche 3 : lien symbolique vers /etc (bonus)

- **Reproduction** : `exec ["ln","-s","/etc","/workspace/etc"]`, puis `GET /files?path=etc/passwd`.
- **Impact** : le chemin semble dans /workspace mais pointe dehors.
- **Correctif** : lecture et écriture vérifient le chemin réel (`readlink -f`) dans le conteneur ; hors de /workspace : 400. Un lien en cible d'écriture est refusé.
- **Test** : la lecture de `etc/passwd` renvoie 400.

## Fiche 4 : fork bomb

- **Reproduction** : `exec ["sh","-c","for i in $(seq 200); do sleep 20 & done"]`
- **Impact** : saturer la machine hôte.
- **Correctif** : `PidsLimit: 64` sur chaque conteneur.
- **Test** : la commande échoue (« can't fork ») et l'hôte reste disponible.

## Fiche 5 : accès réseau depuis la sandbox

- **Reproduction** : `exec ["python","-c","import urllib.request;urllib.request.urlopen('http://example.com')"]`
- **Impact** : exfiltrer des données, attaquer d'autres machines.
- **Correctif** : `NetworkMode: none`.
- **Test** : erreur réseau dans stderr, exit_code non nul.

## Fiche 6 : écrire hors de /workspace

- **Reproduction** : `exec ["sh","-c","echo x > /etc/x"]`
- **Correctif** : racine en lecture seule (`ReadonlyRootfs`), utilisateur 1000, aucune capability.
- **Test** : « Read-only file system ».

## Fiche 7 : utiliser le jeton d'un agent sur une autre sandbox

- **Reproduction** : jeton créé pour sbx-A, `GET /v1/sandboxes/sbx-B` avec ce jeton.
- **Correctif** : `can_use()` : un agent ne voit que sa sandbox ; les autres renvoient 404 (on ne révèle pas leur existence).
- **Test** : 404 sur sbx-B, 200 sur sbx-A, 403 sur `POST /v1/sandboxes`.

## Attaque croisée (binôme voisin)

À compléter en cours : failles trouvées chez le voisin et subies de sa part, avec le jeton qu'il nous a donné.
