"""Rende i casi di test delle API (scope "api" del catalogo) in pytest, per il pacchetto Python del modello.

I test chiamano Api.handle con richieste costruite come quelle degli adattatori: niente rete, stessi controlli del
gateway già applicati (identità come claim verificati). I dati di partenza si inseriscono con i builder del modello
in una sessione confermata (seed), perché le API lavorano in sessioni e transazioni proprie.
"""
from __future__ import annotations

import json
from typing import Dict, List

import api_plan
import test_python as tp
from api_plan import Operation, prop
from naming import header, member
from schema import Table, snake
from sqlonly import has_sql
from verification import API, API_RT, METHODS, RUNTIME, Catalog, TestCase, table_asil, ttl_column

L = "python"


def index(tables: Dict[str, Table], ops: List[Operation]) -> Dict[str, str]:
    out = {n: f"generated/test_api_{snake(n)}.py" for n in tables if any(o.table == n for o in ops)}
    out[API_RT] = out[RUNTIME] = "generated/test_api_runtime.py"
    if any(o.kind == "custom" for o in ops):
        out[API] = "generated/test_api_custom.py"
    return out


# ------------------------------------------------------------------ valori JSON di esempio (espressioni Python)

def _json_sample(t: Table, c) -> str:
    if c.name == ttl_column(t):
        return {"date": "(date.today() + timedelta(days=next_n())).isoformat()",
                "datetime": "datetime_text(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=next_n()))"}[c.type]
    if c.type == "string":
        return f"text_value(next_n(), {c.length})"
    if c.type == "decimal":
        return "str(next_n())" if not c.scale else f"str(next_n()) + '.' + '5' * {c.scale}"
    return {"uuid": "str(uuid.uuid4())", "text": "f'testo {next_n()}'", "int": "next_n()", "bigint": "str(next_n())",
            "bool": "True", "date": "(date(2026, 1, 1) + timedelta(days=next_n())).isoformat()",
            "datetime": "datetime_text(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=next_n()))",
            "json": "{'n': next_n()}"}[c.type]


def _json_new(c) -> str:
    if c.type == "string":
        return f"'u' + text_value(next_n(), {max(c.length - 1, 1)})"
    if c.type == "decimal":
        return "str(next_n() + 500)" if not c.scale else f"str(next_n() + 500) + '.' + '2' * {c.scale}"
    return {"text": "'testo aggiornato'", "int": "next_n() + 500", "bigint": "str(next_n() + 500)", "bool": "False"}[c.type]


def _jkey(pk, expr: str) -> str:
    """Chiave del modello nel formato JSON del contratto."""
    return f"str({expr})" if pk.type in ("uuid", "bigint") else expr


def _missing_json(pk) -> str:
    return {"uuid": "'00000000-0000-4000-8000-000000000999'", "int": "987654321", "bigint": "'987654321'",
            "string": "'kybes-non-esiste'"}[pk.type]


def _path(op: Operation, key: str) -> str:
    """Percorso dell'operazione con {id} sostituito (key è un'espressione Python)."""
    if "{id}" not in op.path:
        return repr(op.path)
    a, b = op.path.split("{id}")
    return f"{a!r} + str({key}) + {b!r}"


def _body_fn(t: Table, tables: Dict[str, Table]) -> List[str]:
    """def body(): corpo valido per POST, con i padri obbligatori inseriti prima (seed)."""
    o = ["def body(seed) -> dict:", f'    """Corpo valido per la creazione di {t.name}, con ogni chiave esterna verso un padre inserito prima."""',
         "    out = {}"]
    for c in api_plan.writable_columns(t):
        rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
        if rel:
            tg = tables[rel.target]
            o.append(f"    out[{prop(c.name)!r}] = {_jkey(tg.pk, f'seed(lambda session: build_{snake(rel.target)}(session)).{member(L, tg.pk.name)}')}")
            continue
        o.append(f"    out[{prop(c.name)!r}] = {_json_sample(t, c)}")
    o += ["    return out", ""]
    return o


# ------------------------------------------------------------------ file per tabella

