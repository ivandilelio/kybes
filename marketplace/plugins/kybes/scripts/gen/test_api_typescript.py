"""Rende i casi di test delle API (scope "api") in node:test per il pacchetto TypeScript del modello.

Stessa struttura dei test Python: Api.handle con richieste come quelle degli adattatori, dati di partenza con i builder
del modello (l'EntityManager dei test scrive subito; la sessione MongoDB anche).
"""
from __future__ import annotations

import json
from typing import Dict, List

import api_plan
import test_typescript as tt
from api_plan import Operation, prop
from naming import header, member, repo_class
from schema import Table, camel
from sqlonly import has_sql
from verification import API, API_RT, METHODS, RUNTIME, Catalog, TestCase, table_asil, ttl_column

L = "typescript"


def _ts_relpath(from_dir: str, to_dir: str) -> str:
    parts_from = from_dir.split("/")
    parts_to = to_dir.split("/")
    common = 0
    for a, b in zip(parts_from, parts_to):
        if a != b:
            break
        common += 1
    ups = len(parts_from) - common
    return "/".join([".."] * ups + parts_to[common:])


def index(tables: Dict[str, Table], ops: List[Operation]) -> Dict[str, str]:
    out = {n: f"generated/{n}.api.test.ts" for n in tables if any(o.table == n for o in ops)}
    out[API_RT] = out[RUNTIME] = "generated/kybes_api_runtime.test.ts"
    if any(o.kind == "custom" for o in ops):
        out[API] = "generated/kybes_api_custom.test.ts"
    return out


def _json_sample(t: Table, c) -> str:
    if c.name == ttl_column(t):
        return {"date": "new Date(Date.now() + nextN() * 86400000).toISOString().slice(0, 10)",
                "datetime": "new Date((Math.floor(Date.now() / 3600000) + nextN()) * 3600000).toISOString()"}[c.type]
    if c.type == "string":
        return f"textValue(nextN(), {c.length})"
    if c.type == "decimal":
        return "String(nextN())" if not c.scale else f"`${{nextN()}}.{'5' * c.scale}`"
    return {"uuid": "randomUUID()", "text": "`testo ${nextN()}`", "int": "nextN()", "bigint": "String(nextN())", "bool": "true",
            "date": "dayValue(nextN())", "datetime": "new Date(Date.UTC(2026, 0, 1) + nextN() * 3600000).toISOString()",
            "json": "{ n: nextN() }"}[c.type]


def _json_new(c) -> str:
    if c.type == "string":
        return f'"u" + textValue(nextN(), {max(c.length - 1, 1)})'
    if c.type == "decimal":
        return "String(nextN() + 500)" if not c.scale else f"`${{nextN() + 500}}.{'2' * c.scale}`"
    return {"text": '"testo aggiornato"', "int": "nextN() + 500", "bigint": "String(nextN() + 500)", "bool": "false"}[c.type]


def _jkey(pk, expr: str) -> str:
    return f"String({expr}).toLowerCase()" if pk.type == "uuid" else (f"String({expr})" if pk.type == "bigint" else expr)


def _missing_json(pk) -> str:
    return {"uuid": '"00000000-0000-4000-8000-000000000999"', "int": "987654321", "bigint": '"987654321"', "string": '"kybes-non-esiste"'}[pk.type]


def _path(op: Operation, key: str) -> str:
    if "{id}" not in op.path:
        return json.dumps(op.path)
    a, b = op.path.split("{id}")
    return f"{json.dumps(a)} + String({key}) + {json.dumps(b)}"


def _body_fn(t: Table, tables: Dict[str, Table]) -> List[str]:
    em_t = "MongoSession" if t.mongo else "EntityManager"
    o = [f"/** Corpo valido per la creazione di {t.name}, con ogni chiave esterna verso un padre inserito prima. */",
         f"async function body(em: {em_t}): Promise<Record<string, any>> {{", "  const out: Record<string, any> = {};"]
    for c in api_plan.writable_columns(t):
        rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
        if rel:
            tg = tables[rel.target]
            o.append(f"  out.{prop(c.name)} = {_jkey(tg.pk, f'(await build{rel.target}(em)).{member(L, tg.pk.name)}')};")
            continue
        o.append(f"  out.{prop(c.name)} = {_json_sample(t, c)};")
    o += ["  return out;", "}", ""]
    return o


