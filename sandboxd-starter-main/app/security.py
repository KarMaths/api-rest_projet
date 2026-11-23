"""Authentification : clé de l'opérateur et jetons d'agent (JWT HS256, 15 min).

Les secrets viennent de l'environnement (jamais de Git) :
  SANDBOXD_API_KEY     la clé de l'opérateur
  SANDBOXD_JWT_SECRET  la clé qui signe les jetons d'agent
"""
import base64
import hashlib
import hmac
import json
import os
import time

from .errors import Problem

API_KEY = os.environ.get("SANDBOXD_API_KEY", "")
JWT_SECRET = os.environ.get("SANDBOXD_JWT_SECRET", "")
TOKEN_TTL = 15 * 60  # 15 minutes

if not API_KEY or not JWT_SECRET:
    raise RuntimeError("SANDBOXD_API_KEY et SANDBOXD_JWT_SECRET doivent être définies (voir .env.example)")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_agent_token(sandbox_id: str) -> tuple[str, int]:
    """Fabrique un jeton d'agent limité à une sandbox. Renvoie (jeton, expiration)."""
    exp = int(time.time()) + TOKEN_TTL
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"sub": sandbox_id, "scope": "agent", "exp": exp}).encode())
    signature = hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}", exp


def _read_agent_token(token: str) -> str | None:
    """Vérifie un jeton d'agent. Renvoie l'id de sa sandbox, ou None s'il est faux ou expiré."""
    try:
        header, payload, signature = token.split(".")
        attendu = hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(attendu, _unb64(signature)):
            return None
        claims = json.loads(_unb64(payload))
        if claims.get("scope") != "agent" or claims.get("exp", 0) < time.time():
            return None
        return claims.get("sub")
    except (ValueError, TypeError):
        return None


def who(request) -> dict:
    """Qui appelle ? {"role": "operator"} ou {"role": "agent", "sandbox": id}. Sinon 401."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Problem(401, "unauthorized", "en-tête Authorization: Bearer manquant",
                      headers={"WWW-Authenticate": "Bearer"})
    token = auth[7:].strip()
    if hmac.compare_digest(token.encode(), API_KEY.encode()):
        caller = {"role": "operator"}
    else:
        sandbox_id = _read_agent_token(token)
        if sandbox_id is None:
            raise Problem(401, "unauthorized", "clé ou jeton invalide ou expiré",
                          headers={"WWW-Authenticate": "Bearer"})
        caller = {"role": "agent", "sandbox": sandbox_id}
    request.state.who = caller
    return caller


def operator_only(request) -> dict:
    """Réservé à l'opérateur : un agent reçoit 403."""
    caller = who(request)
    if caller["role"] != "operator":
        raise Problem(403, "forbidden", "réservé à l'opérateur")
    return caller


def can_use(request, sandbox_id: str) -> dict:
    """L'opérateur peut tout ; un agent seulement sa sandbox. Celle d'un autre : 404."""
    caller = who(request)
    if caller["role"] == "agent" and caller["sandbox"] != sandbox_id:
        raise Problem(404, "not-found", f"{sandbox_id} n'existe pas")
    return caller
