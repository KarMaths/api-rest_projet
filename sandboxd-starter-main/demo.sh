#!/usr/bin/env bash
# Démo de soutenance : bash demo.sh   (sandboxd et le récepteur doivent tourner)
set -a; . ./.env; set +a
API=http://localhost:8000
K="Authorization: Bearer $SANDBOXD_API_KEY"
J='Content-Type: application/json'
titre() { echo; echo "=================== $1 ==================="; read -p "(Entrée pour lancer) " _; }
id_de() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

titre "1. L'opérateur crée une sandbox : 202, puis ready"
curl -s -i -X POST $API/v1/sandboxes -H "$K" -H "$J" -d '{"image":"python:3.12-slim"}' | tee /tmp/create.txt | grep -iE "^HTTP|^location"
A=$(tail -n 1 /tmp/create.txt | id_de id)
echo "sandbox A = $A ; on attend qu'elle soit prête…"
for i in $(seq 30); do S=$(curl -s $API/v1/sandboxes/$A -H "$K" | id_de status); [ "$S" != pending ] && break; sleep 1; done
echo "status : $S"

titre "2. Une commande s'exécute, une autre dépasse son timeout"
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["python","-c","print(1+1)"]}'; echo
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sleep","30"],"timeout_seconds":2}'; echo

titre "3. Jeton d'agent : 200 sur sa sandbox, 404 sur celle d'un autre"
B=$(curl -s -X POST $API/v1/sandboxes -H "$K" -H "$J" -d '{"image":"alpine:3.20"}' | id_de id)
T=$(curl -s -X POST $API/v1/sandboxes/$A/tokens -H "$K" | id_de token)
echo "jeton d'agent créé pour $A (autre sandbox : $B)"
curl -s -o /dev/null -w "agent sur SA sandbox       : %{http_code}\n" $API/v1/sandboxes/$A -H "Authorization: Bearer $T"
curl -s -o /dev/null -w "agent sur une AUTRE sandbox : %{http_code}\n" $API/v1/sandboxes/$B -H "Authorization: Bearer $T"
curl -s -o /dev/null -w "agent qui crée une sandbox  : %{http_code}\n" -X POST $API/v1/sandboxes -H "Authorization: Bearer $T" -H "$J" -d '{"image":"alpine:3.20"}'
curl -s -o /dev/null -w "sans aucune clé             : %{http_code}\n" $API/v1/sandboxes

titre "4. Attaques bloquées par le durcissement"
echo "--- qui suis-je ?"
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["id"]}'; echo
echo "--- écrire dans /etc"
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sh","-c","echo x > /etc/x"]}'; echo
echo "--- accès réseau"
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["python","-c","import urllib.request;urllib.request.urlopen(\"http://example.com\",timeout=3)"],"timeout_seconds":10}' | python3 -c "import sys,json;r=json.load(sys.stdin);print('exit_code',r['exit_code'],'|',r['stderr'].strip().splitlines()[-1] if r['stderr'] else '')"
echo "--- fork bomb : on demande 200 processus"
curl -s -X POST $API/v1/sandboxes/$A/exec -H "$K" -H "$J" -d '{"cmd":["sh","-c","for i in $(seq 200); do sleep 20 >/dev/null 2>&1 & done 2>/dev/null; echo \"processus obtenus : $(jobs -p | wc -l) sur 200 demandés\"; kill $(jobs -p) 2>/dev/null"],"timeout_seconds":10}' | python3 -c "import sys,json;r=json.load(sys.stdin);print(r['stdout'].strip(), '-> limite PidsLimit 64')"
echo "--- chemin hors de /workspace"
curl -s -o /dev/null -w "lire ../etc/passwd : %{http_code}\n" "$API/v1/sandboxes/$A/files?path=../etc/passwd" -H "$K"

titre "5. Webhook signé : regarder le terminal du récepteur"
echo "Le récepteur doit afficher : OK evt-… sandbox.ready … signature vérifiée"
.venv/bin/python -m tests.test_webhooks

titre "6. /metrics et le journal d'audit"
curl -s $API/metrics | grep -E "^sandboxes_active|^http_requests_total" | head -8
echo "--- audit.log"
tail -n 3 audit.log

echo; echo "Nettoyage"; curl -s -o /dev/null -X DELETE $API/v1/sandboxes/$A -H "$K"; curl -s -o /dev/null -X DELETE $API/v1/sandboxes/$B -H "$K"; echo "fin"
