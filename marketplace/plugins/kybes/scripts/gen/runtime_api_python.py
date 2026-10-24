"""Moduli comuni delle API generate in Python: validatore JSON Schema, router e middleware, identità, dati, adattatori."""
from __future__ import annotations

from typing import Dict

from naming import header
from sqlonly import strip_sql

HEAD = header("python", "kit") + "# ruff: noqa\n"

SCHEMA = '''"""Validatore del sottoinsieme di JSON Schema (OpenAPI 3.0) usato dal contratto delle API.

Parole chiave: type, nullable, enum, minLength, maxLength, pattern, format (uuid, date, date-time), minimum, maximum,
items, minItems, maxItems, properties, required, additionalProperties. Per ogni campo si riporta la prima regola
violata, con lo stesso testo in tutti i linguaggi: il client riceve {campo: regola}, mai valori.
"""
from __future__ import annotations

import math
import re
from datetime import date
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DATE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
DATE_TIME = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))$")
INTEGER = re.compile(r"^-?[0-9]+$")
NUMBER = re.compile(r"^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$")


def num(x: Any) -> str:
    """Numero nel testo di una regola: gli interi senza decimali."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _valid_date(y: str, m: str, d: str) -> bool:
    try:
        date(int(y), int(m), int(d))
        return True
    except ValueError:
        return False


def check_format(fmt: str, s: str) -> bool:
    if fmt == "uuid":
        return bool(UUID.fullmatch(s))
    if fmt == "date":
        mt = DATE.fullmatch(s)
        return bool(mt) and _valid_date(*mt.groups())
    mt = DATE_TIME.fullmatch(s)
    if not mt or not _valid_date(mt.group(1), mt.group(2), mt.group(3)):
        return False
    if int(mt.group(4)) > 23 or int(mt.group(5)) > 59 or int(mt.group(6)) > 59:
        return False
    return mt.group(8) == "Z" or (int(mt.group(9)) <= 23 and int(mt.group(10)) <= 59)


@lru_cache(maxsize=256)
def js_pattern(pattern: str) -> "re.Pattern[str]":
    """pattern del contratto con la semantica di JavaScript: $ chiude il testo (non accetta un a capo finale)."""
    return re.compile(re.sub(r"(?<!\\\\)\\$(?=$|\\)|\\|)", r"\\\\Z", pattern))


def type_of(v: Any) -> str:
    """Tipo JSON di un valore non nullo (il nullo lo gestisce validate)."""
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() else "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object" if isinstance(v, dict) else "unknown"


def _has_type(want: str, got: str) -> bool:
    return got == want or (want == "number" and got == "integer")


def validate(schema: Dict[str, Any], value: Any, path: str, errors: Dict[str, str]) -> None:
    """Aggiunge a errors {percorso: regola} le violazioni di value; un solo errore per percorso."""
    where = path or "body"
    if where in errors:
        return
    if value is None:
        if not schema.get("nullable", False) and "type" in schema:
            errors[where] = "nullo non ammesso"
        return
    t = type_of(value)
    want = schema.get("type")
    if want and not _has_type(want, t):
        errors[where] = f"tipo atteso: {want}"
        return
    if "enum" in schema and value not in schema["enum"]:
        errors[where] = "valore non ammesso"
        return
    if t == "string":
        n = len(value)
        if "minLength" in schema and n < schema["minLength"]:
            errors[where] = f"lunghezza minima {schema['minLength']}"
        elif "maxLength" in schema and n > schema["maxLength"]:
            errors[where] = f"lunghezza massima {schema['maxLength']}"
        elif "pattern" in schema and not js_pattern(schema["pattern"]).search(value):
            errors[where] = "formato non valido"
        elif "format" in schema and not check_format(schema["format"], value):
            errors[where] = f"formato {schema['format']}"
    elif t in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors[where] = f"valore minimo {num(schema['minimum'])}"
        elif "maximum" in schema and value > schema["maximum"]:
            errors[where] = f"valore massimo {num(schema['maximum'])}"
    elif t == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors[where] = f"almeno {schema['minItems']} elementi"
        elif "maxItems" in schema and len(value) > schema["maxItems"]:
            errors[where] = f"al massimo {schema['maxItems']} elementi"
        elif "items" in schema:
            for i, item in enumerate(value):
                validate(schema["items"], item, f"{path}[{i}]", errors)
    elif t == "object":
        props = schema.get("properties", {})
        prefix = f"{path}." if path else ""
        for name in schema.get("required", []):
            if name not in value:
                errors.setdefault(prefix + name, "obbligatorio")
        for name, sub in props.items():
            if name in value:
                validate(sub, value[name], prefix + name, errors)
        extra = schema.get("additionalProperties", True)
        for name in value:
            if name not in props:
                if extra is False:
                    errors.setdefault(prefix + name, "non ammesso")
                elif isinstance(extra, dict):
                    validate(extra, value[name], prefix + name, errors)


def coerce(schema: Dict[str, Any], raw: List[str]) -> Tuple[Any, Optional[str]]:
    """Valore di un parametro di path o query (testo) nel tipo dello schema; (valore, regola violata o None)."""
    if schema.get("type") == "array":
        out = []
        for r in raw:
            v, err = coerce(schema.get("items", {}), [r])
            if err:
                return None, err
            out.append(v)
        return out, None
    if len(raw) != 1:
        return None, "un solo valore"
    r, want = raw[0], schema.get("type")
    if want == "integer":
        return (int(r), None) if INTEGER.fullmatch(r) else (None, "tipo atteso: integer")
    if want == "number":
        x = float(r) if NUMBER.fullmatch(r) else math.inf
        return (x, None) if math.isfinite(x) else (None, "tipo atteso: number")
    if want == "boolean":
        return (r == "true", None) if r in ("true", "false") else (None, "tipo atteso: boolean")
    return r, None
'''