def _case(t: Table, tc: TestCase, tables: Dict[str, Table], ops: List[Operation]) -> List[str]:
    n, k = t.name, tc.kind
    base = "/" + t.api.path
    pkp = prop(t.pk.name)
    build = f"seed(lambda session: build_{snake(n)}(session))"
    key = _jkey(t.pk, f"e.{member(L, t.pk.name)}")
    op = next((o for o in ops if o.op_id == tc.args.get("operation")), None)
    if k == "api_list":
        return [f"    e = {build}", f"    r = api('GET', {base!r}, query={{'limit': {t.pagination.max_limit}}})",
                "    assert r.status == 200, r.body", f"    assert r.body['limit'] == {t.pagination.max_limit}",
                f"    assert any(x[{pkp!r}] == {key} for x in r.body['items'])"]
    if k == "api_list_params":
        return [f"    r = api('GET', {base!r}, query={{'limit': 0}})", "    assert r.status == 400 and r.body['error']['fields'] == {'limit': 'valore minimo 1'}",
                f"    r = api('GET', {base!r}, query={{'kybesSconosciuto': 1}})",
                "    assert r.status == 400 and r.body['error']['fields'] == {'kybesSconosciuto': 'parametro sconosciuto'}"]
    if k == "api_list_expand":
        rels = [next(x for x in t.relations if x.name == rn) for rn in tc.args["relations"]]
        exp_val = tc.args["expand"]
        o = ["    with seeding() as session:"]
        seen_targets = {}
        fk_args = []
        for rel in rels:
            tg = tables[rel.target]
            if rel.target == n:
                var = "self_p"
            elif rel.target not in seen_targets:
                var = f"p_{snake(rel.target)}"
                o.append(f"        {var} = build_{snake(rel.target)}(session)")
                seen_targets[rel.target] = var
            else:
                var = seen_targets[rel.target]
            fk_args.append(f"{member(L, rel.foreign_key)}={var}.{member(L, tg.pk.name)}")
        if any(r.target == n for r in rels):
            o.append(f"        self_p = build_{snake(n)}(session)")
        o.append(f"        e = build_{snake(n)}(session, {', '.join(fk_args)})")
        o += [f"    r = api('GET', {base!r}, query={{'expand': {exp_val!r}, 'limit': {t.pagination.max_limit}}})",
              "    assert r.status == 200, r.body",
              f"    hit = next(x for x in r.body['items'] if x[{pkp!r}] == {_jkey(t.pk, 'e.' + member(L, t.pk.name))})"]
        for rel in rels:
            o.append(f"    assert {prop(rel.name)!r} in hit and hit[{prop(rel.name)!r}] is not None")
        return o
    if k == "api_list_expand_bad":
        return [f"    r = api('GET', {base!r}, query={{'expand': 'kybesNonEsiste'}})",
                "    assert r.status == 400 and 'invalid expand' in r.body['error']['code']"]
    if k == "api_get":
        return [f"    e = {build}", f"    r = api('GET', {base!r} + '/' + str({key}))", "    assert r.status == 200, r.body",
                "    assert r.body == to_json(e)"]
    if k == "api_get_missing":
        return [f"    r = api('GET', {base!r} + '/' + str({_missing_json(t.pk)}))",
                "    assert r.status == 404 and r.body['error']['code'] == 'RECORD_NOT_FOUND'"]
    if k == "api_get_badid":
        return [f"    r = api('GET', {base + '/kybes-non-valido'!r})", f"    assert r.status == 400 and r.body['error']['fields'] == {{'id': {tc.args['rule']!r}}}"]
    if k == "api_create":
        return ["    sent = body(seed)", f"    r = api('POST', {base!r}, sent)", "    assert r.status == 201, r.body",
                f"    assert r.headers['location'] == {base!r} + '/' + str(r.body[{pkp!r}])",
                "    for name, value in sent.items():", "        assert r.body[name] == value, name"]
    if k == "api_create_required":
        p = prop(tc.args["column"])
        return ["    sent = body(seed)", f"    del sent[{p!r}]", f"    r = api('POST', {base!r}, sent)",
                f"    assert r.status == 400 and r.body['error']['fields'] == {{{p!r}: 'obbligatorio'}}"]
    if k == "api_create_extra":
        return ["    sent = body(seed)", "    sent['kybesSconosciuto'] = 1", f"    r = api('POST', {base!r}, sent)",
                "    assert r.status == 400 and r.body['error']['fields'] == {'kybesSconosciuto': 'non ammesso'}"]
    if k == "api_create_type":
        c = t.col(tc.args["column"])
        p = prop(c.name)
        wrong = "'x'" if c.type in ("int", "bool") else "12345"
        return ["    sent = body(seed)", f"    sent[{p!r}] = {wrong}", f"    r = api('POST', {base!r}, sent)",
                f"    assert r.status == 400 and r.body['error']['fields'] == {{{p!r}: {tc.args['rule']!r}}}"]
    if k == "api_create_duplicate":
        p = prop(tc.args["column"])
        return ["    first = body(seed)", f"    assert api('POST', {base!r}, first).status == 201", "    second = body(seed)",
                f"    second[{p!r}] = first[{p!r}]", f"    r = api('POST', {base!r}, second)",
                "    assert r.status == 409 and r.body['error']['code'] in ('CONSTRAINT', 'DUPLICATE'), r.body"]
    if k == "api_update":
        if "column" in tc.args:
            c = t.col(tc.args["column"])
            p = prop(c.name)
            return [f"    e = {build}", f"    value = {_json_new(c)}", f"    r = api('PATCH', {base!r} + '/' + str({key}), {{{p!r}: value}})",
                    "    assert r.status == 200, r.body", f"    assert r.body[{p!r}] == value and r.body[{pkp!r}] == {key}"]
        return [f"    e = {build}", f"    r = api('PATCH', {base!r} + '/' + str({key}), {{}})", "    assert r.status == 200, r.body",
                f"    assert r.body[{pkp!r}] == {key}"]
    if k == "api_update_missing":
        return [f"    r = api('PATCH', {base!r} + '/' + str({_missing_json(t.pk)}), {{}})",
                "    assert r.status == 404 and r.body['error']['code'] == 'RECORD_NOT_FOUND'"]
    if k == "api_update_key":
        return [f"    e = {build}", f"    r = api('PATCH', {base!r} + '/' + str({key}), {{{pkp!r}: {key}}})",
                f"    assert r.status == 400 and r.body['error']['fields'] == {{{pkp!r}: 'non ammesso'}}"]
    if k == "api_delete":
        has_get = any(o.table == n and o.kind == "get" for o in ops)
        return [f"    e = {build}", f"    r = api('DELETE', {base!r} + '/' + str({key}))", "    assert r.status == 204 and r.body is None",
                f"    assert api({'GET' if has_get else 'DELETE'!r}, {base!r} + '/' + str({key})).status == 404"]
    if k == "api_delete_missing":
        return [f"    r = api('DELETE', {base!r} + '/' + str({_missing_json(t.pk)}))",
                "    assert r.status == 404 and r.body['error']['code'] == 'RECORD_NOT_FOUND'"]
    if k == "api_query":
        q = next(x for x in t.queries if x.name == op.arg)
        setup = tp._query_case(t, TestCase("TC-X", n, [], "req", "query_match", "", "", {"query": q.name}), tables)
        cut = next(i for i, line in enumerate(setup) if "Repository(session)." in line)
        o = ["    with seeding() as session:"] + ["    " + line for line in setup[:cut]]
        qp = [f"{c.param[:1].lower() + c.param[1:]!r}: qv({snake(c.param)})" for c in q.where if c.param]
        o.append(f"    r = api('GET', {op.path!r}, query={{{', '.join(qp)}}})")
        o.append("    assert r.status == 200, r.body")
        if q.returns == "page":
            o.append(f"    assert any(x[{pkp!r}] == {key} for x in r.body['items'])")
        elif q.returns == "list":
            o.append(f"    assert any(x[{pkp!r}] == {key} for x in r.body)")
        else:
            o += [f"    assert r.body[{pkp!r}] == {key}", "    with seeding() as session:", f"        {tp.repo_class(L, n)}(session).delete(e.{member(L, t.pk.name)})",
                  f"    r = api('GET', {op.path!r}, query={{{', '.join(qp)}}})", "    assert r.status == 404 and r.body['error']['code'] == 'RECORD_NOT_FOUND'"]
        return o
    if k == "api_query_params":
        q = next(x for x in t.queries if x.name == op.arg)
        o = ["    with seeding() as session:"]
        setup = tp._query_case(t, TestCase("TC-X", n, [], "req", "query_match", "", "", {"query": q.name}), tables)
        cut = next(i for i, line in enumerate(setup) if "Repository(session)." in line)
        o += ["    " + line for line in setup[:cut]]
        qp = [f"{c.param[:1].lower() + c.param[1:]!r}: qv({snake(c.param)})" for c in q.where if c.param
              and c.param[:1].lower() + c.param[1:] != tc.args["param"]]
        return o + [f"    r = api('GET', {op.path!r}, query={{{', '.join(qp)}}})",
                    f"    assert r.status == 400 and r.body['error']['fields'] == {{{tc.args['param']!r}: 'obbligatorio'}}"]
    if k == "api_rel":
        r = next(x for x in t.relations if x.name == tc.args["relation"])
        tg = tables[r.target]
        if r.kind == "many_to_one":
            fk = member(L, r.foreign_key)
            return ["    with seeding() as session:", f"        p = build_{snake(r.target)}(session)",
                    f"        e = build_{snake(n)}(session, {fk}=p.{member(L, tg.pk.name)})",
                    f"    r = api('GET', {_path(op, key)})", "    assert r.status == 200, r.body",
                    f"    assert r.body[{prop(tg.pk.name)!r}] == {_jkey(tg.pk, 'p.' + member(L, tg.pk.name))}"]
        fk = member(L, r.foreign_key)
        return ["    with seeding() as session:", f"        e = build_{snake(n)}(session)",
                f"        c = build_{snake(r.target)}(session, {fk}=e.{member(L, t.pk.name)})",
                f"    r = api('GET', {_path(op, key)}, query={{'limit': {tg.pagination.max_limit}}})", "    assert r.status == 200, r.body",
                f"    assert any(x[{prop(tg.pk.name)!r}] == {_jkey(tg.pk, 'c.' + member(L, tg.pk.name))} for x in r.body['items'])"]
    if k == "api_rel_missing":
        return [f"    r = api('GET', {_path(op, _missing_json(t.pk))})", "    assert r.status == 404 and r.body['error']['code'] == 'RECORD_NOT_FOUND'"]
    if k in ("api_auth", "api_scope", "api_tenant_missing"):
        ident = {"api_auth": "None", "api_scope": "Identity(subject='kybes-test', tenant=str(TENANT_A))",
                 "api_tenant_missing": "Identity(subject='kybes-test', scopes=SCOPES)"}[k]
        want = {"api_auth": (401, "IDENTITY_REQUIRED"), "api_scope": (403, "SCOPE_REQUIRED"), "api_tenant_missing": (403, "TENANT_REQUIRED")}[k]
        o = []
        args = ""
        if op.kind == "create":
            o.append("    sent = body(seed)")
            args = ", sent"
        elif op.kind == "update":
            args = ", {}"
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            setup = tp._query_case(t, TestCase("TC-X", n, [], "req", "query_match", "", "", {"query": q.name}), tables)
            cut = next(i for i, line in enumerate(setup) if "Repository(session)." in line)
            o += ["    with seeding() as session:"] + ["    " + line for line in setup[:cut]]
            args = ", query={" + ", ".join(f"{c.param[:1].lower() + c.param[1:]!r}: qv({snake(c.param)})" for c in q.where if c.param) + "}"
        elif op.kind == "rel":
            o.append(f"    e = {build}")
        key_expr = key if op.kind == "rel" else _missing_json(t.pk)
        return o + [f"    r = api({op.method.upper()!r}, {_path(op, key_expr)}{args}, identity={ident})",
                    f"    assert r.status == {want[0]} and r.body['error']['code'] == {want[1]!r}, r.body"]
    if k == "api_tenant_other":
        return [f"    e = {build}", f"    r = api('GET', {base!r} + '/' + str({key}), identity=Identity(subject='kybes-test', tenant=str(TENANT_B), scopes=SCOPES))",
                "    assert r.status == 404"]
    raise ValueError(k)