def _setup(t: Table, q, tables) -> List[str]:
    setup = tt._query_case(t, TestCase("TC-X", t.name, [], "req", "query_match", "", "", {"query": q.name}), tables)
    cut = next(i for i, line in enumerate(setup) if "Repository(em)." in line)
    return setup[:cut]


def _qargs(q, skip: str = "") -> str:
    parts = [f"{camel(c.param)}: qv({member(L, c.param)})" for c in q.where if c.param and camel(c.param) != skip]
    return "{ " + ", ".join(parts) + " }" if parts else "{}"


def _case(t: Table, tc: TestCase, tables: Dict[str, Table], ops: List[Operation]) -> List[str]:
    n, k = t.name, tc.kind
    base = "/" + t.api.path
    B = json.dumps(base)
    pkp = prop(t.pk.name)
    key = _jkey(t.pk, f"e.{member(L, t.pk.name)}")
    op = next((o for o in ops if o.op_id == tc.args.get("operation")), None)
    if k == "api_list":
        return [f"    const e = await build{n}(em);", f"    const r = await api(\"GET\", {B}, undefined, {{ limit: {t.pagination.max_limit} }});",
                "    const b = r.body as any;", "    assert.equal(r.status, 200, JSON.stringify(b));", f"    assert.equal(b.limit, {t.pagination.max_limit});",
                f"    assert.ok(b.items.some((x: any) => x.{pkp} === {key}));"]
    if k == "api_list_params":
        return [f"    let r = await api(\"GET\", {B}, undefined, {{ limit: 0 }});", "    assert.equal(r.status, 400);",
                '    assert.deepEqual((r.body as any).error.fields, { limit: "valore minimo 1" });',
                f"    r = await api(\"GET\", {B}, undefined, {{ kybesSconosciuto: 1 }});",
                '    assert.equal(r.status, 400);', '    assert.deepEqual((r.body as any).error.fields, { kybesSconosciuto: "parametro sconosciuto" });']
    if k == "api_get":
        return [f"    const e = await build{n}(em);", f"    const r = await api(\"GET\", {B} + \"/\" + String({key}));",
                "    assert.equal(r.status, 200, JSON.stringify(r.body));",
                f"    assert.deepEqual(r.body, toJson((await new {repo_class(L, n)}(em).getById(e.{member(L, t.pk.name)}))!));"]
    if k == "api_get_missing":
        return [f"    const r = await api(\"GET\", {B} + \"/\" + String({_missing_json(t.pk)}));", "    assert.equal(r.status, 404);",
                '    assert.equal((r.body as any).error.code, "RECORD_NOT_FOUND");']
    if k == "api_get_badid":
        return [f"    const r = await api(\"GET\", {json.dumps(base + '/kybes-non-valido')});", "    assert.equal(r.status, 400);",
                f"    assert.deepEqual((r.body as any).error.fields, {{ id: {json.dumps(tc.args['rule'])} }});"]
    if k == "api_create":
        return ["    const sent = await body(em);", f"    const r = await api(\"POST\", {B}, sent);", "    const b = r.body as any;",
                "    assert.equal(r.status, 201, JSON.stringify(b));", f"    assert.equal(r.headers.location, {B} + \"/\" + String(b.{pkp}));",
                "    for (const [name, value] of Object.entries(sent)) assert.deepEqual(b[name], value, name);"]
    if k == "api_create_required":
        p = prop(tc.args["column"])
        return ["    const sent = await body(em);", f"    delete sent.{p};", f"    const r = await api(\"POST\", {B}, sent);", "    assert.equal(r.status, 400);",
                f'    assert.deepEqual((r.body as any).error.fields, {{ {p}: "obbligatorio" }});']
    if k == "api_create_extra":
        return ["    const sent = await body(em);", "    sent.kybesSconosciuto = 1;", f"    const r = await api(\"POST\", {B}, sent);",
                "    assert.equal(r.status, 400);", '    assert.deepEqual((r.body as any).error.fields, { kybesSconosciuto: "non ammesso" });']
    if k == "api_create_type":
        c = t.col(tc.args["column"])
        p = prop(c.name)
        wrong = '"x"' if c.type in ("int", "bool") else "12345"
        return ["    const sent = await body(em);", f"    sent.{p} = {wrong};", f"    const r = await api(\"POST\", {B}, sent);", "    assert.equal(r.status, 400);",
                f"    assert.deepEqual((r.body as any).error.fields, {{ {p}: {json.dumps(tc.args['rule'])} }});"]
    if k == "api_create_duplicate":
        p = prop(tc.args["column"])
        return ["    const first = await body(em);", f"    assert.equal((await api(\"POST\", {B}, first)).status, 201);",
                "    const second = await body(em);", f"    second.{p} = first.{p};", f"    const r = await api(\"POST\", {B}, second);",
                "    assert.equal(r.status, 409, JSON.stringify(r.body));", '    assert.ok(["CONSTRAINT", "DUPLICATE"].includes((r.body as any).error.code));']
    if k == "api_update":
        if "column" in tc.args:
            c = t.col(tc.args["column"])
            p = prop(c.name)
            return [f"    const e = await build{n}(em);", f"    const value = {_json_new(c)};",
                    f"    const r = await api(\"PATCH\", {B} + \"/\" + String({key}), {{ {p}: value }});",
                    "    assert.equal(r.status, 200, JSON.stringify(r.body));", f"    assert.equal((r.body as any).{p}, value);",
                    f"    assert.equal((r.body as any).{pkp}, {key});"]
        return [f"    const e = await build{n}(em);", f"    const r = await api(\"PATCH\", {B} + \"/\" + String({key}), {{}});",
                "    assert.equal(r.status, 200, JSON.stringify(r.body));", f"    assert.equal((r.body as any).{pkp}, {key});"]
    if k == "api_update_missing":
        return [f"    const r = await api(\"PATCH\", {B} + \"/\" + String({_missing_json(t.pk)}), {{}});", "    assert.equal(r.status, 404);",
                '    assert.equal((r.body as any).error.code, "RECORD_NOT_FOUND");']
    if k == "api_update_key":
        return [f"    const e = await build{n}(em);", f"    const r = await api(\"PATCH\", {B} + \"/\" + String({key}), {{ {pkp}: {key} }});",
                "    assert.equal(r.status, 400);", f'    assert.deepEqual((r.body as any).error.fields, {{ {pkp}: "non ammesso" }});']
    if k == "api_delete":
        has_get = any(o.table == n and o.kind == "get" for o in ops)
        return [f"    const e = await build{n}(em);", f"    const r = await api(\"DELETE\", {B} + \"/\" + String({key}));",
                "    assert.equal(r.status, 204);", "    assert.equal(r.body, undefined);",
                f"    assert.equal((await api({json.dumps('GET' if has_get else 'DELETE')}, {B} + \"/\" + String({key}))).status, 404);"]
    if k == "api_delete_missing":
        return [f"    const r = await api(\"DELETE\", {B} + \"/\" + String({_missing_json(t.pk)}));", "    assert.equal(r.status, 404);",
                '    assert.equal((r.body as any).error.code, "RECORD_NOT_FOUND");']
    if k == "api_query":
        q = next(x for x in t.queries if x.name == op.arg)
        o = _setup(t, q, tables)
        o += [f"    let r = await api(\"GET\", {json.dumps(op.path)}, undefined, {_qargs(q)});", "    assert.equal(r.status, 200, JSON.stringify(r.body));"]
        if q.returns == "page":
            o.append(f"    assert.ok((r.body as any).items.some((x: any) => x.{pkp} === {key}));")
        elif q.returns == "list":
            o.append(f"    assert.ok((r.body as any).some((x: any) => x.{pkp} === {key}));")
        else:
            o += [f"    assert.equal((r.body as any).{pkp}, {key});", f"    await new {repo_class(L, n)}(em).delete(e.{member(L, t.pk.name)});",
                  f"    r = await api(\"GET\", {json.dumps(op.path)}, undefined, {_qargs(q)});", "    assert.equal(r.status, 404);"]
        return o
    if k == "api_query_params":
        q = next(x for x in t.queries if x.name == op.arg)
        o = _setup(t, q, tables) + ["    void e;", f"    void {member(L, next(c.param for c in q.where if c.param and camel(c.param) == tc.args['param']))};"]
        return o + [f"    const r = await api(\"GET\", {json.dumps(op.path)}, undefined, {_qargs(q, tc.args['param'])});", "    assert.equal(r.status, 400);",
                    f'    assert.deepEqual((r.body as any).error.fields, {{ {tc.args["param"]}: "obbligatorio" }});']
    if k == "api_rel":
        r = next(x for x in t.relations if x.name == tc.args["relation"])
        tg = tables[r.target]
        fk = member(L, r.foreign_key)
        if r.kind == "many_to_one":
            return [f"    const p = await build{r.target}(em);", f"    const e = await build{n}(em, {{ {fk}: p.{member(L, tg.pk.name)} }});",
                    f"    const r = await api(\"GET\", {_path(op, key)});", "    assert.equal(r.status, 200, JSON.stringify(r.body));",
                    f"    assert.equal((r.body as any).{prop(tg.pk.name)}, {_jkey(tg.pk, 'p.' + member(L, tg.pk.name))});"]
        return [f"    const e = await build{n}(em);", f"    const c = await build{r.target}(em, {{ {fk}: e.{member(L, t.pk.name)} }});",
                f"    const r = await api(\"GET\", {_path(op, key)}, undefined, {{ limit: {tg.pagination.max_limit} }});",
                "    assert.equal(r.status, 200, JSON.stringify(r.body));",
                f"    assert.ok((r.body as any).items.some((x: any) => x.{prop(tg.pk.name)} === {_jkey(tg.pk, 'c.' + member(L, tg.pk.name))}));"]
    if k == "api_rel_missing":
        return [f"    const r = await api(\"GET\", {_path(op, _missing_json(t.pk))});", "    assert.equal(r.status, 404);",
                '    assert.equal((r.body as any).error.code, "RECORD_NOT_FOUND");']
    if k in ("api_auth", "api_scope", "api_tenant_missing"):
        ident = {"api_auth": "null", "api_scope": 'identity({ tenant: String(TENANT_A), scopes: [] })',
                 "api_tenant_missing": "identity({ tenant: null })"}[k]
        want = {"api_auth": (401, "IDENTITY_REQUIRED"), "api_scope": (403, "SCOPE_REQUIRED"), "api_tenant_missing": (403, "TENANT_REQUIRED")}[k]
        o, args = [], "undefined, {}"
        if op.kind == "create":
            o.append("    const sent = await body(em);")
            args = "sent, {}"
        elif op.kind == "update":
            args = "{}, {}"
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            o += _setup(t, q, tables) + ["    void e;"]
            args = f"undefined, {_qargs(q)}"
        elif op.kind == "rel":
            o.append(f"    const e = await build{n}(em);")
        key_expr = key if op.kind == "rel" else _missing_json(t.pk)
        return o + [f"    const r = await api({json.dumps(op.method.upper())}, {_path(op, key_expr)}, {args}, {ident});",
                    f"    assert.equal(r.status, {want[0]}, JSON.stringify(r.body));", f'    assert.equal((r.body as any).error.code, "{want[1]}");']
    if k == "api_tenant_other":
        return [f"    const e = await build{n}(em);",
                f"    const r = await api(\"GET\", {B} + \"/\" + String({key}), undefined, {{}}, identity({{ tenant: String(TENANT_B) }}));",
                "    assert.equal(r.status, 404);"]
    raise ValueError(k)