HTTP = '''"""Richieste, risposte ed errori delle API generate: indipendenti dal framework e dal runtime (Lambda, ASGI, FastAPI)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

# errore -> stato HTTP e messaggio pubblico (il dettaglio resta nei log, legato al correlationId)
STATUS = {"VALIDATION": 400, "AUTH": 401, "FORBIDDEN": 403, "NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405,
          "CONFLICT": 409, "UNSUPPORTED_MEDIA_TYPE": 415, "UNPROCESSABLE": 422, "INTERNAL": 500, "TRANSIENT": 503}
MESSAGE = {"VALIDATION": "Richiesta non valida", "AUTH": "Autenticazione richiesta", "FORBIDDEN": "Operazione non consentita",
           "NOT_FOUND": "Risorsa non trovata", "METHOD_NOT_ALLOWED": "Metodo non ammesso",
           "CONFLICT": "Conflitto con lo stato attuale", "UNSUPPORTED_MEDIA_TYPE": "Serve un corpo application/json",
           "UNPROCESSABLE": "Dati non accettati dal modello", "INTERNAL": "Errore interno",
           "TRANSIENT": "Servizio temporaneamente non disponibile"}


@dataclass(frozen=True)
class Identity:
    """Chi chiama: claim già verificati dal gateway (mai il token grezzo)."""
    subject: Optional[str] = None
    tenant: Optional[str] = None
    scopes: FrozenSet[str] = frozenset()
    claims: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApiRequest:
    method: str
    path: str
    query: Dict[str, List[str]] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)      # nomi in minuscolo
    body: Optional[bytes] = None
    identity: Optional[Identity] = None


@dataclass
class ApiResponse:
    status: int
    body: Any = None                                          # JSON serializzabile, None per 204
    headers: Dict[str, str] = field(default_factory=dict)


class ApiError(Exception):
    """Errore applicativo con esito HTTP: kind è una chiave di STATUS, fields {campo: regola} solo per VALIDATION."""

    def __init__(self, kind: str, code: str, fields: Optional[Dict[str, str]] = None, detail: str = "") -> None:
        super().__init__(detail or code)
        self.kind, self.code, self.fields = kind, code, dict(fields or {})


@dataclass
class Call:
    """Input già validato di un'operazione, passato al controller generato o al metodo del service."""
    operation: str
    path: Dict[str, Any]
    query: Dict[str, Any]
    body: Any
    identity: Identity
    correlation_id: str
    base_path: str = ""  # prefisso dei percorsi dell'Api (per Location e collegamenti)

    @property
    def tenant(self) -> Optional[str]:
        return self.identity.tenant


def error_body(kind: str, code: str, cid: str, fields: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": MESSAGE[kind], "correlationId": cid}
    if fields:
        err["fields"] = fields
    return {"error": err}
'''

