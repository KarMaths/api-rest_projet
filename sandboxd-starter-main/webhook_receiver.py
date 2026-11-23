"""Petit récepteur de webhooks : vérifie la signature, l'âge et les doublons.

    python webhook_receiver.py        (écoute sur le port 9000)
Le secret vient de SANDBOXD_WEBHOOK_SECRET, comme pour sandboxd.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.webhooks import verify

SECRET = os.environ.get("SANDBOXD_WEBHOOK_SECRET", "")
DEJA_VUS: set[str] = set()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        event_id = self.headers.get("X-Sandboxd-Event-Id", "")
        if not verify(body, self.headers.get("X-Sandboxd-Signature", ""), SECRET):
            print(f"REFUSÉ  {event_id} : signature invalide ou trop vieille", flush=True)
            self.send_response(401); self.end_headers(); return
        if event_id in DEJA_VUS:
            print(f"DOUBLON {event_id} : ignoré", flush=True)
            self.send_response(200); self.end_headers(); return
        DEJA_VUS.add(event_id)
        event = json.loads(body)
        print(f"OK      {event_id} {event['type']} {event['data']['id']} -> signature vérifiée", flush=True)
        self.send_response(204); self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("récepteur de webhooks sur http://localhost:9000", flush=True)
    HTTPServer(("0.0.0.0", 9000), Receiver).serve_forever()
