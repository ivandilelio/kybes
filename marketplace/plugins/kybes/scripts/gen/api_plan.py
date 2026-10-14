"""Piano neutro delle API REST: operazioni, schemi di validazione e contratto OpenAPI completo.

Fonti:
  - il blocco api degli schemi delle tabelle -> operazioni CRUD, query dichiarate, relazioni (generate);
  - schemas/openapi.yaml del progetto -> endpoint custom (operationId), componenti, sicurezza.

Il risultato serve a tutti gli emettitori: ogni linguaggio riceve la stessa lista di Operation con gli schemi già
risolti (niente $ref) e ristretti al sottoinsieme di JSON Schema che il validatore generato interpreta.

Convenzioni del contratto (uguali in tutti i linguaggi):
  uuid stringa, bigint e decimal stringhe (nessuna perdita di precisione in JavaScript), date "AAAA-MM-GG",
  datetime ISO 8601 con fuso, json valore libero, colonne vuote come null; il tenant non compare mai.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from schema import Table, camel, kebab, tenant_column

# parole chiave di JSON Schema (dialetto OpenAPI 3.0) che il validatore generato applica
VALIDATED = {"type", "nullable", "properties", "required", "additionalProperties", "enum", "minLength", "maxLength",
             "pattern", "minimum", "maximum", "format", "items", "minItems", "maxItems"}
# documentali: ammesse e ignorate dal validatore
DOC_ONLY = {"description", "title", "example", "examples", "default", "readOnly", "writeOnly", "deprecated", "externalDocs", "xml"}
TYPES = ("string", "integer", "number", "boolean", "object", "array")
FORMATS = {"uuid", "date", "date-time"}
FORMATS_DOC = {"int32", "int64", "float", "double"}
METHODS = ("get", "post", "put", "patch", "delete")
OP_ID = re.compile(r"^[a-z][A-Za-z0-9]*$")
INT32 = (-2147483648, 2147483647)
SCALAR_PARAM = ("string", "integer", "number", "boolean")


@dataclass
class Param:
    name: str                       # nome nel contratto (camelCase per le colonne)
    loc: str                        # path | query
    schema: Dict[str, Any]
    required: bool
    column: Optional[str] = None    # colonna del modello, per CRUD e query dichiarate


@dataclass
class Operation:
    op_id: str
    method: str                     # get | post | put | patch | delete
    path: str                       # /segnalazioni/{id}
    context: str
    kind: str                       # list | get | create | update | delete | query | rel | custom
    table: Optional[str] = None
    arg: Optional[str] = None       # nome della query o della relazione
    params: List[Param] = field(default_factory=list)
    body: Optional[Dict[str, Any]] = None
    body_required: bool = False
    scopes: List[str] = field(default_factory=list)
    secured: bool = True            # serve un'identità (claim verificati dal gateway)
    status: int = 200
    summary: str = ""

    @property
    def segments(self) -> List[str]:
        return [s for s in self.path.split("/") if s]


class ContractError(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# ------------------------------------------------------------------ schemi delle colonne e delle tabelle

def prop(name: str) -> str:
    """Nome di una colonna nel JSON delle API (camelCase, come in TypeScript)."""
    return camel(name)


def col_schema(c) -> Dict[str, Any]:
    if c.type == "uuid":
        return {"type": "string", "format": "uuid"}
    if c.type == "string":
        return {"type": "string", "maxLength": c.length}
    if c.type == "text":
        return {"type": "string"}
    if c.type == "int":
        return {"type": "integer", "format": "int32", "minimum": INT32[0], "maximum": INT32[1]}
    if c.type == "bigint":
        return {"type": "string", "pattern": "^-?[0-9]{1,18}$", "description": "intero a 64 bit come stringa"}
    if c.type == "decimal":
        whole = max(c.precision - c.scale, 1)
        frac = f"(\\.[0-9]{{1,{c.scale}}})?" if c.scale else ""
        return {"type": "string", "pattern": f"^-?[0-9]{{1,{whole}}}{frac}$",
                "description": f"decimale ({c.precision},{c.scale}) come stringa"}
    if c.type == "bool":
        return {"type": "boolean"}
    if c.type == "date":
        return {"type": "string", "format": "date"}
    if c.type == "datetime":
        return {"type": "string", "format": "date-time"}
    return {}  # json: qualsiasi valore JSON


def _nullable(s: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(s)
    if out:
        out["nullable"] = True
    return out


def exposed_columns(t: Table) -> list:
    return [c for c in t.columns if not c.tenant]


def writable_columns(t: Table) -> list:
    """Colonne che il client può inviare: niente tenant, chiave generata, date generate."""
    return [c for c in exposed_columns(t) if not (c.primary_key and c.auto) and not c.generated]


def entity_schema(t: Table) -> Dict[str, Any]:
    props, req = {}, []
    for c in exposed_columns(t):
        s = col_schema(c)
        s = _nullable(s) if c.nullable else s
        if c.description:
            s = {**s, "description": c.description}
        if (c.primary_key and c.auto) or c.generated:
            s = {**s, "readOnly": True}
        props[prop(c.name)] = s
        if not c.nullable:
            req.append(prop(c.name))
    return {"type": "object", "description": t.description or f"Record di {t.name}", "properties": props,
            **({"required": req} if req else {}), "additionalProperties": False}


def create_schema(t: Table) -> Dict[str, Any]:
    props, req = {}, []
    for c in writable_columns(t):
        s = col_schema(c)
        props[prop(c.name)] = _nullable(s) if c.nullable else s
        if c.required and c.default is None:
            req.append(prop(c.name))
    return {"type": "object", "properties": props, **({"required": req} if req else {}), "additionalProperties": False}


def update_schema(t: Table) -> Dict[str, Any]:
    props = {}
    for c in writable_columns(t):
        if c.primary_key:
            continue
        s = col_schema(c)
        props[prop(c.name)] = _nullable(s) if c.nullable else s
    return {"type": "object", "properties": props, "additionalProperties": False}


def page_schema(item: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "required": ["items", "nextCursor", "limit"], "additionalProperties": False,
            "properties": {"items": {"type": "array", "items": item},
                           "nextCursor": {"type": "string", "nullable": True,
                                          "description": "cursore opaco della pagina successiva; null all'ultima pagina"},
                           "limit": {"type": "integer"}}}


def page_params(t: Table, sortable: bool) -> List[Param]:
    out = [Param("limit", "query", {"type": "integer", "minimum": 1, "maximum": t.pagination.max_limit}, False),
           Param("cursor", "query", {"type": "string", "maxLength": 4096}, False)]
    if sortable:
        out.append(Param("sort", "query", {"type": "string", "maxLength": 512}, False))
    return out


# ------------------------------------------------------------------ operazioni generate dagli schemi

def _ops_of(t: Table, tables: Dict[str, Table], security: bool) -> List[Operation]:
    a = t.api
    base = "/" + a.path
    T = t.name
    pk = t.pk
    idp = Param("id", "path", col_schema(pk), True, pk.name)
    item = f"/{{id}}"
    ops: List[Operation] = []

    def add(**kw):
        kind = kw["kind"]
        write = kind in ("create", "update", "delete")
        ops.append(Operation(context=a.context, table=T, scopes=list(a.write_scopes if write else a.read_scopes),
                             secured=security, **kw))
    if "list" in a.operations:
        add(op_id=f"list{T}", method="get", path=base, kind="list", params=page_params(t, True),
            summary=f"pagina di {T} con cursore e ordinamento")
    if "get" in a.operations:
        add(op_id=f"get{T}", method="get", path=base + item, kind="get", params=[idp], summary=f"un record di {T} per chiave")
    if "create" in a.operations:
        add(op_id=f"create{T}", method="post", path=base, kind="create", body=create_schema(t), body_required=True,
            status=201, summary=f"crea un record di {T}")
    if "update" in a.operations:
        add(op_id=f"update{T}", method="patch", path=base + item, kind="update", params=[idp], body=update_schema(t),
            body_required=True, summary=f"modifica i campi indicati di un record di {T}")
    if "delete" in a.operations:
        add(op_id=f"delete{T}", method="delete", path=base + item, kind="delete", params=[idp], status=204,
            summary=f"elimina un record di {T}")
    for qn in a.queries:
        q = next(x for x in t.queries if x.name == qn)
        params: List[Param] = []
        for c in q.where:
            if not c.param:
                continue
            col = t.col(c.column)
            s = col_schema(col)
            if c.op == "in":
                s = {"type": "array", "items": s, "minItems": 0}
            elif c.op == "prefix":
                s = {"type": "string", "minLength": 1, **({"maxLength": col.length} if col.length else {})}
            params.append(Param(camel(c.param), "query", s, True, col.name))
        if q.returns == "page":
            params += page_params(t, False)
        add(op_id=f"{camel(T)}{q.name}", method="get", path=f"{base}/query/{kebab(q.name)}", kind="query", arg=q.name,
            params=params, summary=f"query {q.name} ({q.returns})")
    for rn in a.relations:
        r = next(x for x in t.relations if x.name == rn)
        params = [idp] + (page_params(tables[r.target], False) if r.kind == "one_to_many" else [])
        add(op_id=f"{camel(T)}{r.name}", method="get", path=f"{base}{item}/{kebab(r.name)}", kind="rel", arg=r.name,
            params=params, summary=f"{r.target} collegati a un record di {T}" if r.kind == "one_to_many"
            else f"{r.target} collegato a un record di {T}")
    return ops


# ------------------------------------------------------------------ contratto del progetto (endpoint custom)

def _resolve(node: Any, comps: Dict[str, Any], where: str, errs: List[str], seen: Tuple[str, ...] = ()) -> Any:
    """Schema con i $ref verso #/components/schemas sostituiti dal contenuto; rifiuta i riferimenti circolari."""
    if isinstance(node, list):
        return [_resolve(x, comps, where, errs, seen) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
            errs.append(f"{where}: $ref ammessi solo verso #/components/schemas/ ({ref!r})")
            return {}
        name = ref.rsplit("/", 1)[1]
        if name in seen:
            errs.append(f"{where}: riferimento circolare a {name}: il validatore non supporta schemi ricorsivi")
            return {}
        if name not in comps:
            errs.append(f"{where}: {ref} non esiste")
            return {}
        return _resolve(comps[name], comps, f"{where} -> {name}", errs, seen + (name,))
    out: Dict[str, Any] = {}
    for k, v in node.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _resolve(pv, comps, f"{where}.{pk}", errs, seen) for pk, pv in v.items()}
        elif k in ("items", "additionalProperties") and isinstance(v, dict):
            out[k] = _resolve(v, comps, where, errs, seen)
        else:
            out[k] = v
    return out