IDENTITY = '''"""Identità dai claim già verificati dal gateway: requestContext.authorizer (Lambda) o header impostati dal gateway.

Il servizio non verifica il token: deve essere raggiungibile solo dal gateway (rete privata, VPC link), che
sovrascrive gli header di identità a ogni richiesta.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional

from ._http import Identity

CLAIMS = __CLAIMS__
HEADERS = __HEADERS__


def scopes_of(value: Any) -> Iterable[str]:
    """Scope da un claim: lista, "a b", "a,b" o "[a b]" (forma degli array nei claim di API Gateway HTTP API)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [s for s in text.replace(",", " ").split() if s]


def from_claims(claims: Mapping[str, Any]) -> Identity:
    scopes = {s for name in CLAIMS["scopes"] for s in scopes_of(claims.get(name))}
    sub, ten = claims.get(CLAIMS["subject"]), claims.get(CLAIMS["tenant"])
    return Identity(subject=str(sub) if sub not in (None, "") else None, tenant=str(ten) if ten not in (None, "") else None,
                    scopes=frozenset(scopes), claims=dict(claims))


def from_lambda(event: Mapping[str, Any]) -> Optional[Identity]:
    """API Gateway: HTTP API (authorizer.jwt.claims o authorizer.lambda) o REST API (authorizer.claims o contesto)."""
    auth = (event.get("requestContext") or {}).get("authorizer")
    if not isinstance(auth, dict):
        return None
    claims = (auth.get("jwt") or {}).get("claims") or auth.get("lambda") or auth.get("claims") or auth
    if isinstance(claims, str):  # REST API con authorizer Lambda: il contesto può contenere i claim come JSON
        claims = json.loads(claims)
    return from_claims(claims)


def from_headers(headers: Mapping[str, str]) -> Optional[Identity]:
    """Kubernetes dietro il gateway: claim copiati negli header dal parameter mapping del gateway."""
    if HEADERS["subject"] not in headers:
        return None
    claims: Dict[str, Any] = {CLAIMS["subject"]: headers[HEADERS["subject"]]}
    if HEADERS["tenant"] in headers:
        claims[CLAIMS["tenant"]] = headers[HEADERS["tenant"]]
    if HEADERS["scopes"] in headers:
        claims[CLAIMS["scopes"][0]] = headers[HEADERS["scopes"]]
    return from_claims(claims)
'''