def _head(asil: str, what: str) -> List[str]:
    return [header(L, "kit").rstrip("\n") + "\n# ruff: noqa", f'"""{what} (ASIL {asil}). Specifica: docs/generated/verification/."""',
            "import uuid", "from datetime import date, datetime, timedelta, timezone", "from decimal import Decimal", "",
            "import pytest", ""]


def table_file(t: Table, cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> str:
    n = t.name
    api_import = opts.get("api_dir", "api").rsplit("/", 1)[-1]
    ctrl_import = opts.get("controller_dir", "controllers").rsplit("/", 1)[-1]
    others = sorted({r.target for r in t.relations} | {n})
    o = _head(table_asil(t, asil), f"Test di unità generati per le API di {n}")
    mixed_mongo = t.mongo and has_sql(tables)
    o += [f"from {api_import}.generated import Identity", f"from {ctrl_import}.generated.{n} import to_json", f"from model.{n} import {tp.repo_class(L, n)}", f"from {ctrl_import}.generated._convert import datetime_text",
          "from model.generated import PageRequest",
          "from kybes_builders import (" + ", ".join(f"build_{snake(x)}" for x in others) + ", different, greater, next_n, smaller, text_value, TENANT_A, TENANT_B)",
          "from kybes_api import SCOPES, api, custom, qv" + (", seed_mongo, seeding_mongo" if mixed_mongo else ", seed, seeding")
          + "  # noqa: F401 (fixture)", ""]
    if mixed_mongo:  # collection accanto a tabelle SQL: i dati di partenza vanno nella sessione MongoDB
        o += ["", "@pytest.fixture", "def seed(seed_mongo):", "    return seed_mongo", "", "", "@pytest.fixture", "def seeding(seeding_mongo):",
              "    return seeding_mongo"]
    o += ["", ""]
    o += _body_fn(t, tables) + [""]
    for tc in cat.for_table(n, "api"):
        o += ["", f"def test_{tc.slug}(api, seed, seeding):",
              f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""']
        o += _case(t, tc, tables, ops)
        o.append("")
    return "\n".join(o).rstrip("\n") + "\n"


def custom_file(cat: Catalog, ops: List[Operation], asil: str) -> str:
    o = _head(asil, "Test di unità generati per gli endpoint custom del contratto")
    o += ["from kybes_api import api, custom, seed, seeding  # noqa: F401 (fixture)", "", ""]
    by_id = {x.op_id: x for x in ops}
    for tc in cat.for_table(API, "api"):
        op = by_id[tc.args["operation"]]
        inp = tc.args["input"]
        path = op.path
        for p in op.params:
            if p.loc == "path":
                path = path.replace("{" + p.name + "}", _qstr(inp["path"][p.name]))
        o += ["", f"def test_{tc.slug}(api, custom):", f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""',
              f"    query = {inp['query']!r}", f"    r = api({op.method.upper()!r}, {path!r}, {inp['body']!r}, query=query)"]
        if tc.kind == "api_custom":
            o += [f"    assert r.status == {op.status}, r.body", "    call = custom.calls[-1]",
                  f"    assert call.operation == {op.op_id!r}", f"    assert call.path == {inp['path']!r}",
                  f"    assert call.query == query", f"    assert call.body == {inp['body']!r}"]
        else:
            o += [f"    assert r.status == 400 and r.body['error']['fields'] == {{{tc.args['field']!r}: 'obbligatorio'}}",
                  "    assert custom.calls == []"]
        o.append("")
    return "\n".join(o).rstrip("\n") + "\n"


def _qstr(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def api_module(tables: Dict[str, Table], ops: List[Operation], opts: Dict) -> str:
    api_import = opts.get("api_dir", "api").rsplit("/", 1)[-1]
    ctrl_import = opts.get("controller_dir", "controllers").rsplit("/", 1)[-1]
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    scopes = sorted({s for o in ops for s in o.scopes})
    fx = (["session_factory", "isolation_levels"] if sql else []) + (["mongo_client", "mongo_db"] if mongo else [])
    data = []
    if sql:
        data.append("session_factory=session_factory, levels=isolation_levels")
    if mongo:
        data.append("mongo_client=mongo_client, mongo_database=mongo_db.name")
    seeding = []
    if sql and mongo:
        seeding = ["# le collection MongoDB si inseriscono con la sessione MongoDB, le tabelle SQL con una sessione confermata"]
    o = [header(L, "kit").rstrip("\n") + "\n# ruff: noqa",
         '"""Fixture dei test delle API: build_api con i dati dei test, identità di prova, seed confermato, metodi custom finti."""',
         "import contextlib", "import json", "from datetime import date, datetime", "from typing import Any", "", "import pytest", "",
         f"from {api_import}.generated import ApiRequest, Identity, build_api", f"from {ctrl_import}.generated._data import ApiData", f"from {ctrl_import}.generated._convert import datetime_text",
         "from model.generated import bind_tenant", "from kybes_builders import TENANT_A", "",
         f"SCOPES = frozenset({scopes!r})", "ME = Identity(subject='kybes-test', tenant=str(TENANT_A), scopes=SCOPES)", "", "",
         "def qv(v: Any) -> Any:", '    """Valore del modello come testo di un parametro di query."""',
         "    if isinstance(v, list):", "        return [qv(x) for x in v]", "    if isinstance(v, bool):", "        return 'true' if v else 'false'",
         "    if isinstance(v, datetime):", "        return datetime_text(v)", "    if isinstance(v, date):", "        return v.isoformat()",
         "    return str(v)", "", "",
         "class Recorder:", '    """Implementazione finta dei metodi custom: registra le chiamate e restituisce l\'operazione."""', "",
         "    def __init__(self) -> None:", "        self.calls = []", "",
         "    def __getattr__(self, name: str) -> Any:", "        if name.startswith('__'):", "            raise AttributeError(name)", "",
         "        def method(call):", "            self.calls.append(call)", "            return {'operation': call.operation}", "        return method", "", "",
         "@pytest.fixture", "def custom():", "    return Recorder()", "", "",
         "@pytest.fixture", f"def api({', '.join(fx + ['custom'])}):",
         f"    built = build_api(ApiData({', '.join(data)}), custom)", "",
         "    def call(method, path, body=None, query=None, identity=ME, headers=None, raw=None):",
         "        q = {k: (qv(v) if isinstance(v, list) else [qv(v)]) for k, v in (query or {}).items()}",
         "        payload = raw if raw is not None else (None if body is None else json.dumps(body).encode('utf-8'))",
         "        hs = {'content-type': 'application/json', **(headers or {})}",
         "        return built.handle(ApiRequest(method, path, q, hs, payload, identity))", "    return call", "", ""]
    if sql:
        o += ["@pytest.fixture", f"def seeding(session_factory{', mongo_session' if mongo else ''}):",
              '    """Sessione per i dati di partenza, confermata alla fine del blocco (le API la vedono)."""', "",
              "    @contextlib.contextmanager", "    def run():", "        with session_factory(expire_on_commit=False) as s:",
              "            bind_tenant(s, TENANT_A)", "            yield s", "            s.commit()", "    return run", "", "",
              "@pytest.fixture", "def seed(seeding):", "    def run(build):", "        with seeding() as s:", "            return build(s)", "    return run", ""]
    else:
        o += ["@pytest.fixture", "def seeding(mongo_session):", '    """Le collection MongoDB scrivono subito: la sessione MongoDB di prova basta."""', "",
              "    @contextlib.contextmanager", "    def run():", "        yield mongo_session", "    return run", "", "",
              "@pytest.fixture", "def seed(mongo_session):", "    return lambda build: build(mongo_session)", ""]
    if sql and mongo:
        o += ["", "@pytest.fixture", "def seeding_mongo(mongo_session):", "    @contextlib.contextmanager", "    def run():", "        yield mongo_session",
              "    return run", "", "", "@pytest.fixture", "def seed_mongo(mongo_session):", "    return lambda build: build(mongo_session)", ""]
    return "\n".join(o).rstrip("\n") + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> Dict[str, str]:
    tp._TABLES.clear()
    tp._TABLES.update(tables)
    files = {"generated/kybes_api.py": api_module(tables, ops, opts)}
    for n, t in tables.items():
        if any(o.table == n for o in ops):
            files[f"generated/test_api_{snake(n)}.py"] = table_file(t, cat, tables, ops, asil, opts)
    if any(o.kind == "custom" for o in ops):
        top = max((table_asil(t, asil) for t in tables.values()), default=asil)
        files["generated/test_api_custom.py"] = custom_file(cat, ops, top)
    files["generated/test_api_runtime.py"] = runtime_file(cat, tables, ops, asil, opts)
    return files


def runtime_file(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> str:
    import runtime_api_python_tests as rtt
    return rtt.render(cat, tables, ops, asil, opts)
