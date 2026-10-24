"""Emettitore delle API Python: operazioni del contratto, controller CRUD per tabella, interfaccia dei metodi custom."""
from __future__ import annotations

import json
from typing import Dict, List

import runtime_api_python as rt
from api_plan import Operation, op_spec, prop
from naming import header, member, method_name, repo_class
from schema import Table, snake
from sqlonly import has_sql

L = "python"

CONVERT = '''"""Conversioni tra il JSON delle API e i valori del modello (uguali in tutti i linguaggi).

uuid, bigint e decimal viaggiano come stringhe; date "AAAA-MM-GG"; datetime ISO 8601 in UTC al millisecondo ("...Z").
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional

_DT = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\\.([0-9]{1,9}))?(Z|([+-])([0-9]{2}):([0-9]{2}))$")


def to_uuid(v: Any) -> Any:
    return None if v is None else uuid.UUID(v)


def to_int(v: Any) -> Any:
    return None if v is None else int(v)


def to_decimal(v: Any) -> Any:
    return None if v is None else Decimal(v)


def to_date(v: Any) -> Any:
    return None if v is None else date.fromisoformat(v)


def to_datetime(v: Any) -> Any:
    if v is None:
        return None
    m = _DT.match(v)
    y, mo, d, h, mi, s, frac, z, sign, oh, om = m.groups()
    tz = timezone.utc if z == "Z" else timezone((1 if sign == "+" else -1) * timedelta(hours=int(oh), minutes=int(om)))
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(3, "0")[:3]) * 1000, tzinfo=tz)


def text(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def decimal_text(v: Any, scale: int) -> Optional[str]:
    """Esattamente scale decimali, troncando (mai arrotondando); lo zero senza segno."""
    if v is None:
        return None
    d = Decimal(v).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_DOWN)
    return format(d.copy_abs() if d == 0 else d, "f")


def date_text(v: Any) -> Optional[str]:
    return None if v is None else v.isoformat()


def datetime_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if v.tzinfo is None:  # alcuni database restituiscono date senza fuso: sono in UTC
        v = v.replace(tzinfo=timezone.utc)
    v = v.astimezone(timezone.utc)
    return v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
'''

TO_MODEL = {"uuid": "to_uuid", "bigint": "to_int", "decimal": "to_decimal", "date": "to_date", "datetime": "to_datetime"}


def _to_json(c, expr: str) -> str:
    if c.type in ("uuid", "bigint"):
        return f"text({expr})"
    if c.type == "decimal":
        return f"decimal_text({expr}, {c.scale})"
    if c.type == "date":
        return f"date_text({expr})"
    if c.type == "datetime":
        return f"datetime_text({expr})"
    return expr


def _to_model(c, expr: str) -> str:
    return f"{TO_MODEL[c.type]}({expr})" if c.type in TO_MODEL else expr