ROUTER = '''"""Router e middleware delle API: correlationId, percorso e metodo, identità e scope, validazione, errori.

Ordine per ogni richiesta (uguale in tutti i linguaggi):
  1. correlationId dall'header x-correlation-id (se valido) o nuovo;
  2. operazione dal percorso (i segmenti fissi vincono sui parametri) e dal metodo: 404 o 405;
  3. identità obbligatoria per le operazioni protette (401) e scope richiesti (403);
  4. parametri di path e query: tipi, regole, parametri sconosciuti (400);
  5. corpo: application/json (415), JSON valido e conforme allo schema (400);
  6. controller o metodo del service; errori del modello e del database -> 404, 409, 422, 503; il resto -> 500.
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import unquote

from ._http import ApiError, ApiRequest, ApiResponse, Call, Identity, STATUS, error_body
from ._schema import coerce, validate
from model.generated import ModelValidationError, TenantError
# kybes:sql-begin
from sqlalchemy.exc import IntegrityError
from model.generated._uow import is_retryable
# kybes:sql-end

log = logging.getLogger("api")
CID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PAGING_FIELDS = {"limit", "sort", "cursor"}
Handler = Callable[[Call], Any]


def map_error(exc: BaseException) -> ApiError:
    """Errore del modello, del database o inatteso -> errore dell'API."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, ModelValidationError):
        fields = dict(exc.fields)
        if fields and set(fields) <= PAGING_FIELDS:
            return ApiError("VALIDATION", "INVALID_PAGE", fields)
        if fields and all(v == "record collegati" for v in fields.values()):
            return ApiError("CONFLICT", "RELATED_RECORDS", fields)
        return ApiError("UNPROCESSABLE", "MODEL_RULE", fields)
    if isinstance(exc, TenantError):
        return ApiError("FORBIDDEN", "TENANT_REQUIRED")
    if type(exc).__name__ == "DuplicateKeyError":  # MongoDB: chiave univoca già usata
        return ApiError("CONFLICT", "DUPLICATE")
    # kybes:sql-begin
    if isinstance(exc, IntegrityError):  # vincolo univoco o di chiave esterna del database
        return ApiError("CONFLICT", "CONSTRAINT")
    if is_retryable(exc):
        return ApiError("TRANSIENT", "RETRY_LATER")
    # kybes:sql-end
    return ApiError("INTERNAL", "UNEXPECTED")


def _finite(text: str) -> float:
    """Numero JSON con decimali o esponente: fuori dall'intervallo di un double (1e400) il JSON non è valido."""
    x = float(text)
    if math.isinf(x):
        raise ValueError("numero fuori intervallo")
    return x


def _no_constant(name: str) -> Any:
    raise ValueError(name)  # NaN e Infinity non sono JSON


class Route:
    def __init__(self, spec: Dict[str, Any], handler: Handler) -> None:
        self.spec = spec
        self.handler = handler
        self.segments = [s for s in spec["path"].split("/") if s]

    def match(self, parts: List[str]) -> Optional[Dict[str, str]]:
        if len(parts) != len(self.segments):
            return None
        out: Dict[str, str] = {}
        for seg, part in zip(self.segments, parts):
            if seg.startswith("{"):
                out[seg[1:-1]] = part
            elif seg != part:
                return None
        return out

    @property
    def rank(self) -> tuple:
        """I segmenti fissi vincono sui parametri, da sinistra a destra."""
        return tuple(1 if s.startswith("{") else 0 for s in self.segments)


class Api:
    """Le operazioni del contratto con i loro handler: handle(ApiRequest) -> ApiResponse."""

    def __init__(self, specs: Iterable[Dict[str, Any]], handlers: Dict[str, Handler], base_path: str = "") -> None:
        self.routes = sorted((Route(s, handlers[s["id"]]) for s in specs), key=lambda r: r.rank)
        self.base_path = base_path.rstrip("/")

    def handle(self, req: ApiRequest) -> ApiResponse:
        given = req.headers.get("x-correlation-id", "")
        cid = given if CID.match(given) else str(uuid.uuid4())
        try:
            resp = self._dispatch(req, cid)
        except BaseException as exc:  # noqa: BLE001 - ogni errore diventa una risposta sicura
            err = map_error(exc)
            if err.kind == "INTERNAL":
                log.error("api: errore inatteso", extra={"correlationId": cid}, exc_info=exc)
            else:
                log.info("api: %s %s", err.kind, err.code, extra={"correlationId": cid})
            headers = {"content-type": "application/json"}
            if err.kind == "METHOD_NOT_ALLOWED":
                headers["allow"] = err.fields.pop("allow")
            shown = err.fields if err.kind in ("VALIDATION", "CONFLICT", "UNPROCESSABLE") else None
            resp = ApiResponse(STATUS[err.kind], error_body(err.kind, err.code, cid, shown), headers)
        resp.headers["x-correlation-id"] = cid
        return resp

    def _find(self, req: ApiRequest) -> tuple:
        path = req.path
        if self.base_path and (path == self.base_path or path.startswith(self.base_path + "/")):
            path = path[len(self.base_path):]
        parts = [unquote(p) for p in path.split("/") if p]
        allowed = []
        for r in self.routes:
            params = r.match(parts)
            if params is None:
                continue
            if r.spec["method"] == req.method.upper():
                return r, params
            allowed.append(r.spec["method"])
        if allowed:
            raise ApiError("METHOD_NOT_ALLOWED", "METHOD_NOT_ALLOWED", {"allow": ", ".join(sorted(set(allowed)))})
        raise ApiError("NOT_FOUND", "ROUTE_NOT_FOUND")

    def _dispatch(self, req: ApiRequest, cid: str) -> ApiResponse:
        route, raw_path = self._find(req)
        spec = route.spec
        identity = req.identity or Identity()
        if spec["secured"] and not identity.subject:
            raise ApiError("AUTH", "IDENTITY_REQUIRED")
        if not set(spec["scopes"]) <= identity.scopes:
            raise ApiError("FORBIDDEN", "SCOPE_REQUIRED")
        if spec.get("roles") and not (set(spec["roles"]) & identity.scopes):
            raise ApiError("FORBIDDEN", "ROLE_REQUIRED")
        errors: Dict[str, str] = {}
        path_vals: Dict[str, Any] = {}
        query_vals: Dict[str, Any] = {}
        known = {p["name"] for p in spec["params"] if p["in"] == "query"}
        for name in req.query:
            if name not in known:
                errors[name] = "parametro sconosciuto"
        for p in spec["params"]:
            raw = [raw_path[p["name"]]] if p["in"] == "path" else req.query.get(p["name"])
            if raw is None:
                if p["required"]:
                    errors.setdefault(p["name"], "obbligatorio")
                continue
            value, err = coerce(p["schema"], raw)
            if err:
                errors.setdefault(p["name"], err)
                continue
            validate(p["schema"], value, p["name"], errors)
            (path_vals if p["in"] == "path" else query_vals)[p["name"]] = value
        body = None
        has_body = bool(req.body)
        if spec["body"] is None:
            if has_body:
                errors.setdefault("body", "corpo non ammesso")
        elif has_body:
            ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise ApiError("UNSUPPORTED_MEDIA_TYPE", "JSON_REQUIRED")
            try:
                body = json.loads(req.body.decode("utf-8"), parse_constant=_no_constant, parse_float=_finite)
            except (ValueError, UnicodeDecodeError):
                errors.setdefault("body", "JSON non valido")
            else:
                validate(spec["body"], body, "", errors)
        elif spec["bodyRequired"]:
            errors.setdefault("body", "obbligatorio")
        if errors:
            raise ApiError("VALIDATION", "INVALID_REQUEST", errors)
        result = route.handler(Call(spec["id"], path_vals, query_vals, body, identity, cid, self.base_path))
        if isinstance(result, ApiResponse):
            headers = dict(result.headers)
            if result.body is not None:
                headers.setdefault("content-type", "application/json")
            return ApiResponse(result.status, result.body, headers)
        if spec["status"] == 204:
            return ApiResponse(204)
        return ApiResponse(spec["status"], result, {"content-type": "application/json"})
'''