def _imports(tables: Dict[str, Table], t: Table, ctrl_rel: str, model_rel: str) -> List[str]:
    others = sorted({r.target for r in t.relations} | {t.name})
    o = ['import { randomUUID } from "node:crypto";', 'import { test } from "node:test";', 'import assert from "node:assert/strict";',
         f'import {{ toJson }} from "{ctrl_rel}/{t.name}";', f'import {{ {repo_class(L, t.name)} }} from "{model_rel}/{t.name}";',
         "import { " + ", ".join(f"build{x}" for x in others) + ", dayValue, different, greater, nextN, smaller, textValue, TENANT_A, TENANT_B } from \"./kybes_builders\";",
         'import { caller, data, identity, qv } from "./kybes_api";']
    if t.mongo:
        o += ['import { withMongo } from "./_mongo_db";', f'import type {{ MongoSession }} from "{model_rel}/generated";']
    else:
        o += ['import { withDb } from "./_db";', 'import type { EntityManager } from "typeorm";']
    return o


def table_file(t: Table, cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str,
               ctrl_rel: str, model_rel: str) -> str:
    n = t.name
    runner = "withMongo" if t.mongo else "withDb"
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n") + "\n/* eslint-disable */",
         f"// Test di unità generati per le API di {n} (ASIL {table_asil(t, asil)}). Specifica: docs/generated/verification/{n}.md."]
    o += _imports(tables, t, ctrl_rel, model_rel)
    o += ["", "void [randomUUID, dayValue, different, greater, smaller, textValue, nextN, TENANT_A, TENANT_B, qv, identity, toJson];", ""]
    o += _body_fn(t, tables)
    o.append(f"void body;")
    for tc in cat.for_table(n, "api"):
        o += ["", f"test({json.dumps(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)}, () =>",
              f"  {runner}(async (em, ds) => {{", f"    // atteso: {tc.expected}", "    const api = caller(data(ds));"]
        o += _case(t, tc, tables, ops)
        o.append("  }));")
    return "\n".join(o) + "\n"


