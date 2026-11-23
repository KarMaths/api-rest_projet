"""Webhooks signés : sandbox.ready, sandbox.failed, sandbox.expired.

Configuration (environnement) :
  SANDBOXD_WEBHOOK_URLS    les URL abonnées, séparées par des virgules
  SANDBOXD_WEBHOOK_SECRET  le secret partagé avec les récepteurs

Chaque envoi porte :
  X-Sandboxd-Event-Id   identifiant unique (pour repérer les doublons)
  X-Sandboxd-Signature  t=<horodatage>,v1=<HMAC-SHA256 hex de "<t>.<corps>">
Nouvelles tentatives : 4 essais, après 1 s, 2 s puis 4 s.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

import httpx

URLS = [u.strip() for u in os.environ.get("SANDBOXD_WEBHOOK_URLS", "").split(",") if u.strip()]
SECRET = os.environ.get("SANDBOXD_WEBHOOK_SECRET", "")
TOLERANCE = 300  # un horodatage de plus de 5 minutes est refusé


def sign(body: bytes, timestamp: int, secret: str) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(body: bytes, header: str, secret: str, now: float | None = None) -> bool:
    """Vérifie la signature et l'âge du message (utilisé par le récepteur et les tests)."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        recu = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((now or time.time()) - timestamp) > TOLERANCE:
        return False
    attendu = sign(body, timestamp, secret).split("v1=", 1)[1]
    return hmac.compare_digest(attendu, recu)


def _deliver(url: str, body: bytes, event_id: str) -> None:
    for attente in (0, 1, 2, 4):
        time.sleep(attente)
        timestamp = int(time.time())
        headers = {"Content-Type": "application/json", "X-Sandboxd-Event-Id": event_id,
                   "X-Sandboxd-Signature": sign(body, timestamp, SECRET)}
        try:
            r = httpx.post(url, content=body, headers=headers, timeout=5.0)
            if r.status_code < 300:
                return
        except httpx.HTTPError:
            pass


def emit(event_type: str, sandbox: dict) -> None:
    """Envoie l'événement à toutes les URL abonnées, en tâche de fond."""
    if not URLS or not SECRET:
        return
    event_id = "evt-" + secrets.token_hex(8)
    body = json.dumps({"id": event_id, "type": event_type, "created_at": int(time.time()),
                       "data": sandbox}).encode()
    for url in URLS:
        threading.Thread(target=_deliver, args=(url, body, event_id), daemon=True).start()