def check_schema(s: Any, where: str, errs: List[str]) -> Dict[str, Any]:
    """Controlla che uno schema (già risolto) usi solo ciò che il validatore applica; restituisce la forma canonica."""
    if not isinstance(s, dict):
        errs.append(f"{where}: lo schema deve essere una mappa")
        return {}
    out: Dict[str, Any] = {}
    for k, v in s.items():
        if k in DOC_ONLY:
            continue
        if k not in VALIDATED:
            errs.append(f"{where}: '{k}' non è supportato dal validatore generato (ammessi: {', '.join(sorted(VALIDATED))})")
            continue
        if k == "type":
            if v not in TYPES:
                errs.append(f"{where}: type ammette {', '.join(TYPES)} (OpenAPI 3.0: per il nullo usa nullable: true)")
                continue
        elif k == "format":
            if v in FORMATS_DOC:
                continue
            if v not in FORMATS:
                errs.append(f"{where}: format '{v}' non supportato (ammessi: {', '.join(sorted(FORMATS | FORMATS_DOC))})")
                continue
        elif k == "pattern":
            try:
                re.compile(v)
            except (re.error, TypeError):
                errs.append(f"{where}: pattern non valido")
                continue
        elif k in ("minLength", "maxLength", "minItems", "maxItems"):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append(f"{where}: {k} deve essere un intero non negativo")
                continue
        elif k in ("minimum", "maximum"):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(f"{where}: {k} deve essere un numero")
                continue
        elif k in ("nullable",):
            if not isinstance(v, bool):
                errs.append(f"{where}: nullable deve essere true o false")
                continue
        elif k == "enum":
            if not isinstance(v, list) or not v:
                errs.append(f"{where}: enum deve essere una lista non vuota")
                continue
        elif k == "required":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append(f"{where}: required deve essere una lista di nomi")
                continue
        elif k == "properties":
            if not isinstance(v, dict):
                errs.append(f"{where}: properties deve essere una mappa")
                continue
            v = {pn: check_schema(ps, f"{where}.{pn}", errs) for pn, ps in v.items()}
        elif k == "items":
            v = check_schema(v, f"{where}[]", errs)
        elif k == "additionalProperties":
            if isinstance(v, dict):
                v = check_schema(v, f"{where}.*", errs)
            elif not isinstance(v, bool):
                errs.append(f"{where}: additionalProperties deve essere true, false o uno schema")
                continue
        out[k] = v
    return out


