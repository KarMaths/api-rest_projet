"""sandboxd — l'API qui respecte le contrat (openapi.yaml).

Fournis par le kit : le client Docker (docker.py), les erreurs problem+json
(errors.py), le stockage en mémoire, provision() et getSandbox.
Écrits par le binôme :
  TP3  toutes les routes, Idempotency-Key, ETag / If-Match
  D    authentification (clé opérateur, jeton d'agent), quotas, expiration, audit
  E    webhooks signés (app/webhooks.py)
  F    /readyz, /metrics, logs JSON avec request_id
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import docker, webhooks
from .errors import Problem, install
from .security import can_use, make_agent_token, operator_only

app = FastAPI(title="sandboxd", openapi_url=None, docs_url=None, redoc_url=None)
install(app)

SANDBOXES: dict[str, dict] = {}  # id -> sandbox (en mémoire : perdue au redémarrage)
IDEMPOTENCY: dict[str, tuple[str, str]] = {}  # clé -> (empreinte du corps, id de la sandbox)
LOCK = threading.Lock()

MAX_FILE = 96 * 1024  # taille maximale d'un fichier écrit (passé en argument d'exec), au-delà : 413
MAX_SANDBOXES = int(os.environ.get("SANDBOXD_MAX_SANDBOXES", "10"))  # quota de sandboxes actives
AUDIT_LOG = os.environ.get("SANDBOXD_AUDIT_LOG", "audit.log")


# ---------- outils fournis par le kit ----------

def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return "sbx-" + secrets.token_hex(4)


def public(sb: dict) -> dict:
    """La représentation JSON d'une sandbox, conforme au schéma Sandbox."""
    return {
        "id": sb["id"], "image": sb["image"], "status": sb["status"], "ttl_seconds": sb["ttl_seconds"],
        "limits": sb["limits"], "created_at": iso(sb["created_at"]),
        "expires_at": iso(expires_at(sb)),
    }


def expires_at(sb: dict) -> datetime:
    return sb["created_at"] + timedelta(seconds=sb["ttl_seconds"])


def get_or_404(sandbox_id: str) -> dict:
    sb = SANDBOXES.get(sandbox_id)
    if sb is None:
        raise Problem(404, "not-found", f"{sandbox_id} n'existe pas")
    return sb


async def read_json(request: Request, model: type[BaseModel], media_types: tuple[str, ...]) -> BaseModel:
    """Lit le corps : Content-Type refusé (415), JSON invalide (400), contenu invalide (422)."""
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in media_types:
        raise Problem(415, "unsupported-media-type", f"attendu : {', '.join(media_types)}")
    try:
        data = json.loads(await request.body())
    except ValueError:
        raise Problem(400, "invalid-json", "le corps n'est pas du JSON valide")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise Problem(422, "validation", f"{'.'.join(map(str, first['loc'])) or 'corps'} : {first['msg']}")


def provision(sandbox_id: str) -> None:
    """Tâche de fond : crée le conteneur, puis passe la sandbox en ready ou failed (+ webhook)."""
    sb = SANDBOXES.get(sandbox_id)
    if sb is None:
        return
    try:
        cid = docker.create_container(sb["image"], sb["limits"]["cpus"], sb["limits"]["memory_mb"],
                                      {"sandboxd": "1", "sandboxd.id": sandbox_id})
        with LOCK:
            if sandbox_id not in SANDBOXES:  # détruite entre-temps
                docker.remove_container(cid)
                return
            sb.update(container_id=cid, status="ready")
        webhooks.emit("sandbox.ready", public(sb))
    except docker.DockerError:
        sb.update(status="failed")
        webhooks.emit("sandbox.failed", public(sb))


# ---------- nos outils ----------

def etag(sb: dict) -> str:
    """La version d'une sandbox : une empreinte de son contenu (bonus ETag)."""
    contenu = json.dumps(public(sb), sort_keys=True).encode()
    return '"' + hashlib.sha256(contenu).hexdigest()[:16] + '"'


def ready_or_409(sb: dict) -> None:
    """Refuse l'opération si la sandbox n'est pas prête (pending, failed, terminated)."""
    if sb["status"] != "ready":
        raise Problem(409, "not-ready", f"{sb['id']} n'est pas prête (status {sb['status']})")


def safe_path(path: str | None) -> str:
    """Vérifie le chemin du fichier : relatif à /workspace, sans '..', pas un dossier."""
    if not path:
        raise Problem(400, "invalid-path", "le paramètre path est obligatoire")
    if len(path) > 4096 or "\x00" in path or "\\" in path:
        raise Problem(400, "invalid-path", "chemin invalide")
    if path.startswith("/"):
        raise Problem(400, "invalid-path", "le chemin doit être relatif à /workspace")
    parts = path.split("/")
    if ".." in parts:
        raise Problem(400, "invalid-path", 'le chemin ne doit pas contenir ".."')
    if "" in parts or path.endswith("/."):
        raise Problem(400, "invalid-path", "le chemin désigne un dossier")
    if any(len(part.encode()) > 255 for part in parts):  # limite de Linux pour un nom de fichier
        raise Problem(400, "invalid-path", "un nom de fichier ou de dossier dépasse 255 caractères")
    return path