DATA = '''"""Accesso ai dati per i controller generati: sessioni in lettura e Unit of Work in scrittura, con il tenant legato."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Optional, TypeVar

T = TypeVar("T")


class ApiData:
    """Sorgenti dei dati delle API.

    sql: session_factory di SQLAlchemy (sessionmaker), oppure sql_for(tenant) -> session_factory per le tabelle con
    tenancy schema o database. mongo: client pymongo e nome del database, oppure mongo_database_for(tenant) -> nome.
    """

    def __init__(self, session_factory: Any = None, sql_for: Optional[Callable[[Any], Any]] = None,
                 mongo_client: Any = None, mongo_database: Optional[str] = None,
                 mongo_database_for: Optional[Callable[[Any], str]] = None, levels: Any = None) -> None:
        self.session_factory, self.sql_for = session_factory, sql_for
        self.mongo_client, self.mongo_database, self.mongo_database_for = mongo_client, mongo_database, mongo_database_for
        self.levels = levels

    # kybes:sql-begin
    def _sql(self, tenant: Any) -> Any:
        factory = self.sql_for(tenant) if self.sql_for else self.session_factory
        if factory is None:
            raise RuntimeError("ApiData: serve session_factory (o sql_for) per le tabelle SQL")
        return factory

    @contextmanager
    def read(self, tenant: Any) -> Iterator[Any]:
        from model.generated import bind_tenant
        with self._sql(tenant)() as s:
            if tenant is not None:
                bind_tenant(s, tenant)
            yield s

    def write(self, tables: Iterable[str], tenant: Any, work: Callable[[Any], T]) -> T:
        from model.generated import run_in_transaction
        return run_in_transaction(self._sql(tenant), work, tables=list(tables), tenant=tenant, levels=self.levels)
    # kybes:sql-end

    # kybes:mongo-begin
    def _mongo(self, tenant: Any) -> str:
        if self.mongo_client is None:
            raise RuntimeError("ApiData: serve mongo_client per le collection MongoDB")
        return self.mongo_database_for(tenant) if self.mongo_database_for else self.mongo_database

    @contextmanager
    def mongo_read(self, tenant: Any) -> Iterator[Any]:
        from model.generated import mongo_session
        yield mongo_session(self.mongo_client, self._mongo(tenant), tenant)

    def mongo_write(self, tenant: Any, work: Callable[[Any], T]) -> T:
        from model.generated import run_in_mongo_transaction
        return run_in_mongo_transaction(self.mongo_client, self._mongo(tenant), work, tenant=tenant)
    # kybes:mongo-end

    # kybes:neo4j-begin
    @contextmanager
    def neo4j_read(self, tenant: Any) -> Iterator[Any]:
        from model.generated import neo4j_session
        yield neo4j_session(self.neo4j_driver, tenant)

    def neo4j_write(self, tenant: Any, work: Callable[[Any], T]) -> T:
        from model.generated import run_in_neo4j_transaction
        return run_in_neo4j_transaction(self.neo4j_driver, work, tenant=tenant)
    # kybes:neo4j-end
'''

