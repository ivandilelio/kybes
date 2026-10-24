"""Rende i casi di test delle API (scope "api") in JUnit 5 per il pacchetto Java del modello.

Stessa struttura dei test Python e TypeScript: Api.handle con richieste come quelle degli adattatori, dati di partenza
con i builder del modello. Per le tabelle SQL i dati sono confermati (commit) prima di ogni chiamata, perché l'API legge
e scrive con i propri EntityManager; le collection MongoDB scrivono subito.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List

import api_plan
import test_java as tj
from api_plan import Operation, prop
from emit_api_java import api_package, controller_package
from naming import header, member, repo_class
from schema import Table, camel
from sqlonly import has_sql
from verification import API, API_RT, METHODS, RUNTIME, Catalog, TestCase, table_asil, ttl_column

L = "java"


def index(tables: Dict[str, Table], ops: List[Operation]) -> Dict[str, str]:
    out = {n: f"generated/{n}ApiTest.java" for n in tables if any(o.table == n for o in ops)}
    out[API_RT] = out[RUNTIME] = "generated/KybesApiRuntimeTest.java"
    if any(o.kind == "custom" for o in ops):
        out[API] = "generated/KybesApiCustomTest.java"
    return out


def _js(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _json_sample(t: Table, c) -> str:
    if c.name == ttl_column(t):
        return {"date": "LocalDate.now(ZoneOffset.UTC).plusDays(nextN()).toString()",
                "datetime": "Convert.datetimeText(OffsetDateTime.now(ZoneOffset.UTC).truncatedTo(java.time.temporal.ChronoUnit.HOURS).plusHours(nextN()))"}[c.type]
    if c.type == "string":
        return f"textValue(nextN(), {c.length})"
    if c.type == "decimal":
        return "String.valueOf(nextN())" if not c.scale else f'nextN() + ".{"5" * c.scale}"'
    return {"uuid": "UUID.randomUUID().toString()", "text": '"testo " + nextN()', "int": "(long) nextN()", "bigint": "String.valueOf(nextN())",
            "bool": "true", "date": "LocalDate.of(2026, 1, 1).plusDays(nextN()).toString()",
            "datetime": "Convert.datetimeText(OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC).plusHours(nextN()))",
            "json": 'Map.of("n", (long) nextN())'}[c.type]


def _json_new(c) -> str:
    if c.type == "string":
        return f'"u" + textValue(nextN(), {max(c.length - 1, 1)})'
    if c.type == "decimal":
        return "String.valueOf(nextN() + 500)" if not c.scale else f'(nextN() + 500) + ".{"2" * c.scale}"'
    return {"text": '"testo aggiornato"', "int": "(long) (nextN() + 500)", "bigint": "String.valueOf(nextN() + 500)", "bool": "false"}[c.type]


def _jkey(pk, expr: str) -> str:
    """Chiave come compare nel JSON della risposta."""
    return f"Long.valueOf({expr})" if pk.type == "int" else (expr if pk.type == "string" else f"String.valueOf({expr})")


def _missing_json(pk) -> str:
    return {"uuid": '"00000000-0000-4000-8000-000000000999"', "int": '"987654321"', "bigint": '"987654321"', "string": '"kybes-non-esiste"'}[pk.type]


def _path(op: Operation, key_text: str) -> str:
    if "{id}" not in op.path:
        return _js(op.path)
    a, b = op.path.split("{id}")
    return f"{_js(a)} + {key_text} + {_js(b)}" if b else f"{_js(a)} + {key_text}"


def _body_fn(t: Table, tables: Dict[str, Table]) -> List[str]:
    o = ["", f"    /** Corpo valido per la creazione di {t.name}, con ogni chiave esterna verso un padre inserito prima. */",
         "    private Map<String, Object> body() {", "        Map<String, Object> out = new LinkedHashMap<>();"]
    for c in api_plan.writable_columns(t):
        rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
        if rel:
            tg = tables[rel.target]
            o.append(f'        out.put("{prop(c.name)}", {_jkey(tg.pk, f"build{rel.target}(em).get{_cap(member(L, tg.pk.name))}()")});')
            continue
        o.append(f'        out.put("{prop(c.name)}", {_json_sample(t, c)});')
    o += ["        return out;", "    }"]
    return o


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _setup(t: Table, q, tables) -> List[str]:
    setup = tj._query_case(t, TestCase("TC-X", t.name, [], "req", "query_match", "", "", {"query": q.name}), tables)
    cut = next(i for i, line in enumerate(setup) if "Repository(em)." in line)
    return setup[:cut]


def _qargs(q, skip: str = "") -> str:
    parts = []
    for c in q.where:
        if c.param and camel(c.param) != skip:
            parts += [_js(camel(c.param)), member(L, c.param)]
    return f"q({', '.join(parts)})"


def _case(t: Table, tc: TestCase, tables: Dict[str, Table], ops: List[Operation]) -> List[str]:
    n, k = t.name, tc.kind
    base = "/" + t.api.path
    B = _js(base)
    pkp = _js(prop(t.pk.name))
    pkget = f"get{_cap(member(L, t.pk.name))}()"
    key = _jkey(t.pk, f"e.{pkget}")
    ktext = f"String.valueOf(e.{pkget})"
    op = next((o for o in ops if o.op_id == tc.args.get("operation")), None)
    if k == "api_list":
        m = t.pagination.max_limit
        return [f"        {n} e = build{n}(em);", f'        Result r = call("GET", {B}, null, q("limit", {m}), ME);',
                "        assertEquals(200, r.status(), r.text());", f'        assertEquals({m}L, r.map().get("limit"));',
                f"        assertTrue(r.items().stream().anyMatch(x -> Objects.equals(x.get({pkp}), {key})));"]
    if k == "api_list_params":
        return [f'        Result r = call("GET", {B}, null, q("limit", 0), ME);', "        assertEquals(400, r.status());",
                '        assertEquals(Map.of("limit", "valore minimo 1"), r.fields());',
                f'        r = call("GET", {B}, null, q("kybesSconosciuto", 1), ME);', "        assertEquals(400, r.status());",
                '        assertEquals(Map.of("kybesSconosciuto", "parametro sconosciuto"), r.fields());']
    if k == "api_list_expand":
        rels = [next(x for x in t.relations if x.name == rn) for rn in tc.args["relations"]]
        exp_val = tc.args["expand"]
        o = []
        seen_targets = {}
        setter_parts = []
        for rel in rels:
            tg = tables[rel.target]
            fkset = f"set{_cap(member(L, rel.foreign_key))}"
            tget = f"get{_cap(member(L, tg.pk.name))}()"
            if rel.target == n:
                var = "selfP"
            elif rel.target not in seen_targets:
                var = f"p{rel.target}"
                o.append(f"        {rel.target} {var} = build{rel.target}(em);")
                seen_targets[rel.target] = var
            else:
                var = seen_targets[rel.target]
            setter_parts.append(f"x.{fkset}({var}.{tget})")
        if any(r.target == n for r in rels):
            o.append(f"        {n} selfP = build{n}(em);")
        lam = "; ".join(setter_parts)
        o.append(f"        {n} e = build{n}(em, x -> {{ {lam}; }});")
        o += [f'        Result r = call("GET", {B}, null, q("expand", {_js(exp_val)}, "limit", {t.pagination.max_limit}), ME);',
              "        assertEquals(200, r.status(), r.text());",
              f"        var hit = r.items().stream().filter(x -> Objects.equals(x.get({pkp}), {key})).findFirst().orElseThrow();"]
        for rel in rels:
            o.append(f"        assertNotNull(hit.get({_js(prop(rel.name))}), \"relazione espansa mancante\");")
        return o
    if k == "api_list_expand_null":
        nullable_rels = [next(x for x in t.relations if x.name == rn) for rn in tc.args["nullable_relations"]]
        exp_val = tc.args["expand"]
        o = [f"        {n} e = build{n}(em);"]
        o += [f'        Result r = call("GET", {B}, null, q("expand", {_js(exp_val)}, "limit", {t.pagination.max_limit}), ME);',
              "        assertEquals(200, r.status(), r.text());",
              f"        var hit = r.items().stream().filter(x -> Objects.equals(x.get({pkp}), {key})).findFirst().orElseThrow();"]
        for rel in nullable_rels:
            o.append(f"        assertNull(hit.get({_js(prop(rel.name))}), \"relazione nullable senza padre deve tornare null\");")
        return o
    if k == "api_list_expand_bad":
        return [f'        Result r = call("GET", {B}, null, q("expand", "kybesNonEsiste"), ME);',
                "        assertEquals(400, r.status());",
                '        assertTrue(r.error().get("code").toString().contains("invalid expand"));']
    if k == "api_get":
        return [f"        {n} e = build{n}(em);", f'        Result r = call("GET", {B} + "/" + {ktext}, null, q(), ME);',
                "        assertEquals(200, r.status(), r.text());",
                f"        assertEquals(json({n}Api.toJson(new {repo_class(L, n)}(em).getById(e.{pkget}).orElseThrow())), r.body());"]
    if k == "api_get_missing":
        return [f'        Result r = call("GET", {B} + "/" + {_missing_json(t.pk)}, null, q(), ME);', "        assertEquals(404, r.status());",
                '        assertEquals("RECORD_NOT_FOUND", r.error().get("code"));']
    if k == "api_get_badid":
        return [f'        Result r = call("GET", {_js(base + "/kybes-non-valido")}, null, q(), ME);', "        assertEquals(400, r.status());",
                f'        assertEquals(Map.of("id", {_js(tc.args["rule"])}), r.fields());']
    if k == "api_create":
        return ["        Map<String, Object> sent = body();", f'        Result r = call("POST", {B}, sent, q(), ME);',
                "        assertEquals(201, r.status(), r.text());", f'        assertEquals({B} + "/" + r.map().get({pkp}), r.headers().get("location"));',
                "        for (Map.Entry<String, Object> x : sent.entrySet()) assertEquals(x.getValue(), r.map().get(x.getKey()), x.getKey());"]
    if k == "api_create_required":
        p = _js(prop(tc.args["column"]))
        return ["        Map<String, Object> sent = body();", f"        sent.remove({p});", f'        Result r = call("POST", {B}, sent, q(), ME);',
                "        assertEquals(400, r.status());", f'        assertEquals(Map.of({p}, "obbligatorio"), r.fields());']
    if k == "api_create_extra":
        return ["        Map<String, Object> sent = body();", '        sent.put("kybesSconosciuto", 1);', f'        Result r = call("POST", {B}, sent, q(), ME);',
                "        assertEquals(400, r.status());", '        assertEquals(Map.of("kybesSconosciuto", "non ammesso"), r.fields());']
    if k == "api_create_type":
        c = t.col(tc.args["column"])
        p = _js(prop(c.name))
        wrong = '"x"' if c.type in ("int", "bool") else "12345"
        return ["        Map<String, Object> sent = body();", f"        sent.put({p}, {wrong});", f'        Result r = call("POST", {B}, sent, q(), ME);',
                "        assertEquals(400, r.status());", f"        assertEquals(Map.of({p}, {_js(tc.args['rule'])}), r.fields());"]
    if k == "api_create_duplicate":
        p = _js(prop(tc.args["column"]))
        return ["        Map<String, Object> first = body();", f'        assertEquals(201, call("POST", {B}, first, q(), ME).status());',
                "        Map<String, Object> second = body();", f"        second.put({p}, first.get({p}));", f'        Result r = call("POST", {B}, second, q(), ME);',
                "        assertEquals(409, r.status(), r.text());", '        assertTrue(List.of("CONSTRAINT", "DUPLICATE").contains(r.error().get("code")));']
    if k == "api_update":
        if "column" in tc.args:
            c = t.col(tc.args["column"])
            p = _js(prop(c.name))
            return [f"        {n} e = build{n}(em);", f"        Object value = {_json_new(c)};",
                    f'        Result r = call("PATCH", {B} + "/" + {ktext}, Map.of({p}, value), q(), ME);',
                    "        assertEquals(200, r.status(), r.text());", f"        assertEquals(value, r.map().get({p}));",
                    f"        assertEquals({key}, r.map().get({pkp}));",
                    f'        r = call("PATCH", {B} + "/" + {ktext}, Map.of(), q(), ME);', "        assertEquals(200, r.status(), r.text());",
                    f"        assertEquals(value, r.map().get({p}), \"un corpo vuoto non cambia i campi\");"]
        return [f"        {n} e = build{n}(em);", f'        Result r = call("PATCH", {B} + "/" + {ktext}, Map.of(), q(), ME);',
                "        assertEquals(200, r.status(), r.text());", f"        assertEquals({key}, r.map().get({pkp}));"]
    if k == "api_update_missing":
        return [f'        Result r = call("PATCH", {B} + "/" + {_missing_json(t.pk)}, Map.of(), q(), ME);', "        assertEquals(404, r.status());",
                '        assertEquals("RECORD_NOT_FOUND", r.error().get("code"));']
    if k == "api_update_key":
        return [f"        {n} e = build{n}(em);", f'        Result r = call("PATCH", {B} + "/" + {ktext}, Map.of({pkp}, {key}), q(), ME);',
                "        assertEquals(400, r.status());", f'        assertEquals(Map.of({pkp}, "non ammesso"), r.fields());']
    if k == "api_delete":
        has_get = any(o.table == n and o.kind == "get" for o in ops)
        return [f"        {n} e = build{n}(em);", f'        Result r = call("DELETE", {B} + "/" + {ktext}, null, q(), ME);',
                "        assertEquals(204, r.status());", "        assertNull(r.body());",
                f'        assertEquals(404, call({_js("GET" if has_get else "DELETE")}, {B} + "/" + {ktext}, null, q(), ME).status());']
    if k == "api_delete_missing":
        return [f'        Result r = call("DELETE", {B} + "/" + {_missing_json(t.pk)}, null, q(), ME);', "        assertEquals(404, r.status());",
                '        assertEquals("RECORD_NOT_FOUND", r.error().get("code"));']
    if k == "api_query":
        q = next(x for x in t.queries if x.name == op.arg)
        o = _setup(t, q, tables)
        o += [f'        Result r = call("GET", {_js(op.path)}, null, {_qargs(q)}, ME);', "        assertEquals(200, r.status(), r.text());"]
        if q.returns == "page":
            o.append(f"        assertTrue(r.items().stream().anyMatch(x -> Objects.equals(x.get({pkp}), {key})));")
        elif q.returns == "list":
            o.append(f"        assertTrue(r.list().stream().anyMatch(x -> Objects.equals(x.get({pkp}), {key})));")
        else:
            o += [f"        assertEquals({key}, r.map().get({pkp}));", f"        new {repo_class(L, n)}(em).delete(e.{pkget});",
                  f'        r = call("GET", {_js(op.path)}, null, {_qargs(q)}, ME);', "        assertEquals(404, r.status());"]
        return o
    if k == "api_query_params":
        q = next(x for x in t.queries if x.name == op.arg)
        return _setup(t, q, tables) + [f'        Result r = call("GET", {_js(op.path)}, null, {_qargs(q, tc.args["param"])}, ME);',
                                       "        assertEquals(400, r.status());",
                                       f'        assertEquals(Map.of({_js(tc.args["param"])}, "obbligatorio"), r.fields());']
    if k == "api_rel":
        r = next(x for x in t.relations if x.name == tc.args["relation"])
        tg = tables[r.target]
        tget = f"get{_cap(member(L, tg.pk.name))}()"
        fkset = f"set{_cap(member(L, r.foreign_key))}"
        if r.kind == "many_to_one":
            return [f"        {r.target} p = build{r.target}(em);", f"        {n} e = build{n}(em, x -> x.{fkset}(p.{tget}));",
                    f'        Result r = call("GET", {_path(op, ktext)}, null, q(), ME);', "        assertEquals(200, r.status(), r.text());",
                    f"        assertEquals({_jkey(tg.pk, 'p.' + tget)}, r.map().get({_js(prop(tg.pk.name))}));"]
        return [f"        {n} e = build{n}(em);", f"        {r.target} c = build{r.target}(em, x -> x.{fkset}(e.{pkget}));",
                f'        Result r = call("GET", {_path(op, ktext)}, null, q("limit", {tg.pagination.max_limit}), ME);',
                "        assertEquals(200, r.status(), r.text());",
                f"        assertTrue(r.items().stream().anyMatch(x -> Objects.equals(x.get({_js(prop(tg.pk.name))}), {_jkey(tg.pk, 'c.' + tget)})));"]
    if k == "api_rel_missing":
        return [f'        Result r = call("GET", {_path(op, _missing_json(t.pk))}, null, q(), ME);', "        assertEquals(404, r.status());",
                '        assertEquals("RECORD_NOT_FOUND", r.error().get("code"));']
    if k in ("api_auth", "api_scope", "api_tenant_missing"):
        ident = {"api_auth": "null", "api_scope": "identity(String.valueOf(TENANT_A), List.of())",
                 "api_tenant_missing": "identity(null, SCOPES)"}[k]
        want = {"api_auth": (401, "IDENTITY_REQUIRED"), "api_scope": (403, "SCOPE_REQUIRED"), "api_tenant_missing": (403, "TENANT_REQUIRED")}[k]
        o, body, query = [], "null", "q()"
        if op.kind == "create":
            o.append("        Map<String, Object> sent = body();")
            body = "sent"
        elif op.kind == "update":
            body = "Map.of()"
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            o += _setup(t, q, tables)
            query = _qargs(q)
        elif op.kind == "rel":
            o.append(f"        {n} e = build{n}(em);")
        key_expr = ktext if op.kind == "rel" else _missing_json(t.pk)
        return o + [f"        Result r = call({_js(op.method.upper())}, {_path(op, key_expr)}, {body}, {query}, {ident});",
                    f"        assertEquals({want[0]}, r.status(), r.text());", f'        assertEquals("{want[1]}", r.error().get("code"));']
    if k == "api_tenant_other":
        return [f"        {n} e = build{n}(em);",
                f'        Result r = call("GET", {B} + "/" + {ktext}, null, q(), identity(String.valueOf(TENANT_B), SCOPES));',
                "        assertEquals(404, r.status());"]
    raise ValueError(k)


def _head(pkg: str, api_pkg: str, ctrl_pkg: str, extra: List[str]) -> List[str]:
    return [f"package {pkg}.generated;", "", "import static org.junit.jupiter.api.Assertions.*;",
            f"import static {pkg}.generated.KybesApiSupport.*;", f"import static {pkg}.generated.KybesBuilders.*;", ""] + sorted(
        extra + [f"import {api_pkg}.generated.Api;", f"import {ctrl_pkg}.generated.ApiData;", f"import {api_pkg}.generated.KybesApi;",
                 "import java.math.BigDecimal;", "import java.time.LocalDate;", "import java.time.OffsetDateTime;", "import java.time.ZoneOffset;",
                 "import java.util.*;", "import org.junit.jupiter.api.AfterEach;", "import org.junit.jupiter.api.BeforeEach;",
                 "import org.junit.jupiter.api.DisplayName;", "import org.junit.jupiter.api.Test;"])


def table_file(t: Table, cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, pkg: str) -> str:
    n = t.name
    api_pkg = api_package(pkg)
    ctrl_pkg = controller_package(pkg)
    custom = any(o.kind == "custom" for o in ops)
    extra = [f"import {ctrl_pkg}.generated.{n}Api;", f"import {ctrl_pkg}.generated.Convert;", f"import {api_pkg}.generated.Identity;",
             f"import {pkg}.{repo_class(L, n)};"]
    em_t = "MongoSession" if t.mongo else "EntityManager"
    if not t.mongo:
        extra.append("import jakarta.persistence.EntityManager;")
    rec = ", new Recorder()" if custom else ""
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n")] + _head(pkg, api_pkg, ctrl_pkg, extra) + [
        "", f"/** Test di unità generati per le API di {n} (ASIL {table_asil(t, asil)}). Specifica: docs/generated/verification/{n}.md. */",
        f"class {n}ApiTest {{", "", f"    private {em_t} em;", "    private Api api;", "", "    @BeforeEach", "    void open() {"]
    if t.mongo:
        o += ["        em = KybesMongo.open();", f"        api = KybesApi.build(new ApiData().mongo(KybesMongo.client(), em.db().getName()){rec});",
              "    }", "", "    @AfterEach", "    void close() {", "        KybesMongo.close(em);", "    }", "",
              "    private Result call(String method, String path, Object body, Map<String, Object> query, Identity who) {",
              "        return KybesApiSupport.call(api, method, path, body, query, who);", "    }"]
    else:
        o += ["        em = openCommitted();", f"        api = KybesApi.build(new ApiData().emf(KybesDb.emf()){rec});", "    }", "",
              "    @AfterEach", "    void close() {", "        KybesDb.close(em);", "    }", "",
              "    /** Conferma i dati di partenza (l'API li legge con i propri EntityManager) e chiama l'API. */",
              "    private Result call(String method, String path, Object body, Map<String, Object> query, Identity who) {",
              "        commit(em);", "        return KybesApiSupport.call(api, method, path, body, query, who);", "    }"]
    o += _body_fn(t, tables)
    for tc in cat.for_table(n, "api"):
        title = tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title
        o += ["", "    @Test", f"    @DisplayName({_js(title)})", f"    void {_mname(tc.id)}() {{", f"        // atteso: {tc.expected}"]
        o += _case(t, tc, tables, ops)
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def _jv(v) -> str:
    """Valore JSON (da api_plan.sample) come espressione Java confrontabile con il JSON letto (interi Long)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}L"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return _js(v)
    if isinstance(v, list):
        return "List.of(" + ", ".join(_jv(x) for x in v) + ")"
    return "Map.of(" + ", ".join(f"{_js(k)}, {_jv(x)}" for k, x in v.items()) + ")"