def _table_file(t: Table, tables: Dict[str, Table], ops: List[Operation], api_import: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    exposed = [c for c in t.columns if not c.tenant and c.api_visible]
    writable = [c for c in exposed if not (c.primary_key and c.auto) and not c.generated]
    read, write = ("data.mongo_read", "data.mongo_write") if t.mongo else ("data.neo4j_read", "data.neo4j_write") if t.neo4j else ("data.read", None)
    expand_targets = {r.target for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable} if t.api and t.api.expandable else set()
    targets = sorted(({next(r for r in t.relations if r.name == o.arg).target for o in ops if o.kind == "rel"} | expand_targets) - {n})
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n") + "\n# ruff: noqa",
         f'"""Controller di {n}: logica CRUD e query; riceve le chiamate dall\'API layer e accede al model."""',
         "from __future__ import annotations", "", "from typing import Any, Dict", "",
         "from model.generated import PageRequest",
         f"from model.generated.{n} import {n}", f"from model.{n} import {repo}",
         "from ._convert import date_text, datetime_text, decimal_text, text, to_date, to_datetime, to_decimal, to_int, to_uuid",
         "from ._data import ApiData", f"from {api_import}.generated._http import ApiError, ApiResponse, Call"]
    for tg in targets:
        o.append(f"from . import {tg} as {snake(tg)}_api  # import del modulo: le relazioni possono essere circolari")
    o += ["", "", f"def to_json(e: {n}) -> Dict[str, Any]:", f'    """{n} nel formato del contratto (senza tenant)."""', "    return {"]
    o += [f'        "{prop(c.name)}": {_to_json(c, "e." + member(L, c.name))},' for c in exposed]
    o += ["    }", "", "", "def values(body: Dict[str, Any]) -> Dict[str, Any]:",
          '    """Campi presenti nel corpo (già validato) come valori del modello."""', "    out: Dict[str, Any] = {}"]
    for c in writable:
        o += [f'    if "{prop(c.name)}" in body:', f'        out["{member(L, c.name)}"] = {_to_model(c, "body[" + repr(prop(c.name)) + "]")}']
    o += ["    return out", "", "",
          "def _page(p: Any, conv: Any = None) -> Dict[str, Any]:",
          "    return {\"items\": [(conv or to_json)(x) for x in p.items], \"nextCursor\": p.next_cursor, \"limit\": p.limit}", "", "",
          "def _request(q: Dict[str, Any]) -> PageRequest:",
          '    return PageRequest(limit=q.get("limit"), cursor=q.get("cursor"), sort=q.get("sort"))', ""]
    if t.mongo:
        o += ["", f"def _write(data: ApiData, call: Call, work: Any) -> Any:", "    return data.mongo_write(call.tenant, work)", ""]
    elif t.neo4j:
        o += ["", f"def _write(data: ApiData, call: Call, work: Any) -> Any:", "    return data.neo4j_write(call.tenant, work)", ""]
    else:
        o += ["", f"def _write(data: ApiData, call: Call, work: Any) -> Any:", f'    return data.write(["{n}"], call.tenant, work)', ""]
    key = _to_model(t.pk, 'call.path["id"]')
    handlers = []
    for op in ops:
        fn = snake(op.op_id)
        handlers.append((op.op_id, fn))
        o += ["", f"def {fn}(data: ApiData, call: Call) -> Any:", f'    """{op.method.upper()} {op.path}: {op.summary}."""']
        if op.kind == "list":
            expandable = [r for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable] if (t.api and t.api.expandable and not t.mongo and not t.neo4j) else []
            if expandable:
                exp_allowed_sorted = sorted(prop(r.name) for r in expandable)
                exp_map_items = ", ".join(f"{prop(r.name)!r}: {r.name!r}" for r in expandable)
                o += [f'    expand_raw = call.query.get("expand", "")',
                      f"    expand = [x.strip() for x in expand_raw.split(\",\") if x.strip()] if expand_raw else []",
                      f"    _exp_allowed = {{{', '.join(repr(x) for x in exp_allowed_sorted)}}}",
                      f"    _bad = [x for x in expand if x not in _exp_allowed]",
                      f"    if _bad:",
                      f'        raise ApiError("VALIDATION", f"invalid expand: {{_bad}}")',
                      f"    _exp_map = {{{exp_map_items}}}",
                      f"    _model_expand = [_exp_map[x] for x in expand]",
                      f"    with {read}(call.tenant) as s:",
                      f"        repo = {repo}(s)",
                      f"        p = repo.list_page_expand(_model_expand, _request(call.query)) if _model_expand else repo.list_page(_request(call.query))"]
                o.append(f"        def _conv(e: Any) -> Dict[str, Any]:")
                o.append(f"            d = to_json(e)")
                o.append(f"            for _rn in expand:")
                for r in expandable:
                    target_conv = "to_json" if r.target == n else f"{snake(r.target)}_api.to_json"
                    fk_nullable = t.col(r.foreign_key).nullable
                    o.append(f"                if _rn == {prop(r.name)!r}:")
                    o.append(f"                    _v = e.{member(L, r.name)}")
                    if fk_nullable:
                        o.append(f"                    d[{prop(r.name)!r}] = {target_conv}(_v) if _v is not None else None")
                    else:
                        o.append(f"                    d[{prop(r.name)!r}] = {target_conv}(_v)")
                o.append(f"            return d")
                o.append(f"        return _page(p, _conv if expand else None)")
            else:
                o += [f"    with {read}(call.tenant) as s:", f"        return _page({repo}(s).list_page(_request(call.query)))"]
        elif op.kind == "get":
            o += [f"    with {read}(call.tenant) as s:", f"        e = {repo}(s).get_by_id({key})",
                  "        if e is None:", '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")', "        return to_json(e)"]
        elif op.kind == "create":
            o += ["    def work(s: Any) -> Dict[str, Any]:", f"        return to_json({repo}(s).create({n}(**values(call.body))))", "",
                  "    body = _write(data, call, work)",
                  f'    return ApiResponse(201, body, {{"content-type": "application/json", "location": call.base_path + "{op.path}/" + str(body["{prop(t.pk.name)}"])}})']
        elif op.kind == "update":
            o += ["    def work(s: Any) -> Dict[str, Any]:", f"        e = {repo}(s).update({key}, values(call.body))",
                  "        if e is None:", '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")', "        return to_json(e)", "",
                  "    return _write(data, call, work)"]
        elif op.kind == "delete":
            o += ["    def work(s: Any) -> None:", f"        if not {repo}(s).delete({key}):", '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")', "",
                  "    _write(data, call, work)", "    return ApiResponse(204)"]
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            args = []
            for c in q.where:
                if not c.param:
                    continue
                col = t.col(c.column)
                v = f'call.query["{_camel(c.param)}"]'
                args.append(f"[{_to_model(col, 'x')} for x in {v}]" if c.op == "in" and col.type in TO_MODEL else _to_model(col, v))
            if q.returns == "page":
                args.append("page=_request(call.query)")
            meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
            call = f"{repo}(s).{meth}({', '.join(args)})"
            o.append(f"    with {read}(call.tenant) as s:")
            if q.returns == "page":
                o.append(f"        return _page({call})")
            elif q.returns == "list":
                o.append(f"        return [to_json(x) for x in {call}]")
            else:
                o += [f"        e = {call}", "        if e is None:", '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")',
                      "        return to_json(e)"]
        elif op.kind == "rel":
            r = next(x for x in t.relations if x.name == op.arg)
            conv = "to_json" if r.target == n else f"{snake(r.target)}_api.to_json"
            o.append(f"    with {read}(call.tenant) as s:")
            o.append(f"        repo = {repo}(s)")
            if r.kind == "many_to_one":
                o += [f"        e = repo.{method_name(L, 'get_rel:' + r.name)}({key})", "        if e is None:",
                      '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")', f"        return {conv}(e)"]
            else:
                o += [f"        if not repo.exists({key}):", '            raise ApiError("NOT_FOUND", "RECORD_NOT_FOUND")',
                      f"        return _page(repo.{method_name(L, 'list_rel:' + r.name)}({key}, page=_request(call.query)), {conv})"]
        o.append("")
    o += ["", "HANDLERS = {" + ", ".join(f'"{i}": {f}' for i, f in handlers) + "}"]
    return "\n".join(o) + "\n"