def _param_schema(s: Dict[str, Any], where: str, errs: List[str]) -> Dict[str, Any]:
    t = s.get("type")
    if t == "array":
        if s.get("items", {}).get("type") not in SCALAR_PARAM:
            errs.append(f"{where}: un parametro array deve avere items di tipo {', '.join(SCALAR_PARAM)}")
    elif t not in SCALAR_PARAM:
        errs.append(f"{where}: il parametro deve avere type {', '.join(SCALAR_PARAM)} o array")
    return s


def custom_operations(doc: Dict[str, Any], security: bool) -> Tuple[List[Operation], List[str]]:
    """Endpoint scritti a mano in schemas/openapi.yaml: ognuno con operationId, implementato nel service."""
    errs: List[str] = []
    ops: List[Operation] = []
    comps = ((doc.get("components") or {}).get("schemas") or {})
    pcomps = ((doc.get("components") or {}).get("parameters") or {})
    for path, item in (doc.get("paths") or {}).items():
        w = f"openapi.yaml paths.{path}"
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            errs.append(f"{w}: percorso non valido")
            continue
        segs = [s for s in path.split("/") if s]
        if any(not re.match(r"^(\{[a-z][A-Za-z0-9]*\}|[a-z0-9][a-z0-9._-]*)$", s) for s in segs):
            errs.append(f"{w}: ogni segmento è un nome in minuscolo o un parametro {{nomeCamel}}")
            continue
        shared = item.get("parameters") or []
        for method, op in item.items():
            if method in ("parameters", "summary", "description", "servers"):
                continue
            wm = f"{w}.{method}"
            if method not in METHODS:
                errs.append(f"{wm}: metodo non supportato (ammessi: {', '.join(METHODS)})")
                continue
            if not isinstance(op, dict):
                errs.append(f"{wm}: deve essere una mappa")
                continue
            oid = op.get("operationId")
            if not isinstance(oid, str) or not OP_ID.match(oid):
                errs.append(f"{wm}: operationId obbligatorio, in camelCase (es. chiudiSegnalazione): diventa il metodo del service")
                continue
            params: List[Param] = []
            for i, p in enumerate(list(shared) + list(op.get("parameters") or [])):
                wp = f"{wm}.parameters[{i}]"
                if isinstance(p, dict) and "$ref" in p:
                    ref = p["$ref"]
                    p = pcomps.get(ref.rsplit("/", 1)[1]) if isinstance(ref, str) and ref.startswith("#/components/parameters/") else None
                    if p is None:
                        errs.append(f"{wp}: $ref ammessi solo verso #/components/parameters/ esistenti")
                        continue
                if not isinstance(p, dict) or not isinstance(p.get("name"), str) or p.get("in") not in ("path", "query"):
                    errs.append(f"{wp}: parametro con name e in (path o query); header e cookie li gestisce il gateway")
                    continue
                s = check_schema(_resolve(p.get("schema") or {}, comps, wp, errs), wp, errs)
                _param_schema(s, wp, errs)
                params = [x for x in params if not (x.name == p["name"] and x.loc == p["in"])]  # quelli dell'operazione vincono
                params.append(Param(p["name"], p["in"], s, bool(p.get("required")) or p["in"] == "path"))
            names = {s[1:-1] for s in segs if s.startswith("{")}
            declared = {p.name for p in params if p.loc == "path"}
            if names != declared:
                errs.append(f"{wm}: i parametri di path dichiarati ({', '.join(sorted(declared)) or 'nessuno'}) "
                            f"non coincidono con quelli del percorso ({', '.join(sorted(names)) or 'nessuno'})")
            body, body_req = None, False
            rb = op.get("requestBody")
            if rb is not None:
                content = (rb or {}).get("content") or {}
                if list(content) != ["application/json"]:
                    errs.append(f"{wm}.requestBody: solo content application/json")
                else:
                    body = check_schema(_resolve(content["application/json"].get("schema") or {}, comps, f"{wm}.requestBody", errs),
                                        f"{wm}.requestBody", errs)
                    body_req = bool(rb.get("required"))
            elif method in ("post", "put", "patch"):
                body = None
            sec = op.get("security", doc.get("security"))
            scopes = sorted({s for req in (sec or []) for v in (req or {}).values() for s in (v or [])})
            ctx = op.get("x-kybes-context", segs[0] if segs and not segs[0].startswith("{") else "api")
            if not isinstance(ctx, str) or not re.match(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", ctx):
                errs.append(f"{wm}: x-kybes-context in minuscolo (lettere, cifre e -)")
                ctx = "api"
            ok = {str(c) for c in (op.get("responses") or {})}
            status = min((int(c) for c in ok if c.isdigit() and 200 <= int(c) < 300), default=200)
            ops.append(Operation(op_id=oid, method=method, path=path, context=ctx, kind="custom", params=params, body=body,
                                 body_required=body_req, scopes=scopes, secured=bool(sec) if sec is not None else security,
                                 status=status, summary=str(op.get("summary") or oid)))
    return ops, errs


# ------------------------------------------------------------------ piano completo e contratto generato

def security_scheme(doc: Dict[str, Any]) -> Optional[str]:
    """Schema di sicurezza delle operazioni generate: il primo della sicurezza globale del contratto."""
    for req in doc.get("security") or []:
        for name in (req or {}):
            return name
    return None


def build(tables: Dict[str, Table], doc: Optional[Dict[str, Any]]) -> Tuple[List[Operation], Dict[str, Any]]:
    """(operazioni, contratto OpenAPI completo); solleva ContractError con tutti i problemi trovati."""
    doc = copy.deepcopy(doc) if doc else {"openapi": "3.0.3", "info": {"title": "API", "version": "0.1.0"}, "paths": {}}
    errs: List[str] = []
    if not str(doc.get("openapi", "")).startswith("3.0"):
        errs.append("openapi.yaml: serve OpenAPI 3.0.x (openapi: 3.0.3)")
    scheme = security_scheme(doc)
    ops: List[Operation] = []
    for t in tables.values():
        if t.api:
            ops += _ops_of(t, tables, scheme is not None)
    custom, cerrs = custom_operations(doc, scheme is not None)
    errs += cerrs
    ids: Dict[str, str] = {}
    routes: Dict[Tuple[str, str], str] = {}
    for o in ops + custom:
        if o.op_id in ids:
            errs.append(f"operationId {o.op_id} duplicato ({ids[o.op_id]} e {o.method.upper()} {o.path})")
        ids[o.op_id] = f"{o.method.upper()} {o.path}"
        shape = "/".join("{}" if s.startswith("{") else s for s in o.segments)
        if (o.method, shape) in routes:
            errs.append(f"{o.method.upper()} {o.path}: stesso percorso di {routes[(o.method, shape)]}")
        routes[(o.method, shape)] = o.op_id
    if errs:
        raise ContractError(errs)
    return ops + custom, contract(tables, ops, doc, scheme)


def _ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


ERROR_SCHEMA = {"type": "object", "required": ["error"], "properties": {"error": {
    "type": "object", "required": ["code", "message", "correlationId"],
    "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "correlationId": {"type": "string"},
                   "fields": {"type": "object", "additionalProperties": {"type": "string"}}}}}}