def custom_file(cat: Catalog, tables: Dict[str, Table], ops: List[Operation]) -> str:
    runner = "withDb" if has_sql(tables) else "withMongo"
    o = [header(L, "schemas/openapi.yaml").rstrip("\n") + "\n/* eslint-disable */",
         "// Test di unità generati per gli endpoint custom del contratto.", 'import { test } from "node:test";',
         'import assert from "node:assert/strict";', 'import { caller, data, recorder } from "./kybes_api";',
         f'import {{ {runner} }} from "./{"_db" if runner == "withDb" else "_mongo_db"}";']
    by_id = {x.op_id: x for x in ops}
    for tc in cat.for_table(API, "api"):
        op = by_id[tc.args["operation"]]
        inp = tc.args["input"]
        path = op.path
        for p in op.params:
            if p.loc == "path":
                path = path.replace("{" + p.name + "}", _qstr(inp["path"][p.name]))
        o += ["", f"test({json.dumps(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)}, () =>",
              f"  {runner}(async (_em, ds) => {{", "    const custom = recorder();", "    const api = caller(data(ds), custom.impl);",
              f"    const query: Record<string, unknown> = {json.dumps(inp['query'])};",
              f"    const r = await api({json.dumps(op.method.upper())}, {json.dumps(path)}, {json.dumps(inp['body']) if inp['body'] is not None else 'undefined'}, query);"]
        if tc.kind == "api_custom":
            o += [f"    assert.equal(r.status, {op.status}, JSON.stringify(r.body));", "    const call = custom.calls[custom.calls.length - 1];",
                  f"    assert.equal(call.operation, {json.dumps(op.op_id)});", f"    assert.deepEqual(call.path, {json.dumps(inp['path'])});",
                  "    assert.deepEqual(call.query, query);", f"    assert.deepEqual(call.body, {json.dumps(inp['body'])});"]
        else:
            o += ["    assert.equal(r.status, 400);", f'    assert.deepEqual((r.body as any).error.fields, {{ {json.dumps(tc.args["field"])}: "obbligatorio" }});',
                  "    assert.equal(custom.calls.length, 0);"]
        o.append("  }));")
    return "\n".join(o) + "\n"


