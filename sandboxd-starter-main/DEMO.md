# Démo de soutenance (dans l'ordre)

Préparation : 3 terminaux Ubuntu dans le dossier du projet.
- T1 : `make run`
- T2 : `make receiver`
- T3 : les commandes ci-dessous

```bash
set -a; . ./.env; set +a
K="Authorization: Bearer $SANDBOXD_API_KEY"
J='Content-Type: application/json'
```

## 1. L'opérateur crée une sandbox : 202, puis ready
```bash
curl -i -X POST localhost:8000/v1/sandboxes -H "$K" -H "$J" -d '{"image":"python:3.12-slim"}'
A=sbx-XXXXXXXX            # copier l'id
curl -s localhost:8000/v1/sandboxes/$A -H "$K"; echo
```
(T2 affiche : `OK evt-… sandbox.ready … signature vérifiée` → point 5)

## 2. Une commande s'exécute ; une autre dépasse son timeout
```bash
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["python","-c","print(1+1)"]}'; echo
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sleep","30"],"timeout_seconds":2}'; echo
```
→ `"timed_out": true, "exit_code": 137`

## 3. Le jeton d'agent : OK sur sa sandbox, 404 sur celle d'un autre
```bash
curl -s -X POST localhost:8000/v1/sandboxes -H "$K" -H "$J" -d '{"image":"alpine:3.20"}'; echo
B=sbx-YYYYYYYY            # l'id de la 2e sandbox
T=$(curl -s -X POST localhost:8000/v1/sandboxes/$A/tokens -H "$K" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w "agent sur sa sandbox : %{http_code}\n" localhost:8000/v1/sandboxes/$A -H "Authorization: Bearer $T"
curl -s -o /dev/null -w "agent sur une autre : %{http_code}\n"  localhost:8000/v1/sandboxes/$B -H "Authorization: Bearer $T"
curl -s -o /dev/null -w "agent crée une sandbox : %{http_code}\n" -X POST localhost:8000/v1/sandboxes -H "Authorization: Bearer $T" -H "$J" -d '{"image":"alpine:3.20"}'
curl -s -o /dev/null -w "sans clé : %{http_code}\n" localhost:8000/v1/sandboxes
```
→ 200, 404, 403, 401

## 4. Attaques bloquées par le durcissement
```bash
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sh","-c","for i in $(seq 200); do sleep 20 & done"],"timeout_seconds":5}'; echo
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["python","-c","import urllib.request;urllib.request.urlopen(\"http://example.com\",timeout=3)"]}'; echo
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sh","-c","echo x > /etc/x"]}'; echo
curl -s -X POST localhost:8000/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["id"]}'; echo
```
→ fork impossible ; réseau injoignable ; Read-only file system ; uid=1000

## 5. Un webhook signé reçu et vérifié
Regarder T2 : `OK evt-… sandbox.ready sbx-… -> signature vérifiée`.
Tests : `make test-webhooks` (signature invalide, doublon, horodatage trop vieux).

## 6. /metrics et une ligne du journal d'audit
```bash
curl -s localhost:8000/metrics | grep -E "sandboxes_active|http_requests_total" | head
tail -n 3 audit.log
```