def rel_targets(tables: Dict[str, Table], ops: List[Operation]) -> set:
    return {next(r for r in tables[o.table].relations if r.name == o.arg).target for o in ops if o.kind == "rel"}


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def _custom_file(ops: List[Operation]) -> str:
    o = [header(L, "schemas/openapi.yaml").rstrip("\n") + "\n# ruff: noqa",
         '"""Endpoint custom del contratto (schemas/openapi.yaml): un metodo per operationId, da implementare nel service.',
         "", "Ogni metodo riceve il Call con path, query e body già validati e l'identità; restituisce il corpo JSON della risposta",
         "(stato del contratto) o un ApiResponse. Gli errori applicativi si sollevano con ApiError.", '"""',
         "from __future__ import annotations", "", "from typing import Any, Protocol", "", "from ._http import Call", "", "",
         "class Operations(Protocol):"]
    for op in ops:
        ins = ", ".join(f"{p.loc} {p.name}" for p in op.params) + (", body" if op.body is not None else "")
        o += [f"    def {snake(op.op_id)}(self, call: Call) -> Any:", f'        """{op.method.upper()} {op.path} ({op.context}): {op.summary}.'
              + (f" Input: {ins}." if ins else "") + '"""']
        o.append("")
    if not ops:
        o += ["    pass", ""]
    return "\n".join(o).rstrip("\n") + "\n"