ERRORS = {"400": "richiesta non valida (fields: campo -> regola)", "401": "identità mancante",
          "403": "scope o tenant mancanti", "404": "risorsa inesistente", "409": "conflitto (duplicato o record collegati)",
          "422": "regola del modello violata", "500": "errore interno (dettaglio solo nei log, con il correlationId)"}


def _param_doc(p: Param) -> Dict[str, Any]:
    d = {"name": p.name, "in": p.loc, "required": p.required, "schema": p.schema}
    if p.schema.get("type") == "array":
        d.update({"style": "form", "explode": True})
    return d


def contract(tables: Dict[str, Table], ops: List[Operation], doc: Dict[str, Any], scheme: Optional[str]) -> Dict[str, Any]:
    comps = doc.setdefault("components", {}).setdefault("schemas", {})
    comps.setdefault("Error", ERROR_SCHEMA)
    used = {o.table for o in ops} | {next(r for r in tables[o.table].relations if r.name == o.arg).target
                                      for o in ops if o.kind == "rel"}
    for n in sorted(x for x in used if x):
        t = tables[n]
        comps[n] = entity_schema(t)
        comps[f"{n}Page"] = page_schema(_ref(n))
        if t.api and "create" in t.api.operations:
            comps[f"{n}Create"] = create_schema(t)
        if t.api and "update" in t.api.operations:
            comps[f"{n}Update"] = update_schema(t)
    paths = doc.setdefault("paths", {}) or {}
    doc["paths"] = paths
    err_resp = {"description": "errore", "content": {"application/json": {"schema": _ref("Error")}}}
    tags = {x.get("name") for x in doc.get("tags") or [] if isinstance(x, dict)}
    for o in ops:
        t = tables[o.table]
        target = o.table
        if o.kind == "rel":
            r = next(x for x in t.relations if x.name == o.arg)
            target = r.target
        many = o.kind == "list" or (o.kind == "rel" and r.kind == "one_to_many") or \
            (o.kind == "query" and next(q for q in t.queries if q.name == o.arg).returns == "page")
        listing = o.kind == "query" and next(q for q in t.queries if q.name == o.arg).returns == "list"
        out = _ref(f"{target}Page") if many else ({"type": "array", "items": _ref(target)} if listing else _ref(target))
        spec: Dict[str, Any] = {"operationId": o.op_id, "summary": o.summary, "tags": [o.context]}
        if o.params:
            spec["parameters"] = [_param_doc(p) for p in o.params]
        if o.kind in ("create", "update"):
            spec["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": _ref(f"{o.table}{'Create' if o.kind == 'create' else 'Update'}")}}}
        ok = {"description": "nessun contenuto"} if o.status == 204 else \
            {"description": "ok", "content": {"application/json": {"schema": out}}}
        if o.kind == "create":
            ok["headers"] = {"Location": {"schema": {"type": "string"}, "description": "percorso del record creato"}}
        spec["responses"] = {str(o.status): ok, **{c: {**err_resp, "description": d} for c, d in ERRORS.items()}}
        if scheme:
            spec["security"] = [{scheme: o.scopes}]
        spec["x-kybes"] = {"generated": True, "table": o.table, "kind": o.kind, **({"arg": o.arg} if o.arg else {})}
        paths.setdefault(o.path, {})[o.method] = spec
        if o.context not in tags:
            doc.setdefault("tags", []).append({"name": o.context})
            tags.add(o.context)
    doc["paths"] = dict(sorted(paths.items()))
    return doc