def _qstr(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def api_module(tables: Dict[str, Table], ops: List[Operation], api_rel: str) -> str:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    scopes = sorted({s for o in ops for s in o.scopes})
    o = [header(L, "kit").rstrip("\n") + "\n/* eslint-disable */",
         "// Supporto dei test delle API: buildApi con i dati dei test, identità di prova, metodi custom finti.",
         f'import {{ ApiData, buildApi }} from "{api_rel}";', f'import type {{ ApiResponse, Call, Identity }} from "{api_rel}";',
         'import { TENANT_A } from "./kybes_builders";']
    if sql:
        o.append('import type { DataSource } from "typeorm";')
    if mongo:
        o.append('import type { MongoTestDb } from "./_mongo_db";')
    o += ["", f"export const SCOPES: string[] = {json.dumps(scopes)};", "",
          "/** Identità di prova: soggetto, TENANT_A e tutti gli scope del contratto, salvo quanto indicato. */",
          "export function identity(over: { tenant?: string | null; scopes?: string[] } = {}): Identity {",
          '  return { subject: "kybes-test", tenant: "tenant" in over ? (over.tenant ?? null) : String(TENANT_A), scopes: new Set(over.scopes ?? SCOPES), claims: {} };',
          "}", "", "/** Valore del modello come testo di un parametro di query. */",
          "export function qv(v: unknown): string | string[] {", "  if (Array.isArray(v)) return v.map((x) => qv(x) as string);",
          "  if (v instanceof Date) return v.toISOString();", "  return String(v);", "}", "",
          "/** Implementazione finta dei metodi custom: registra le chiamate e restituisce l'operazione. */",
          "export function recorder(): { impl: unknown; calls: Call[] } {", "  const calls: Call[] = [];",
          "  const impl = new Proxy({}, { get: (_t, name) => (typeof name === \"string\" ? (call: Call) => { calls.push(call); return { operation: call.operation }; } : undefined) });",
          "  return { impl, calls };", "}", ""]
    levels = '  levels: process.env.KYBES_TEST_DATABASE_URL ? undefined : { read_committed: null, repeatable_read: null, serializable: null },'
    if sql and mongo:
        o += ["/** Dati delle API per i test: DataSource (tabelle SQL) o client MongoDB (collection). */",
              "export function data(ds: DataSource | MongoTestDb): ApiData {",
              '  if ("client" in ds) return new ApiData({ mongoClient: ds.client, mongoDatabase: ds.db.databaseName });',
              f"  return new ApiData({{ dataSource: ds,\n  {levels}\n  }});", "}", ""]
    elif sql:
        o += ["export function data(ds: DataSource): ApiData {", f"  return new ApiData({{ dataSource: ds,\n  {levels}\n  }});", "}", ""]
    else:
        o += ["export function data(ds: MongoTestDb): ApiData {", "  return new ApiData({ mongoClient: ds.client, mongoDatabase: ds.db.databaseName });", "}", ""]
    o += ["export type Caller = (method: string, path: string, body?: unknown, query?: Record<string, unknown>, who?: Identity | null,",
          "  headers?: Record<string, string>) => Promise<ApiResponse>;", "",
          "/** Le operazioni custom senza implementazione indicata usano recorder(). */", "export function caller(d: ApiData, custom: unknown = null): Caller {", "  const api = buildApi(d, (custom ?? recorder().impl) as never);",
          "  return async (method, path, body, query = {}, who = identity(), headers = {}) => {",
          "    const q: Record<string, string[]> = {};",
          "    for (const [k, v] of Object.entries(query)) q[k] = Array.isArray(v) ? (qv(v) as string[]) : [qv(v) as string];",
          "    const payload = body === undefined ? null : Buffer.from(JSON.stringify(body), \"utf8\");",
          '    return api.handle({ method, path, query: q, headers: { "content-type": "application/json", ...headers }, body: payload, identity: who });',
          "  };", "}"]
    return "\n".join(o) + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> Dict[str, str]:
    import runtime_api_typescript_tests as rtt
    tests_gen = opts.get("tests_dir", "tests") + "/generated"
    api_rel = _ts_relpath(tests_gen, opts.get("api_dir", "api") + "/generated")
    ctrl_rel = _ts_relpath(tests_gen, opts.get("controller_dir", "controllers") + "/generated")
    model_rel = _ts_relpath(tests_gen, opts.get("model_dir", "model"))
    files = {"generated/kybes_api.ts": api_module(tables, ops, api_rel)}
    for n, t in tables.items():
        if any(o.table == n for o in ops):
            files[f"generated/{n}.api.test.ts"] = table_file(t, cat, tables, ops, asil, ctrl_rel, model_rel)
    if any(o.kind == "custom" for o in ops):
        files["generated/kybes_api_custom.test.ts"] = custom_file(cat, tables, ops)
    files["generated/kybes_api_runtime.test.ts"] = rtt.render(cat, tables, ops, asil, api_rel, ctrl_rel, model_rel)
    return files