def audit(request: Request, action: str, sandbox_id: str | None, detail: str = "") -> None:
    """Une ligne JSON par action dans le journal d'audit : qui, quoi, sur quelle sandbox."""
    caller = getattr(request.state, "who", None) or {"role": "anonyme"}
    acteur = "operator" if caller["role"] == "operator" else f"agent:{caller.get('sandbox', '?')}"
    line = {"ts": iso(now()), "request_id": getattr(request.state, "request_id", None),
            "actor": acteur, "action": action, "sandbox": sandbox_id}
    if detail:
        line["detail"] = detail
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


# Lecture et écriture de fichiers par exec (le /workspace du conteneur est un tmpfs,
# la racine est en lecture seule). Le script vérifie aussi le chemin RÉEL avec
# readlink -f : un lien symbolique vers /etc est refusé (faille ln -s /etc /workspace/etc).
READ_SCRIPT = r'''
p=$(readlink -f -- "$1") || exit 2
case "$p" in /workspace/*) ;; *) exit 4;; esac
[ -d "$p" ] && exit 5
[ -f "$p" ] || exit 2
base64 "$p"
'''
WRITE_SCRIPT = r'''
d=$(dirname -- "$2")
[ -d "$d" ] || exit 2
p=$(readlink -f -- "$d") || exit 2
case "$p" in /workspace|/workspace/*) ;; *) exit 4;; esac
t="$p/$(basename -- "$2")"
[ -L "$t" ] && exit 4
[ -d "$t" ] && exit 5
e=0; [ -e "$t" ] && e=1
printf %s "$1" | base64 -d > "$t" || exit 6
exit $((10+e))
'''


def read_in_sandbox(cid: str, path: str) -> bytes:
    res = docker.exec_command(cid, ["sh", "-c", READ_SCRIPT, "sh", path], 10)
    code = res["exit_code"]
    if code == 0:
        return base64.b64decode(res["stdout"])
    if code in (4, 5):
        raise Problem(400, "invalid-path", f"{path} sort de /workspace ou est un dossier")
    raise Problem(404, "file-not-found", f"/workspace/{path} n'existe pas")


def write_in_sandbox(cid: str, path: str, data: bytes) -> bool:
    payload = base64.b64encode(data).decode()
    res = docker.exec_command(cid, ["sh", "-c", WRITE_SCRIPT, "sh", payload, path], 10)
    code = res["exit_code"]
    if code in (10, 11):
        return code == 10  # True si le fichier a été créé
    if code in (4, 5):
        raise Problem(400, "invalid-path", f"{path} sort de /workspace ou est un dossier")
    if code == 2:
        raise Problem(404, "not-found", "le dossier parent n'existe pas")
    raise Problem(409, "not-ready", f"écriture impossible (code {code})")


# ---------- les formulaires (= les schémas du contrat) ----------

class LimitsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cpus: float = Field(1, ge=0.1, le=2)
    memory_mb: int = Field(512, ge=64, le=1024)


class SandboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    image: Literal["python:3.12-slim", "node:22-slim", "alpine:3.20"]
    ttl_seconds: int = Field(600, ge=60, le=3600)
    limits: LimitsIn = LimitsIn()


class SandboxPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ttl_seconds: int = Field(ge=60, le=3600)


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cmd: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(10, ge=1, le=60)


# ---------- logs JSON, request_id et métriques (bloc F) ----------

METRICS_LOCK = threading.Lock()
REQUESTS: dict[tuple[str, str, int], int] = {}        # (méthode, route, code) -> nombre
DURATIONS: dict[tuple[str, str], list[float]] = {}    # (méthode, route) -> [somme, nombre]


@app.middleware("http")
async def observe(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or secrets.token_hex(8)
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    route = request.scope.get("route")
    route = getattr(route, "path", "inconnue")
    with METRICS_LOCK:
        key = (request.method, route, response.status_code)
        REQUESTS[key] = REQUESTS.get(key, 0) + 1
        total = DURATIONS.setdefault((request.method, route), [0.0, 0])
        total[0] += duration
        total[1] += 1

    caller = getattr(request.state, "who", None) or {}
    print(json.dumps({
        "ts": iso(now()), "level": "info", "request_id": request.state.request_id,
        "method": request.method, "path": request.url.path, "status": response.status_code,
        "duration_ms": round(duration * 1000, 1), "actor": caller.get("role"),
    }), flush=True)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


# ---------- expiration : les sandboxes expirées sont détruites (bloc D) ----------

def reaper() -> None:
    while True:
        time.sleep(2)
        for sb in list(SANDBOXES.values()):
            if sb["status"] in ("pending", "ready") and expires_at(sb) <= now():
                if sb.get("container_id"):
                    try:
                        docker.remove_container(sb["container_id"])
                    except docker.DockerError:
                        continue  # on réessaiera au prochain tour
                sb.update(status="terminated", container_id=None)
                webhooks.emit("sandbox.expired", public(sb))
                with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": iso(now()), "actor": "sandboxd", "action": "expire",
                                        "sandbox": sb["id"]}) + "\n")


