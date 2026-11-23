# sandboxd

API REST qui crée, pilote et détruit des sandboxes (conteneurs Docker isolés).
Binôme : Karl JEAN / Anas Louraibi. Le contrat fait foi : `openapi.yaml`.

## Installer et lancer

Prérequis : Python 3.11+, Node 18+, Docker (sous Windows : WSL 2 + Docker Desktop).

```bash
cp .env.example .env     # puis remplir les secrets (voir ci-dessous)
make install
make run                 # sandboxd sur http://localhost:8000
```

Générer des secrets : `python3 -c "import secrets; print(secrets.token_hex(32))"`

| Commande | Rôle |
|---|---|
| `make lint` | vérifie le contrat |
| `make test-contract` | Schemathesis contre sandboxd (sandboxd doit tourner) |
| `make flaky` | API capricieuse du TP4, port 8001 |
| `make receiver` | récepteur de webhooks, port 9000 |
| `make test-webhooks` | tests de signature des webhooks |
| `make clean` | supprime les conteneurs créés par sandboxd |

## Un exemple curl par opération

```bash
K="Authorization: Bearer $SANDBOXD_API_KEY"
# createSandbox -> 202 + Location
curl -i -X POST localhost:8000/v1/sandboxes -H "$K" -H 'Content-Type: application/json' -d '{"image":"python:3.12-slim"}'
# listSandboxes
curl -s "localhost:8000/v1/sandboxes?status=ready&page_size=20" -H "$K"
# getSandbox
curl -i localhost:8000/v1/sandboxes/sbx-a1b2c3d4 -H "$K"
# updateSandbox (If-Match facultatif)
curl -X PATCH localhost:8000/v1/sandboxes/sbx-a1b2c3d4 -H "$K" -H 'Content-Type: application/merge-patch+json' -d '{"ttl_seconds":1800}'
# deleteSandbox -> 204
curl -X DELETE localhost:8000/v1/sandboxes/sbx-a1b2c3d4 -H "$K"
# createAgentToken -> 201
curl -X POST localhost:8000/v1/sandboxes/sbx-a1b2c3d4/tokens -H "$K"
# execCommand
curl -X POST localhost:8000/v1/sandboxes/sbx-a1b2c3d4/exec -H "$K" -H 'Content-Type: application/json' -d '{"cmd":["ls","-la"],"timeout_seconds":5}'
# writeFile -> 201 / 204
curl -X PUT "localhost:8000/v1/sandboxes/sbx-a1b2c3d4/files?path=hello.py" -H "$K" -H 'Content-Type: application/octet-stream' --data-binary 'print("bonjour")'
# readFile
curl "localhost:8000/v1/sandboxes/sbx-a1b2c3d4/files?path=hello.py" -H "$K"
# santé et métriques
curl localhost:8000/healthz; curl localhost:8000/readyz; curl localhost:8000/metrics
```

## Client sbx (TP4)

```bash
export SANDBOXD_URL=http://localhost:8000 SANDBOXD_API_KEY=...
.venv/bin/python -m client.sbx create --image alpine:3.20 --wait
.venv/bin/python -m client.sbx exec sbx-a1b2c3d4 -- ls -la
.venv/bin/python -m client.sbx ls
.venv/bin/python -m client.sbx rm sbx-a1b2c3d4
```

## Sécurité (résumé)

- Opérateur : clé d'API (`SANDBOXD_API_KEY`). Agent : jeton JWT de 15 min limité à une sandbox ; sur une autre sandbox il reçoit 404, sur une route d'opérateur 403.
- Conteneurs : réseau coupé, utilisateur 1000, racine en lecture seule (sauf /workspace et /tmp), aucune capability, 64 processus au plus, no-new-privileges.
- Quota de sandboxes actives, expiration automatique (terminated), chemins de fichiers vérifiés, journal d'audit `audit.log`.
- `/metrics` est hors du contrat : c'est un point de supervision (format Prometheus), pas une route métier.
