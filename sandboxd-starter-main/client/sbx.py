"""sbx — le client en ligne de commande de sandboxd (TP4).

    python -m client.sbx ls [--status ready]
    python -m client.sbx create --image alpine:3.20 [--wait]
    python -m client.sbx exec sbx-a1b2c3d4 -- ls -la
    python -m client.sbx rm sbx-a1b2c3d4

L'adresse de l'API vient de SANDBOXD_URL (par défaut http://localhost:8000).
Si SANDBOXD_API_KEY est définie, elle est envoyée en Authorization: Bearer.
"""
import argparse
import os
import random
import sys
import time
import uuid

import httpx

API = os.environ.get("SANDBOXD_URL", "http://localhost:8000")
API_KEY = os.environ.get("SANDBOXD_API_KEY")

RETRY_STATUS = {429, 502, 503, 504}  # erreurs passagères : on peut réessayer
IDEMPOTENT = {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}
MAX_TRIES = 6
TIMEOUT = httpx.Timeout(5.0, read=70.0)  # 5 s pour se connecter, 70 s pour un exec long


class ApiError(Exception):
    """Erreur définitive : inutile de réessayer."""


def backoff(attempt: int, response: httpx.Response | None) -> float:
    """Temps d'attente avant le prochain essai : Retry-After s'il est là, sinon exponentiel + hasard."""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
    return random.uniform(0, min(8.0, 0.5 * 2 ** attempt))  # "full jitter"


def request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    """Envoie une requête et renvoie la réponse finale, en tenant face à une API capricieuse."""
    headers = kwargs.get("headers") or {}
    rejouable = method in IDEMPOTENT or "Idempotency-Key" in headers
    last_error = "aucune réponse"

    for attempt in range(MAX_TRIES):
        response = None
        try:
            response = client.request(method, path, timeout=TIMEOUT, **kwargs)
        except httpx.TransportError as exc:  # réseau coupé, timeout, connexion refusée…
            last_error = f"erreur réseau : {exc.__class__.__name__}"
        else:
            if response.status_code not in RETRY_STATUS:
                return response
            last_error = f"HTTP {response.status_code}"

        if not rejouable:
            break  # un POST sans clé ne se rejoue pas : on risquerait un doublon
        if attempt < MAX_TRIES - 1:
            time.sleep(backoff(attempt, response))

    raise ApiError(f"{method} {path} : abandon après {attempt + 1} essai(s), {last_error}")


def fail_on_error(response: httpx.Response) -> httpx.Response:
    """Transforme une réponse 4xx/5xx en ApiError avec le detail du problem+json."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or response.json().get("title")
        except ValueError:
            detail = response.text
        raise ApiError(f"HTTP {response.status_code} : {detail}")
    return response


def cmd_ls(client: httpx.Client, args) -> None:
    """Suit next_page_token jusqu'au bout, une ligne par sandbox."""
    params = {"page_size": 100}
    if args.status:
        params["status"] = args.status
    while True:
        page = fail_on_error(request(client, "GET", "/v1/sandboxes", params=params)).json()
        for sb in page["items"]:
            print(f'{sb["id"]}\t{sb["status"]}\t{sb["image"]}')
        if not page.get("next_page_token"):
            return
        params["page_token"] = page["next_page_token"]


def cmd_create(client: httpx.Client, args) -> int:
    """Création rejouable (une Idempotency-Key, gardée pour chaque essai), puis --wait."""
    key = str(uuid.uuid4())
    r = fail_on_error(request(client, "POST", "/v1/sandboxes", json={"image": args.image},
                              headers={"Idempotency-Key": key}))
    sandbox = r.json()
    if not args.wait:
        print(sandbox["id"])
        return 0

    location = r.headers.get("Location", f'/v1/sandboxes/{sandbox["id"]}')
    deadline = time.monotonic() + 120
    while sandbox["status"] not in ("ready", "failed"):
        if time.monotonic() > deadline:
            raise ApiError(f'{sandbox["id"]} toujours {sandbox["status"]} après 120 s')
        time.sleep(1)
        sandbox = fail_on_error(request(client, "GET", location)).json()

    if sandbox["status"] == "failed":
        print(f'{sandbox["id"]} : la création a échoué', file=sys.stderr)
        return 1
    print(sandbox["id"])
    return 0


def cmd_exec(client: httpx.Client, args) -> int:
    """Affiche stdout et stderr séparément, et sort avec le code de la commande."""
    if not args.cmd:
        raise ApiError("commande manquante (exemple : sbx exec sbx-… -- ls -la)")
    r = fail_on_error(request(client, "POST", f"/v1/sandboxes/{args.id}/exec", json={"cmd": args.cmd}))
    result = r.json()
    sys.stdout.write(result.get("stdout", ""))
    sys.stderr.write(result.get("stderr", ""))
    if result.get("timed_out"):
        print("sbx: la commande a dépassé son timeout", file=sys.stderr)
    code = result.get("exit_code")
    return code if isinstance(code, int) else 1


def cmd_rm(client: httpx.Client, args) -> None:
    """DELETE est idempotent : un 404 (déjà supprimée) n'est pas une erreur."""
    r = request(client, "DELETE", f"/v1/sandboxes/{args.id}")
    if r.status_code not in (204, 404):
        fail_on_error(r)


def main() -> int:
    parser = argparse.ArgumentParser(prog="sbx")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ls"); p.add_argument("--status"); p.set_defaults(func=cmd_ls)
    p = sub.add_parser("create"); p.add_argument("--image", required=True); p.add_argument("--wait", action="store_true"); p.set_defaults(func=cmd_create)
    p = sub.add_parser("exec"); p.add_argument("id"); p.add_argument("cmd", nargs=argparse.REMAINDER); p.set_defaults(func=cmd_exec)
    p = sub.add_parser("rm"); p.add_argument("id"); p.set_defaults(func=cmd_rm)
    args = parser.parse_args()
    if getattr(args, "cmd", None) and args.cmd[:1] == ["--"]:
        args.cmd = args.cmd[1:]
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    with httpx.Client(base_url=API, headers=headers) as client:  # un seul client : connexions réutilisées
        try:
            return args.func(client, args) or 0
        except ApiError as exc:
            print(f"sbx: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