# ------------------------------------------------------------------ YAML deterministico

_PLAIN = re.compile(r"^[A-Za-z_/][A-Za-z0-9_ ./{}()-]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", "y", "n"}


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    s = str(v)
    if _PLAIN.match(s) and s.lower() not in _RESERVED and not s.endswith(" ") and ": " not in s and " #" not in s:
        return s
    return json.dumps(s, ensure_ascii=False)


def dump_yaml(node: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(node, dict):
        if not node:
            return "{}"
        lines = []
        for k, v in node.items():
            key = _scalar(k) if not str(k).startswith("$") else json.dumps(str(k))
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:\n{dump_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}{key}: {dump_yaml(v, indent + 1) if isinstance(v, (dict, list)) else _scalar(v)}")
        return "\n".join(lines)
    if isinstance(node, list):
        if not node:
            return "[]"
        lines = []
        for v in node:
            if isinstance(v, dict) and v:
                body = dump_yaml(v, indent + 1)
                lines.append(f"{pad}- {body[len(pad) + 2:]}")
            elif isinstance(v, list) and v:
                lines.append(f"{pad}-\n{dump_yaml(v, indent + 1)}")
            else:
                lines.append(f"{pad}- {dump_yaml(v) if isinstance(v, (dict, list)) else _scalar(v)}")
        return "\n".join(lines)
    return pad + _scalar(node)


# ------------------------------------------------------------------ dati per gli emettitori

def op_spec(o: Operation) -> Dict[str, Any]:
    """Descrizione compatta di un'operazione, incorporata come JSON nel codice generato di ogni linguaggio."""
    return {"id": o.op_id, "method": o.method.upper(), "path": o.path, "context": o.context, "kind": o.kind,
            "table": o.table, "arg": o.arg, "status": o.status, "secured": o.secured, "scopes": o.scopes,
            "params": [{"name": p.name, "in": p.loc, "required": p.required, "schema": p.schema} for p in o.params],
            "body": o.body, "bodyRequired": o.body_required}


# ------------------------------------------------------------------ valori di esempio per i test generati

class NoSample(Exception):
    """Lo schema ammette valori che il generatore non sa costruire (es. pattern senza enum)."""


def sample(s: Dict[str, Any]) -> Any:
    """Un valore valido per lo schema, deterministico; NoSample se non costruibile."""
    if "enum" in s:
        return s["enum"][0]
    t = s.get("type")
    if t == "string":
        if "pattern" in s:
            raise NoSample(s["pattern"])
        fmt = s.get("format")
        if fmt == "uuid":
            return "00000000-0000-4000-8000-000000000042"
        if fmt == "date":
            return "2026-01-02"
        if fmt == "date-time":
            return "2026-01-02T03:04:05.000Z"
        n = max(s.get("minLength", 1), 1)
        v = ("kybes" * (n // 5 + 1))[:max(n, 5)]
        return v[: s["maxLength"]] if "maxLength" in s else v
    if t in ("integer", "number"):
        lo, hi = s.get("minimum"), s.get("maximum")
        v = 1 if lo is None else lo
        if hi is not None and v > hi:
            v = hi
        return int(v) if t == "integer" else v
    if t == "boolean":
        return True
    if t == "array":
        return [sample(s.get("items", {})) for _ in range(s.get("minItems", 0) or 1)][: s.get("maxItems", 1) or 1] \
            if s.get("minItems", 0) or "items" in s else []
    if t == "object" or "properties" in s:
        props = s.get("properties", {})
        return {k: sample(props[k]) if k in props else "kybes" for k in s.get("required", [])}
    return "kybes"