threading.Thread(target=reaper, daemon=True).start()


# ---------- createSandbox : POST /v1/sandboxes ----------

@app.post("/v1/sandboxes")
async def create_sandbox(request: Request, idempotency_key: str | None = Header(None)):
    operator_only(request)
    body = await read_json(request, SandboxCreate, ("application/json",))

    # Idempotency-Key : même clé et même corps = même réponse, autre corps = 409
    empreinte = json.dumps(body.model_dump(), sort_keys=True)
    if idempotency_key is not None:
        if not 8 <= len(idempotency_key) <= 64:
            raise Problem(400, "invalid-idempotency-key", "Idempotency-Key : entre 8 et 64 caractères")
        with LOCK:
            deja = IDEMPOTENCY.get(idempotency_key)
        if deja is not None:
            ancienne_empreinte, ancien_id = deja
            if ancienne_empreinte != empreinte:
                raise Problem(409, "idempotency-conflict", "cette clé a déjà servi avec un autre corps")
            if ancien_id in SANDBOXES:
                return JSONResponse(public(SANDBOXES[ancien_id]), status_code=202,
                                    headers={"Location": f"/v1/sandboxes/{ancien_id}"})

    with LOCK:
        actives = sum(1 for sb in SANDBOXES.values() if sb["status"] in ("pending", "ready"))
        if actives >= MAX_SANDBOXES:
            raise Problem(429, "quota-exceeded", f"quota atteint : {MAX_SANDBOXES} sandboxes actives",
                          headers={"Retry-After": "10"})
        sandbox_id = new_id()
        sb = {"id": sandbox_id, "image": body.image, "status": "pending", "ttl_seconds": body.ttl_seconds,
              "limits": body.limits.model_dump(), "created_at": now(), "container_id": None}
        SANDBOXES[sandbox_id] = sb
        if idempotency_key is not None:
            IDEMPOTENCY[idempotency_key] = (empreinte, sandbox_id)

    threading.Thread(target=provision, args=(sandbox_id,), daemon=True).start()
    audit(request, "create", sandbox_id, body.image)
    return JSONResponse(public(sb), status_code=202, headers={"Location": f"/v1/sandboxes/{sandbox_id}"})


# ---------- listSandboxes : GET /v1/sandboxes ----------

@app.get("/v1/sandboxes")
def list_sandboxes(
    request: Request,
    status: Literal["pending", "ready", "failed", "terminated"] | None = None,
    page_size: int = Query(20, ge=1, le=100),
    page_token: str | None = None,
):
    operator_only(request)
    items = sorted(SANDBOXES.values(), key=lambda sb: (sb["created_at"], sb["id"]), reverse=True)
    if status:
        items = [sb for sb in items if sb["status"] == status]
    start = 0
    if page_token is not None:
        ids = [sb["id"] for sb in items]
        if page_token not in ids:
            raise Problem(400, "invalid-page-token", "page_token inconnu")
        start = ids.index(page_token) + 1
    page = items[start:start + page_size]
    reste = start + page_size < len(items)
    return {"items": [public(sb) for sb in page], "next_page_token": page[-1]["id"] if reste else None}


# ---------- getSandbox : GET /v1/sandboxes/{id} ----------

@app.get("/v1/sandboxes/{sandbox_id}")
def get_sandbox(request: Request, sandbox_id: str):
    can_use(request, sandbox_id)
    sb = get_or_404(sandbox_id)
    return JSONResponse(public(sb), headers={"ETag": etag(sb)})


# ---------- updateSandbox : PATCH /v1/sandboxes/{id} (bonus ETag / If-Match) ----------

@app.patch("/v1/sandboxes/{sandbox_id}")
async def update_sandbox(request: Request, sandbox_id: str, if_match: str | None = Header(None)):
    operator_only(request)
    sb = get_or_404(sandbox_id)
    body = await read_json(request, SandboxPatch, ("application/merge-patch+json",))
    with LOCK:
        if if_match is not None and if_match != etag(sb):
            raise Problem(412, "precondition-failed", "la sandbox a changé depuis la lecture")
        if sb["status"] == "terminated":
            raise Problem(409, "not-ready", f"{sandbox_id} est terminée")
        sb["ttl_seconds"] = body.ttl_seconds
    audit(request, "update", sandbox_id, f"ttl_seconds={body.ttl_seconds}")
    return JSONResponse(public(sb), headers={"ETag": etag(sb)})