LAMBDA = '''"""Adattatore AWS Lambda (API Gateway HTTP API v2 e REST API v1): evento -> ApiRequest -> risposta proxy."""
from __future__ import annotations

import base64
import json
from typing import Any, Callable, Dict, List, Mapping
from urllib.parse import parse_qs

from ._http import ApiRequest, ApiResponse
from ._identity import from_lambda
from ._router import Api


def to_request(event: Mapping[str, Any]) -> ApiRequest:
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    body = event.get("body")
    raw = None
    if body is not None:
        raw = base64.b64decode(body) if event.get("isBase64Encoded") else str(body).encode("utf-8")
    if event.get("version") == "2.0":
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath") or "/"
        query: Dict[str, List[str]] = parse_qs(event.get("rawQueryString") or "", keep_blank_values=True)
    else:
        method, path = event["httpMethod"], event.get("path") or "/"
        multi = event.get("multiValueQueryStringParameters")
        single = event.get("queryStringParameters") or {}
        query = {k: list(v) for k, v in multi.items()} if multi else {k: [v] for k, v in single.items()}
    return ApiRequest(method=method, path=path, query=query, headers=headers, body=raw, identity=from_lambda(event))


def to_proxy(resp: ApiResponse) -> Dict[str, Any]:
    out: Dict[str, Any] = {"statusCode": resp.status, "headers": dict(resp.headers), "isBase64Encoded": False}
    out["body"] = "" if resp.body is None else json.dumps(resp.body, ensure_ascii=False)
    return out


def lambda_handler(api: Api) -> Callable[[Mapping[str, Any], Any], Dict[str, Any]]:
    """handler = lambda_handler(build_api(...)): il punto d'ingresso della function."""
    def handler(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
        return to_proxy(api.handle(to_request(event)))
    return handler
'''

