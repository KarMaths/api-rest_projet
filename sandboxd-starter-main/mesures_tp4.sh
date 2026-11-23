#!/usr/bin/env bash
# Mesures du TP4 : client naïf (squelette du prof) puis notre client. make flaky doit tourner.
export SANDBOXD_URL=http://localhost:8001; unset SANDBOXD_API_KEY
PY=$PWD/.venv/bin/python
stats() { curl -s localhost:8001/_stats; echo; }

mesurer() {  # $1 = dossier qui contient client/sbx.py
  ( cd "$1"
    echo "sbx ls | wc -l        : $($PY -m client.sbx ls 2>/dev/null | wc -l)"
    echo "doublons dans ls      : $($PY -m client.sbx ls 2>/dev/null | sort | uniq -d | wc -l)"
    echo -n "stats avant          : "; stats
    ok=0; for i in $(seq 20); do $PY -m client.sbx create --image alpine:3.20 >/dev/null 2>&1 && ok=$((ok+1)); done
    echo "créations réussies    : $ok / 20"
    echo -n "stats après          : "; stats )
}

echo "===== AVANT : client naïf du squelette ====="
mesurer ../sandboxd-tp4
echo
echo "===== APRÈS : notre client ====="
mesurer .
echo
echo "===== create --wait, rm deux fois ====="
ID=$($PY -m client.sbx create --image alpine:3.20 --wait); echo "create --wait : $ID"
$PY -m client.sbx rm $ID; echo "rm 1 : code $?"
$PY -m client.sbx rm $ID; echo "rm 2 : code $?"