def _init_file(tables: Dict[str, Table], ops: List[Operation], ac: Dict, ctrl_import: str) -> str:
    exposed = [n for n in tables if any(o.table == n for o in ops) or n in rel_targets(tables, ops)]
    o = [header(L, "kit").rstrip("\n") + "\n# ruff: noqa",
         '"""API REST generate: build_api(data, custom, contexts) -> Api; adattatori per Lambda, ASGI e FastAPI."""',
         "from __future__ import annotations", "", "from functools import partial", "from typing import Any, Dict, Iterable, Optional", "",
         f"from {ctrl_import}.generated._data import ApiData", "from ._http import ApiError, ApiRequest, ApiResponse, Call, Identity",
         "from ._router import Api", "from .operations import SPECS",
         *(["from .custom import Operations"] if any(x.kind == "custom" for x in ops) else [])]
    for n in exposed:
        o.append(f"from {ctrl_import}.generated.{n} import HANDLERS as _{snake(n)}")
    o += ["", "CONTROLLERS: Dict[str, Any] = {" + ", ".join(f"**_{snake(n)}" for n in exposed) + "}",
          f"BASE_PATH = {ac.get('base_path', '')!r}",
          *([f"CUSTOM = {{{', '.join(f'{x.op_id!r}: {snake(x.op_id)!r}' for x in ops if x.kind == 'custom')}}}  # operationId -> metodo di custom.Operations"]
            if any(x.kind == "custom" for x in ops) else []), "", "",
          "def build_api(data: ApiData, custom: Any = None, contexts: Optional[Iterable[str]] = None, base_path: str = BASE_PATH) -> Api:",
          '    """Api con le operazioni dei contesti indicati (tutti se None); custom implementa i metodi di custom.Operations."""',
          "    wanted = None if contexts is None else set(contexts)", "    handlers: Dict[str, Any] = {}", "    for spec in SPECS:",
          '        if wanted is not None and spec["context"] not in wanted:', "            continue",
          *(['        if spec["kind"] == "custom":', '            fn = getattr(custom, CUSTOM[spec["id"]], None)', "            if fn is None:",
             '                raise TypeError(f"manca il metodo {CUSTOM[spec[\'id\']]} per l\'operazione {spec[\'id\']} (custom.Operations)")',
             '            handlers[spec["id"]] = fn', "        else:", '            handlers[spec["id"]] = partial(CONTROLLERS[spec["id"]], data)']
            if any(x.kind == "custom" for x in ops) else ['        handlers[spec["id"]] = partial(CONTROLLERS[spec["id"]], data)']),
          '    return Api([s for s in SPECS if s["id"] in handlers], handlers, base_path)', "", "",
          '__all__ = ["Api", "ApiData", "ApiError", "ApiRequest", "ApiResponse", "Call", "Identity", "build_api"'
          + (', "Operations"' if any(x.kind == "custom" for x in ops) else "") + "]"]
    return "\n".join(o) + "\n"


def emit(tables: Dict[str, Table], ops: List[Operation], ac: Dict, opts: Dict):
    """Restituisce (api_files, controller_files): file separati per il layer HTTP e per i controller."""
    sql, mongo, neo4j = has_sql(tables), any(t.mongo for t in tables.values()), any(t.neo4j for t in tables.values())
    api_import = opts.get("api_dir", "api").rsplit("/", 1)[-1]
    ctrl_import = opts.get("controller_dir", "controllers").rsplit("/", 1)[-1]
    rt_files = rt.files(sql, mongo, ac["claims"], ac["headers"], neo4j=neo4j)
    api_rt_keys = {"_schema.py", "_http.py", "_identity.py", "_router.py", "lambda_adapter.py", "asgi_adapter.py", "fastapi_adapter.py"}
    ctrl_rt_keys = {"_data.py"}
    api_files = {f"generated/{k}": v for k, v in rt_files.items() if k in api_rt_keys}
    ctrl_files = {f"generated/{k}": v for k, v in rt_files.items() if k in ctrl_rt_keys}
    ctrl_files["generated/_convert.py"] = rt.HEAD + CONVERT
    specs = json.dumps([op_spec(o) for o in ops], ensure_ascii=False, indent=1)
    api_files["generated/operations.py"] = (header(L, "schemas/generated/openapi.yaml").rstrip("\n") + "\n# ruff: noqa\n"
                                            '"""Operazioni del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo."""\n'
                                            "import json\n\nSPECS = json.loads(r'''" + specs + "''')\n")
    for n, t in tables.items():
        tops = [o for o in ops if o.table == n]
        if tops or n in rel_targets(tables, ops):
            ctrl_files[f"generated/{n}.py"] = _table_file(t, tables, tops, api_import)
    if any(o.kind == "custom" for o in ops):
        api_files["generated/custom.py"] = _custom_file([o for o in ops if o.kind == "custom"])
    api_files["generated/__init__.py"] = _init_file(tables, ops, ac, ctrl_import)
    api_files["__init__.py"] = header(L, "kit").rstrip("\n") + '\n"""Pacchetto API REST: routing, validazione e adattatori (vedi schemas/generated/openapi.yaml)."""\n'
    ctrl_files["__init__.py"] = header(L, "kit").rstrip("\n") + '\n"""Controller generati: logica CRUD, query e conversioni JSON <-> modello."""\n'
    return api_files, ctrl_files