ASGI = '''"""Adattatore ASGI senza framework (uvicorn, hypercorn) per i microservizi su Kubernetes dietro il gateway."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List
from urllib.parse import parse_qs, quote

from ._http import ApiRequest, ApiResponse
from ._identity import from_headers
from ._router import Api

Receive = Callable[[], Awaitable[Dict[str, Any]]]
Send = Callable[[Dict[str, Any]], Awaitable[None]]


async def read_body(receive: Receive) -> bytes:
    chunks: List[bytes] = []
    while True:
        msg = await receive()
        chunks.append(msg.get("body", b""))
        if not msg.get("more_body"):
            return b"".join(chunks)


def raw_path(scope: Dict[str, Any]) -> str:
    """Percorso ancora codificato (lo decodifica il router, una volta sola); senza raw_path lo si ricodifica."""
    raw = scope.get("raw_path")
    return raw.decode("latin-1") if raw else quote(scope["path"])


def request_of(scope: Dict[str, Any], body: bytes) -> ApiRequest:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    headers = {k: v for k, v in headers.items() if not k.startswith("x-kybes-")}
    query = parse_qs(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
    return ApiRequest(method=scope["method"], path=raw_path(scope), query=query, headers=headers, body=body or None,
                      identity=from_headers(headers))


async def send_response(send: Send, resp: ApiResponse) -> None:
    body = b"" if resp.body is None else json.dumps(resp.body, ensure_ascii=False).encode("utf-8")
    headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in resp.headers.items()]
    await send({"type": "http.response.start", "status": resp.status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def asgi_app(api: Api) -> Callable[[Dict[str, Any], Receive, Send], Awaitable[None]]:
    """app = asgi_app(build_api(...)); uvicorn modulo:app. Il lavoro sincrono gira in un thread."""
    async def app(scope: Dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        body = await read_body(receive)
        resp = await asyncio.to_thread(api.handle, request_of(scope, body))
        await send_response(send, resp)
    return app
'''

FASTAPI = '''"""Adattatore FastAPI: ogni operazione del contratto diventa una route; validazione, errori e identità restano del nucleo."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import Request  # extra "api": pip install db-models[api]
from fastapi.responses import Response

from ._http import ApiRequest, ApiResponse
from ._identity import from_headers
from ._router import Api
from .asgi_adapter import raw_path

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def include_api(app: Any, api: Api) -> Any:
    """Registra le operazioni sull'app FastAPI (con i loro operationId) e una route finale per 404 e 405 uniformi."""
    async def endpoint(request: Request) -> Response:
        headers = {k.lower(): v for k, v in request.headers.items() if not k.lower().startswith("x-kybes-")}
        query = {k: request.query_params.getlist(k) for k in request.query_params.keys()}
        body = await request.body()
        req = ApiRequest(method=request.method, path=raw_path(request.scope), query=query, headers=headers, body=body or None,
                         identity=from_headers(headers))
        resp: ApiResponse = await asyncio.to_thread(api.handle, req)
        content = b"" if resp.body is None else json.dumps(resp.body, ensure_ascii=False).encode("utf-8")
        return Response(content=content, status_code=resp.status, headers=resp.headers)

    for r in api.routes:
        app.add_api_route(api.base_path + r.spec["path"], endpoint, methods=[r.spec["method"]], operation_id=r.spec["id"],
                          include_in_schema=False)
    app.add_api_route("/{kybes_rest:path}", endpoint, methods=METHODS, include_in_schema=False)
    return app
'''


def files(sql: bool, mongo: bool, claims: Dict, headers: Dict, neo4j: bool = False) -> Dict[str, str]:
    data = strip_sql(DATA, sql)
    data = _strip_block(data, "mongo", mongo)
    data = _strip_block(data, "neo4j", neo4j)
    return {
        "_schema.py": HEAD + SCHEMA,
        "_http.py": HEAD + HTTP,
        "_identity.py": HEAD + IDENTITY.replace("__CLAIMS__", repr(claims)).replace("__HEADERS__", repr(headers)),
        "_router.py": HEAD + strip_sql(ROUTER, sql),
        "_data.py": HEAD + data,
        "lambda_adapter.py": HEAD + LAMBDA,
        "asgi_adapter.py": HEAD + ASGI,
        "fastapi_adapter.py": HEAD + FASTAPI,
    }


def _strip_block(text: str, tag: str, keep: bool) -> str:
    out, skip = [], False
    for line in text.split("\n"):
        if f"kybes:{tag}-begin" in line:
            skip = not keep
            continue
        if f"kybes:{tag}-end" in line:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)