# ---------- deleteSandbox : DELETE /v1/sandboxes/{id} ----------

@app.delete("/v1/sandboxes/{sandbox_id}")
def delete_sandbox(request: Request, sandbox_id: str):
    operator_only(request)
    with LOCK:
        sb = get_or_404(sandbox_id)
        del SANDBOXES[sandbox_id]
    if sb.get("container_id"):
        docker.remove_container(sb["container_id"])
    audit(request, "delete", sandbox_id)
    return Response(status_code=204)


# ---------- createAgentToken : POST /v1/sandboxes/{id}/tokens (bloc D) ----------

@app.post("/v1/sandboxes/{sandbox_id}/tokens")
def create_agent_token(request: Request, sandbox_id: str):
    operator_only(request)
    sb = get_or_404(sandbox_id)
    if sb["status"] == "terminated":
        raise Problem(409, "not-ready", f"{sandbox_id} est terminée")
    token, exp = make_agent_token(sandbox_id)
    audit(request, "token", sandbox_id)
    return JSONResponse({"token": token, "sandbox_id": sandbox_id,
                         "expires_at": iso(datetime.fromtimestamp(exp, timezone.utc))}, status_code=201)


# ---------- execCommand : POST /v1/sandboxes/{id}/exec ----------

@app.post("/v1/sandboxes/{sandbox_id}/exec")
async def exec_command(request: Request, sandbox_id: str):
    can_use(request, sandbox_id)
    sb = get_or_404(sandbox_id)
    body = await read_json(request, ExecRequest, ("application/json",))
    ready_or_409(sb)
    result = docker.exec_command(sb["container_id"], body.cmd, body.timeout_seconds)
    if result["exit_code"] is None:  # tuée par le timeout : le contrat dit 137
        result["exit_code"] = 137
    audit(request, "exec", sandbox_id, " ".join(body.cmd)[:200])
    return result


# ---------- readFile : GET /v1/sandboxes/{id}/files?path=… ----------

@app.get("/v1/sandboxes/{sandbox_id}/files")
def read_file(request: Request, sandbox_id: str, path: str | None = None):
    can_use(request, sandbox_id)
    sb = get_or_404(sandbox_id)
    path = safe_path(path)
    ready_or_409(sb)
    data = read_in_sandbox(sb["container_id"], path)
    audit(request, "read", sandbox_id, path)
    return Response(content=data, media_type="application/octet-stream")


# ---------- writeFile : PUT /v1/sandboxes/{id}/files?path=… ----------

@app.put("/v1/sandboxes/{sandbox_id}/files")
async def write_file(request: Request, sandbox_id: str, path: str | None = None):
    can_use(request, sandbox_id)
    sb = get_or_404(sandbox_id)
    path = safe_path(path)
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/octet-stream":
        raise Problem(415, "unsupported-media-type", "attendu : application/octet-stream")
    data = await request.body()
    if len(data) > MAX_FILE:
        raise Problem(413, "payload-too-large", f"fichier trop volumineux ({MAX_FILE // 1024} Ko maximum)")
    ready_or_409(sb)
    created = write_in_sandbox(sb["container_id"], path, data)
    audit(request, "write", sandbox_id, path)
    return Response(status_code=201 if created else 204)


# ---------- santé et métriques (bloc F) ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if not docker.ping():
        raise Problem(503, "docker-unavailable", "le démon Docker ne répond pas", headers={"Retry-After": "5"})
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    """Format Prometheus : métriques RED (débit, erreurs, durée) et sandboxes_active."""
    lines = ["# HELP http_requests_total Requêtes HTTP reçues.", "# TYPE http_requests_total counter"]
    with METRICS_LOCK:
        for (method, route, code), n in sorted(REQUESTS.items()):
            lines.append(f'http_requests_total{{method="{method}",route="{route}",status="{code}"}} {n}')
        lines += ["# HELP http_request_duration_seconds Durée des requêtes.",
                  "# TYPE http_request_duration_seconds summary"]
        for (method, route), (somme, nombre) in sorted(DURATIONS.items()):
            lines.append(f'http_request_duration_seconds_sum{{method="{method}",route="{route}"}} {somme:.6f}')
            lines.append(f'http_request_duration_seconds_count{{method="{method}",route="{route}"}} {nombre}')
    actives = sum(1 for sb in SANDBOXES.values() if sb["status"] in ("pending", "ready"))
    lines += ["# HELP sandboxes_active Sandboxes en pending ou ready.", "# TYPE sandboxes_active gauge",
              f"sandboxes_active {actives}"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