def _mname(tc_id: str) -> str:
    return re.sub(r"\W", "_", tc_id.lower())


def _qstr(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def custom_file(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], pkg: str) -> str:
    api_pkg = api_package(pkg)
    ctrl_pkg = controller_package(pkg)
    o = [header(L, "schemas/openapi.yaml").rstrip("\n")] + _head(pkg, api_pkg, ctrl_pkg, [f"import {api_pkg}.generated.Call;"]) + [
        "", "/** Test di unità generati per gli endpoint custom del contratto. */", "class KybesApiCustomTest {"]
    by_id = {x.op_id: x for x in ops}
    for tc in cat.for_table(API, "api"):
        op = by_id[tc.args["operation"]]
        inp = tc.args["input"]
        path = op.path
        for p in op.params:
            if p.loc == "path":
                path = path.replace("{" + p.name + "}", _qstr(inp["path"][p.name]))
        title = tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title
        qparts = []
        for name, v in inp["query"].items():
            qparts += [_js(name), _jv(v)]
        o += ["", "    @Test", f"    @DisplayName({_js(title)})", f"    void {_mname(tc.id)}() {{",
              "        Recorder custom = new Recorder();", "        Api api = KybesApi.build(new ApiData(), custom);",
              f"        Map<String, Object> query = q({', '.join(qparts)});",
              f"        Result r = KybesApiSupport.call(api, {_js(op.method.upper())}, {_js(path)}, {_jv(inp['body'])}, query, ME);"]
        if tc.kind == "api_custom":
            o += [f"        assertEquals({op.status}, r.status(), r.text());", "        Call call = custom.calls.get(custom.calls.size() - 1);",
                  f'        assertEquals("{op.op_id}", call.operation());', f"        assertEquals({_jv(inp['path'])}, json(call.path()));",
                  "        assertEquals(json(query), json(call.query()));", f"        assertEquals(json({_jv(inp['body'])}), json(call.body()));"]
        else:
            o += ["        assertEquals(400, r.status());", f'        assertEquals(Map.of({_js(tc.args["field"])}, "obbligatorio"), r.fields());',
                  "        assertTrue(custom.calls.isEmpty());"]
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def support_file(tables: Dict[str, Table], ops: List[Operation], pkg: str) -> str:
    api_pkg = api_package(pkg)
    ctrl_pkg = controller_package(pkg)
    sql = has_sql(tables)
    scopes = sorted({s for o in ops for s in o.scopes})
    custom = [o for o in ops if o.kind == "custom"]
    imports = [f"import {api_pkg}.generated.{x};" for x in ("Api", "ApiRequest", "ApiResponse", "Identity", "Json")]
    imports.append(f"import {ctrl_pkg}.generated.Convert;")
    if custom:
        imports += [f"import {api_pkg}.generated.Call;", f"import {api_pkg}.generated.Operations;"]
    imports += ["import java.math.BigDecimal;", "import java.nio.charset.StandardCharsets;", "import java.time.OffsetDateTime;",
                "import java.util.ArrayList;", "import java.util.Collection;", "import java.util.LinkedHashMap;", "import java.util.LinkedHashSet;",
                "import java.util.List;", "import java.util.Map;"]
    if sql:
        imports.append("import jakarta.persistence.EntityManager;")
    o = [header(L, "kit").rstrip("\n"), f"package {pkg}.generated;", ""] + sorted(imports) + [
        "", "/** Supporto dei test delle API: identità di prova, chiamate all'Api con il JSON come lo vede un client, metodi custom finti. */",
        "public final class KybesApiSupport {", "",
        f"    public static final List<String> SCOPES = List.of({', '.join(_js(s) for s in scopes)});",
        "    public static final Identity ME = identity(String.valueOf(KybesBuilders.TENANT_A), SCOPES);", "",
        "    private KybesApiSupport() {", "    }", "",
        "    /** Identità di prova: soggetto, tenant e scope indicati. */",
        "    public static Identity identity(String tenant, List<String> scopes) {",
        '        return new Identity("kybes-test", tenant, new LinkedHashSet<>(scopes), Map.of());', "    }", "",
        "    /** Valore del modello come testo di un parametro di query. */",
        "    public static Object qv(Object v) {",
        "        if (v instanceof Collection<?> c) {", "            List<String> out = new ArrayList<>();",
        "            for (Object x : c) out.add((String) qv(x));", "            return out;", "        }",
        "        if (v instanceof OffsetDateTime d) return Convert.datetimeText(d);",
        "        if (v instanceof BigDecimal d) return d.toPlainString();", "        return String.valueOf(v);", "    }", "",
        "    /** Mappa ordinata da coppie chiave, valore. */", "    public static Map<String, Object> q(Object... kv) {",
        "        Map<String, Object> out = new LinkedHashMap<>();", "        for (int i = 0; i < kv.length; i += 2) out.put((String) kv[i], kv[i + 1]);",
        "        return out;", "    }", "",
        "    /** Valore normalizzato come JSON letto (interi Long, oggetti LinkedHashMap). */",
        "    public static Object json(Object v) {", "        return Json.parse(Json.write(v));", "    }", "",
        "    /** Risposta come la vede un client: stato, JSON letto (null senza corpo), header. */",
        "    public record Result(int status, Object body, String text, Map<String, String> headers) {", "",
        "        @SuppressWarnings(\"unchecked\")", "        public Map<String, Object> map() {", "            return (Map<String, Object>) body;", "        }", "",
        "        @SuppressWarnings(\"unchecked\")", "        public List<Map<String, Object>> list() {", "            return (List<Map<String, Object>>) body;", "        }", "",
        "        @SuppressWarnings(\"unchecked\")", "        public List<Map<String, Object>> items() {",
        '            return (List<Map<String, Object>>) map().get("items");', "        }", "",
        "        @SuppressWarnings(\"unchecked\")", "        public Map<String, Object> error() {",
        '            return (Map<String, Object>) map().get("error");', "        }", "",
        "        public Object fields() {", '            return error().get("fields");', "        }", "    }", "",
        "    /** Api.handle con il corpo serializzato e i parametri come testo. */",
        "    public static Result call(Api api, String method, String path, Object body, Map<String, Object> query, Identity who) {",
        "        Map<String, List<String>> q = new LinkedHashMap<>();", "        for (Map.Entry<String, Object> e : query.entrySet()) {",
        "            Object v = qv(e.getValue());", "            List<String> values = new ArrayList<>();",
        "            if (v instanceof List<?> l) for (Object x : l) values.add(String.valueOf(x));", "            else values.add(String.valueOf(v));",
        "            q.put(e.getKey(), values);", "        }",
        "        byte[] payload = body == null ? null : Json.write(body).getBytes(StandardCharsets.UTF_8);",
        '        Map<String, String> headers = new LinkedHashMap<>(Map.of("content-type", "application/json"));',
        "        ApiResponse resp = api.handle(new ApiRequest(method, path, q, headers, payload, who));", "        String text = resp.text();",
        "        return new Result(resp.status(), text.isEmpty() ? null : Json.parse(text), text, resp.headers());", "    }"]
    if sql:
        o += ["", "    /** Tabelle vuote, EntityManager con TENANT_A legato e transazione aperta; commit(em) rende visibili i dati all'API. */",
              "    public static EntityManager openCommitted() {", "        KybesDb.reset();",
              "        EntityManager em = KybesDb.emf().createEntityManager();", "        Tenancy.bind(em, KybesBuilders.TENANT_A);",
              "        em.getTransaction().begin();", "        return em;", "    }", "",
              "    /** Conferma la transazione dei test e ne apre un'altra. */", "    public static void commit(EntityManager em) {",
              "        em.getTransaction().commit();", "        em.getTransaction().begin();", "    }"]
    if custom:
        o += ["", "    /** Implementazione finta dei metodi custom: registra le chiamate e restituisce l'operazione. */",
              "    public static final class Recorder implements Operations {", "        public final List<Call> calls = new ArrayList<>();", "",
              "        private Object record(Call call) {", "            calls.add(call);", '            return Map.of("operation", call.operation());', "        }"]
        for x in custom:
            o += ["", "        @Override", f"        public Object {x.op_id}(Call call) {{", "            return record(call);", "        }"]
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> Dict[str, str]:
    import runtime_api_java_tests as rtt
    pkg = opts["package"]
    files = {"generated/KybesApiSupport.java": support_file(tables, ops, pkg)}
    for n, t in tables.items():
        if any(o.table == n for o in ops):
            files[f"generated/{n}ApiTest.java"] = table_file(t, cat, tables, ops, asil, pkg)
    if any(o.kind == "custom" for o in ops):
        files["generated/KybesApiCustomTest.java"] = custom_file(cat, tables, ops, pkg)
    files["generated/KybesApiRuntimeTest.java"] = rtt.render(cat, tables, ops, asil, pkg, api_package(pkg), controller_package(pkg))
    return files
