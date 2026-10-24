"""Rende i casi di test delle API (scope "api") in xUnit per il pacchetto C# del modello.

Stessa struttura dei test degli altri linguaggi: ApiRouter.HandleAsync con richieste come quelle degli adattatori, dati di
partenza con i builder del modello (il contesto dei test salva subito; la sessione MongoDB anche). L'API usa contesti
propri, senza tenant legato: lo lega lei dall'identità della chiamata.
"""
from __future__ import annotations

import json
from typing import Dict, List

import api_plan
import test_csharp as tc_
from api_plan import Operation, prop
from emit_api_csharp import api_namespace, controller_namespace
from naming import header, member, repo_class
from schema import Table, camel
from sqlonly import has_sql
from verification import API, API_RT, METHODS, RUNTIME, Catalog, TestCase, table_asil, ttl_column

L = "csharp"


def index(tables: Dict[str, Table], ops: List[Operation]) -> Dict[str, str]:
    out = {n: f"generated/{n}ApiTests.cs" for n in tables if any(o.table == n for o in ops)}
    out[API_RT] = out[RUNTIME] = "generated/KybesApiRuntimeTests.cs"
    if any(o.kind == "custom" for o in ops):
        out[API] = "generated/KybesApiCustomTests.cs"
    return out


def _cs(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _json_sample(t: Table, c) -> str:
    if c.name == ttl_column(t):
        return {"date": 'DateOnly.FromDateTime(DateTime.UtcNow).AddDays(NextN()).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)',
                "datetime": "ApiConvert.DatetimeText(new DateTimeOffset(DateTime.UtcNow.Date, TimeSpan.Zero).AddHours(DateTime.UtcNow.Hour + NextN()))"}[c.type]
    if c.type == "string":
        return f"TextValue(NextN(), {c.length})"
    if c.type == "decimal":
        return "NextN().ToString(CultureInfo.InvariantCulture)" if not c.scale else f'NextN() + ".{"5" * c.scale}"'
    return {"uuid": "Guid.NewGuid().ToString()", "text": '"testo " + NextN()', "int": "(long)NextN()", "bigint": "NextN().ToString(CultureInfo.InvariantCulture)",
            "bool": "true", "date": 'new DateOnly(2026, 1, 1).AddDays(NextN()).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)',
            "datetime": "ApiConvert.DatetimeText(new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero).AddHours(NextN()))",
            "json": 'new Dictionary<string, object?> { ["n"] = (long)NextN() }'}[c.type]


def _json_new(c) -> str:
    if c.type == "string":
        return f'"u" + TextValue(NextN(), {max(c.length - 1, 1)})'
    if c.type == "decimal":
        return "(NextN() + 500).ToString(CultureInfo.InvariantCulture)" if not c.scale else f'(NextN() + 500) + ".{"2" * c.scale}"'
    return {"text": '"testo aggiornato"', "int": "(long)(NextN() + 500)", "bigint": "(NextN() + 500).ToString(CultureInfo.InvariantCulture)",
            "bool": "false"}[c.type]


def _jkey(pk, expr: str) -> str:
    """Chiave come compare nel JSON della risposta (canonico: Canon)."""
    return f"(long){expr}" if pk.type == "int" else (expr if pk.type == "string" else f"{expr}.ToString()")


def _ktext(pk, expr: str) -> str:
    return expr if pk.type == "string" else f"{expr}.ToString()"


def _missing_json(pk) -> str:
    return {"uuid": '"00000000-0000-4000-8000-000000000999"', "int": '"987654321"', "bigint": '"987654321"', "string": '"kybes-non-esiste"'}[pk.type]


def _path(op: Operation, key_text: str) -> str:
    if "{id}" not in op.path:
        return _cs(op.path)
    a, b = op.path.split("{id}")
    return f"{_cs(a)} + {key_text} + {_cs(b)}" if b else f"{_cs(a)} + {key_text}"


def _body_fn(t: Table, tables: Dict[str, Table]) -> List[str]:
    o = ["", f"    /// <summary>Corpo valido per la creazione di {t.name}, con ogni chiave esterna verso un padre inserito prima.</summary>",
         "    private async Task<Dictionary<string, object?>> Body()", "    {", "        var output = new Dictionary<string, object?>();"]
    for c in api_plan.writable_columns(t):
        rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
        if rel:
            tg = tables[rel.target]
            o.append(f'        output["{prop(c.name)}"] = {_jkey(tg.pk, f"(await Build{rel.target}(db)).{member(L, tg.pk.name)}")};')
            continue
        o.append(f'        output["{prop(c.name)}"] = {_json_sample(t, c)};')
    o += ["        return output;", "    }"]
    return o


def _setup(t: Table, q, tables) -> List[str]:
    setup = tc_._query_case(t, TestCase("TC-X", t.name, [], "req", "query_match", "", "", {"query": q.name}), tables)
    cut = next(i for i, line in enumerate(setup) if "Repository(db)." in line)
    return setup[:cut]


def _qargs(q, skip: str = "") -> str:
    parts = []
    for c in q.where:
        if c.param and camel(c.param) != skip:
            parts += [_cs(camel(c.param)), c.param[:1].lower() + c.param[1:]]
    return f"Q({', '.join(parts)})"


def _case(t: Table, tc: TestCase, tables: Dict[str, Table], ops: List[Operation]) -> List[str]:
    n, k = t.name, tc.kind
    base = "/" + t.api.path
    B = _cs(base)
    pkp = _cs(prop(t.pk.name))
    pkm = member(L, t.pk.name)
    key = _jkey(t.pk, f"e.{pkm}")
    ktext = _ktext(t.pk, f"e.{pkm}")
    op = next((o for o in ops if o.op_id == tc.args.get("operation")), None)
    eq = "Assert.Equal(Canon({}), Canon({}));"
    if k == "api_list":
        m = t.pagination.max_limit
        return [f"        var e = await Build{n}(db);", f'        var r = await Call("GET", {B}, null, Q("limit", {m}), Me);',
                "        Assert.True(r.Status == 200, r.Text);", f'        Assert.Equal({m}L, r.Map()["limit"]);',
                f"        Assert.Contains(r.Items(), x => Canon(x[{pkp}]) == Canon({key}));"]
    if k == "api_list_params":
        return [f'        var r = await Call("GET", {B}, null, Q("limit", 0), Me);', "        Assert.Equal(400, r.Status);",
                "        " + eq.format('J("{\'limit\': \'valore minimo 1\'}")', "r.Fields()"),
                f'        r = await Call("GET", {B}, null, Q("kybesSconosciuto", 1), Me);', "        Assert.Equal(400, r.Status);",
                "        " + eq.format('J("{\'kybesSconosciuto\': \'parametro sconosciuto\'}")', "r.Fields()")]
    if k == "api_list_expand":
        rels = [next(x for x in t.relations if x.name == rn) for rn in tc.args["relations"]]
        exp_val = tc.args["expand"]
        o = []
        seen_targets = {}
        assign_parts = []
        for rel in rels:
            tg = tables[rel.target]
            fk = member(L, rel.foreign_key)
            tpk = member(L, tg.pk.name)
            if rel.target == n:
                var = "selfP"
            elif rel.target not in seen_targets:
                var = f"p{rel.target}"
                o.append(f"        var {var} = await Build{rel.target}(db);")
                seen_targets[rel.target] = var
            else:
                var = seen_targets[rel.target]
            assign_parts.append(f"x.{fk} = {var}.{tpk}")
        if any(r.target == n for r in rels):
            o.append(f"        var selfP = await Build{n}(db);")
        lam = "; ".join(assign_parts)
        o.append(f"        var e = await Build{n}(db, x => {{ {lam}; }});")
        o += [f'        var r = await Call("GET", {B}, null, Q("expand", {_cs(exp_val)}, "limit", {t.pagination.max_limit}), Me);',
              "        Assert.True(r.Status == 200, r.Text);",
              f"        var hit = r.Items().First(x => Canon(x[{pkp}]) == Canon({key}));"]
        for rel in rels:
            o.append(f"        Assert.True(hit.ContainsKey({_cs(prop(rel.name))}) && hit[{_cs(prop(rel.name))}] != null, \"relazione espansa mancante\");")
        return o
    if k == "api_list_expand_bad":
        return [f'        var r = await Call("GET", {B}, null, Q("expand", "kybesNonEsiste"), Me);',
                "        Assert.Equal(400, r.Status);",
                '        Assert.Contains("invalid expand", r.Error()["code"].ToString());']
    if k == "api_get":
        return [f"        var e = await Build{n}(db);", f'        var r = await Call("GET", {B} + "/" + {ktext}, null, Q(), Me);',
                "        Assert.True(r.Status == 200, r.Text);",
                "        " + eq.format(f"{n}Api.ToJson((await new {repo_class(L, n)}(db).GetByIdAsync(e.{pkm}))!)", "r.Body")]
    if k in ("api_get_missing", "api_update_missing", "api_delete_missing"):
        method, body = {"api_get_missing": ("GET", "null"), "api_update_missing": ("PATCH", "Q()"), "api_delete_missing": ("DELETE", "null")}[k]
        return [f'        var r = await Call("{method}", {B} + "/" + {_missing_json(t.pk)}, {body}, Q(), Me);', "        Assert.Equal(404, r.Status);",
                '        Assert.Equal("RECORD_NOT_FOUND", r.Error()["code"]);']
    if k == "api_get_badid":
        return [f'        var r = await Call("GET", {_cs(base + "/kybes-non-valido")}, null, Q(), Me);', "        Assert.Equal(400, r.Status);",
                "        " + eq.format(f'Q("id", {_cs(tc.args["rule"])})', "r.Fields()")]
    if k == "api_create":
        return ["        var sent = await Body();", f'        var r = await Call("POST", {B}, sent, Q(), Me);',
                "        Assert.True(r.Status == 201, r.Text);", f'        Assert.Equal({B} + "/" + Canon(r.Map()[{pkp}]).Trim(\'"\'), r.Headers["location"]);',
                "        foreach (var x in sent) Assert.True(Canon(x.Value) == Canon(r.Map()[x.Key]), x.Key);"]
    if k == "api_create_required":
        p = _cs(prop(tc.args["column"]))
        return ["        var sent = await Body();", f"        sent.Remove({p});", f'        var r = await Call("POST", {B}, sent, Q(), Me);',
                "        Assert.Equal(400, r.Status);", "        " + eq.format(f'Q({p}, "obbligatorio")', "r.Fields()")]
    if k == "api_create_extra":
        return ["        var sent = await Body();", '        sent["kybesSconosciuto"] = 1L;', f'        var r = await Call("POST", {B}, sent, Q(), Me);',
                "        Assert.Equal(400, r.Status);", "        " + eq.format('Q("kybesSconosciuto", "non ammesso")', "r.Fields()")]
    if k == "api_create_type":
        c = t.col(tc.args["column"])
        p = _cs(prop(c.name))
        wrong = '"x"' if c.type in ("int", "bool") else "12345L"
        return ["        var sent = await Body();", f"        sent[{p}] = {wrong};", f'        var r = await Call("POST", {B}, sent, Q(), Me);',
                "        Assert.Equal(400, r.Status);", "        " + eq.format(f"Q({p}, {_cs(tc.args['rule'])})", "r.Fields()")]
    if k == "api_create_duplicate":
        p = _cs(prop(tc.args["column"]))
        return ["        var first = await Body();", f'        Assert.Equal(201, (await Call("POST", {B}, first, Q(), Me)).Status);',
                "        var second = await Body();", f"        second[{p}] = first[{p}];", f'        var r = await Call("POST", {B}, second, Q(), Me);',
                "        Assert.True(r.Status == 409, r.Text);", '        Assert.Contains((string)r.Error()["code"]!, new[] { "CONSTRAINT", "DUPLICATE" });']
    if k == "api_update":
        if "column" in tc.args:
            c = t.col(tc.args["column"])
            p = _cs(prop(c.name))
            return [f"        var e = await Build{n}(db);", f"        object value = {_json_new(c)};",
                    f'        var r = await Call("PATCH", {B} + "/" + {ktext}, Q({p}, value), Q(), Me);',
                    "        Assert.True(r.Status == 200, r.Text);", "        " + eq.format("value", f"r.Map()[{p}]"),
                    "        " + eq.format(key, f"r.Map()[{pkp}]"),
                    f'        r = await Call("PATCH", {B} + "/" + {ktext}, Q(), Q(), Me);', "        Assert.True(r.Status == 200, r.Text);",
                    "        " + eq.format("value", f"r.Map()[{p}]")]
        return [f"        var e = await Build{n}(db);", f'        var r = await Call("PATCH", {B} + "/" + {ktext}, Q(), Q(), Me);',
                "        Assert.True(r.Status == 200, r.Text);", "        " + eq.format(key, f"r.Map()[{pkp}]")]
    if k == "api_update_key":
        return [f"        var e = await Build{n}(db);", f'        var r = await Call("PATCH", {B} + "/" + {ktext}, Q({pkp}, {key}), Q(), Me);',
                "        Assert.Equal(400, r.Status);", "        " + eq.format(f'Q({pkp}, "non ammesso")', "r.Fields()")]
    if k == "api_delete":
        has_get = any(o.table == n and o.kind == "get" for o in ops)
        return [f"        var e = await Build{n}(db);", f'        var r = await Call("DELETE", {B} + "/" + {ktext}, null, Q(), Me);',
                "        Assert.Equal(204, r.Status);", "        Assert.Null(r.Body);",
                f'        Assert.Equal(404, (await Call({_cs("GET" if has_get else "DELETE")}, {B} + "/" + {ktext}, null, Q(), Me)).Status);']
    if k == "api_query":
        q = next(x for x in t.queries if x.name == op.arg)
        o = _setup(t, q, tables)
        o += [f'        var r = await Call("GET", {_cs(op.path)}, null, {_qargs(q)}, Me);', "        Assert.True(r.Status == 200, r.Text);"]
        if q.returns == "page":
            o.append(f"        Assert.Contains(r.Items(), x => Canon(x[{pkp}]) == Canon({key}));")
        elif q.returns == "list":
            o.append(f"        Assert.Contains(r.List(), x => Canon(x[{pkp}]) == Canon({key}));")
        else:
            o += ["        " + eq.format(key, f"r.Map()[{pkp}]"), f"        await new {repo_class(L, n)}(db).DeleteAsync(e.{pkm});",
                  f'        r = await Call("GET", {_cs(op.path)}, null, {_qargs(q)}, Me);', "        Assert.Equal(404, r.Status);"]
        return o
    if k == "api_query_params":
        q = next(x for x in t.queries if x.name == op.arg)
        return _setup(t, q, tables) + [f'        var r = await Call("GET", {_cs(op.path)}, null, {_qargs(q, tc.args["param"])}, Me);',
                                       "        Assert.Equal(400, r.Status);",
                                       "        " + eq.format(f'Q({_cs(tc.args["param"])}, "obbligatorio")', "r.Fields()")]
    if k == "api_rel":
        r = next(x for x in t.relations if x.name == tc.args["relation"])
        tg = tables[r.target]
        tpk = member(L, tg.pk.name)
        fk = member(L, r.foreign_key)
        if r.kind == "many_to_one":
            return [f"        var p = await Build{r.target}(db);", f"        var e = await Build{n}(db, x => x.{fk} = p.{tpk});",
                    f'        var r = await Call("GET", {_path(op, ktext)}, null, Q(), Me);', "        Assert.True(r.Status == 200, r.Text);",
                    "        " + eq.format(_jkey(tg.pk, "p." + tpk), f"r.Map()[{_cs(prop(tg.pk.name))}]")]
        return [f"        var e = await Build{n}(db);", f"        var c = await Build{r.target}(db, x => x.{fk} = e.{pkm});",
                f'        var r = await Call("GET", {_path(op, ktext)}, null, Q("limit", {tg.pagination.max_limit}), Me);',
                "        Assert.True(r.Status == 200, r.Text);",
                f"        Assert.Contains(r.Items(), x => Canon(x[{_cs(prop(tg.pk.name))}]) == Canon({_jkey(tg.pk, 'c.' + tpk)}));"]
    if k == "api_rel_missing":
        return [f'        var r = await Call("GET", {_path(op, _missing_json(t.pk))}, null, Q(), Me);', "        Assert.Equal(404, r.Status);",
                '        Assert.Equal("RECORD_NOT_FOUND", r.Error()["code"]);']
    if k in ("api_auth", "api_scope", "api_tenant_missing"):
        ident = {"api_auth": "null", "api_scope": "Who(TENANT_A.ToString(), Array.Empty<string>())", "api_tenant_missing": "Who(null, Scopes)"}[k]
        want = {"api_auth": (401, "IDENTITY_REQUIRED"), "api_scope": (403, "SCOPE_REQUIRED"), "api_tenant_missing": (403, "TENANT_REQUIRED")}[k]
        o, body, query = [], "null", "Q()"
        if op.kind == "create":
            o.append("        var sent = await Body();")
            body = "sent"
        elif op.kind == "update":
            body = "Q()"
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            o += _setup(t, q, tables)
            query = _qargs(q)
        elif op.kind == "rel":
            o.append(f"        var e = await Build{n}(db);")
        key_expr = ktext if op.kind == "rel" else _missing_json(t.pk)
        return o + [f"        var r = await Call({_cs(op.method.upper())}, {_path(op, key_expr)}, {body}, {query}, {ident});",
                    f"        Assert.True(r.Status == {want[0]}, r.Text);", f'        Assert.Equal("{want[1]}", r.Error()["code"]);']
    if k == "api_tenant_other":
        return [f"        var e = await Build{n}(db);",
                f'        var r = await Call("GET", {B} + "/" + {ktext}, null, Q(), Who(TENANT_B.ToString(), Scopes));',
                "        Assert.Equal(404, r.Status);"]
    raise ValueError(k)


def _usings(model_ns: str, api_ns: str, ctrl_ns: str, mongo: bool) -> List[str]:
    o = ["#nullable enable", "using System;", "using System.Collections.Generic;", "using System.Globalization;", "using System.Linq;",
         "using System.Threading.Tasks;"]
    o += ["using MongoDB.Bson;", "using MongoDB.Driver;"] if mongo else ["using Microsoft.EntityFrameworkCore;"]
    return o + ["using Xunit;", f"using {model_ns};", f"using {api_ns};", f"using {ctrl_ns};", f"using static {model_ns}.Tests.KybesBuilders;",
                f"using static {model_ns}.Tests.KybesApiSupport;"]


def table_file(t: Table, cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, model_ns: str) -> str:
    n = t.name
    api_ns = api_namespace(model_ns)
    ctrl_ns = controller_namespace(model_ns)
    custom = any(o.kind == "custom" for o in ops)
    rec = ", new Recorder()" if custom else ""
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n"), "// <auto-generated />"] + _usings(model_ns, api_ns, ctrl_ns, t.mongo) + [
        "", f"namespace {model_ns}.Tests;", "",
        f"/// <summary>Test di unità generati per le API di {n} (ASIL {table_asil(t, asil)}). Specifica: docs/generated/verification/{n}.md.</summary>",
        f"public sealed class {n}ApiTests : IDisposable", "{"]
    if t.mongo:
        o += ["    private readonly MongoSession db = KybesMongo.Open();", "    private readonly ApiRouter api;", "",
              f"    public {n}ApiTests()", "    {",
              f"        api = KybesApi.Build(new ApiData {{ MongoClient = KybesMongo.Client(), MongoDatabase = db.Db.DatabaseNamespace.DatabaseName }}{rec});",
              "    }", "", "    public void Dispose() => KybesMongo.Close(db);"]
    else:
        o += ["    private readonly AppDbContext db = KybesDb.Open();", "    private readonly ApiRouter api;", "",
              f"    public {n}ApiTests()", "    {", f"        api = KybesApi.Build(new ApiData {{ SqlFor = _ => Fresh() }}{rec});", "    }", "",
              "    public void Dispose() => db.Dispose();"]
    o += ["", "    private Task<Result> Call(string method, string path, object? body, IReadOnlyDictionary<string, object?> query, Identity? who) =>",
          "        CallAsync(api, method, path, body, query, who);"]
    o += _body_fn(t, tables)
    for tc in cat.for_table(n, "api"):
        title = tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title
        o += ["", f"    [Fact(DisplayName = {_cs(title)})]", f"    public async Task {tc.slug}()", "    {", f"        // atteso: {tc.expected}"]
        o += _case(t, tc, tables, ops)
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def _cv(v) -> str:
    """Valore JSON (da api_plan.sample) come espressione C# (interi long, oggetti Dictionary)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}L"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return _cs(v)
    if isinstance(v, list):
        return "new List<object?> { " + ", ".join(_cv(x) for x in v) + " }"
    return "Q(" + ", ".join(f"{_cs(k)}, {_cv(x)}" for k, x in v.items()) + ")"


def _qstr(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def custom_file(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], model_ns: str) -> str:
    api_ns = api_namespace(model_ns)
    ctrl_ns = controller_namespace(model_ns)
    o = [header(L, "schemas/openapi.yaml").rstrip("\n"), "// <auto-generated />"] + _usings(model_ns, api_ns, ctrl_ns, False) + [
        "", f"namespace {model_ns}.Tests;", "", "/// <summary>Test di unità generati per gli endpoint custom del contratto.</summary>",
        "public sealed class KybesApiCustomTests", "{"]
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
            qparts += [_cs(name), _cv(v)]
        o += ["", f"    [Fact(DisplayName = {_cs(title)})]", f"    public async Task {tc.slug}()", "    {",
              "        var custom = new Recorder();", "        var api = KybesApi.Build(new ApiData(), custom);",
              f"        var query = Q({', '.join(qparts)});",
              f"        var r = await CallAsync(api, {_cs(op.method.upper())}, {_cs(path)}, {_cv(inp['body'])}, query, Me);"]
        if tc.kind == "api_custom":
            o += [f"        Assert.True(r.Status == {op.status}, r.Text);", "        var call = custom.Calls[^1];",
                  f'        Assert.Equal("{op.op_id}", call.Operation);', f"        Assert.Equal(Canon({_cv(inp['path'])}), Canon(call.Path));",
                  "        Assert.Equal(Canon(query), Canon(call.Query));", f"        Assert.Equal(Canon({_cv(inp['body'])}), Canon(call.Body));"]
        else:
            o += ["        Assert.Equal(400, r.Status);", f'        Assert.Equal(Canon(Q({_cs(tc.args["field"])}, "obbligatorio")), Canon(r.Fields()));',
                  "        Assert.Empty(custom.Calls);"]
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def support_file(tables: Dict[str, Table], ops: List[Operation], model_ns: str) -> str:
    api_ns = api_namespace(model_ns)
    ctrl_ns = controller_namespace(model_ns)
    sql = has_sql(tables)
    scopes = sorted({s for o in ops for s in o.scopes})
    custom = [o for o in ops if o.kind == "custom"]
    o = [header(L, "kit").rstrip("\n"), "// <auto-generated />", "#nullable enable", "using System;", "using System.Collections;",
         "using System.Collections.Generic;", "using System.Globalization;", "using System.Linq;", "using System.Text;", "using System.Threading.Tasks;"]
    if sql:
        o.append("using Microsoft.EntityFrameworkCore;")
    o += [f"using {model_ns};", f"using {api_ns};", f"using {ctrl_ns};", "", f"namespace {model_ns}.Tests;", "",
          "/// <summary>Supporto dei test delle API: identità di prova, chiamate all'ApiRouter con il JSON come lo vede un client, metodi custom finti.</summary>",
          "public static class KybesApiSupport", "{",
          "    public static readonly IReadOnlyList<string> Scopes = new string[] { " + ", ".join(_cs(s) for s in scopes) + " };",
          "    public static readonly Identity Me = Who(KybesBuilders.TENANT_A.ToString(), Scopes);", "",
          "    /// <summary>Identità di prova: soggetto, tenant e scope indicati.</summary>",
          "    public static Identity Who(string? tenant, IEnumerable<string> scopes) =>",
          '        new("kybes-test", tenant, new HashSet<string>(scopes), new Dictionary<string, object?>());', "",
          "    /// <summary>Valore del modello come testo di un parametro di query.</summary>", "    public static object Qv(object? v) => v switch",
          "    {", "        string s => s,", '        bool b => b ? "true" : "false",', "        DateTimeOffset d => ApiConvert.DatetimeText(d)!,",
          "        DateOnly d => ApiConvert.DateText(d)!,", "        IEnumerable e => e.Cast<object?>().Select(x => (string)Qv(x)).ToList(),",
          "        _ => Convert.ToString(v, CultureInfo.InvariantCulture)!,", "    };", "",
          "    /// <summary>Dizionario da coppie chiave, valore.</summary>", "    public static Dictionary<string, object?> Q(params object?[] kv)", "    {",
          "        var output = new Dictionary<string, object?>();", "        for (var i = 0; i < kv.Length; i += 2) output[(string)kv[i]!] = kv[i + 1];",
          "        return output;", "    }", "",
          "    /// <summary>JSON scritto con gli apici singoli (più leggibile nei test).</summary>",
          "    public static object? J(string text) => Json.Parse(text.Replace('\\'', '\"'));", "",
          "    /// <summary>Forma canonica di un valore JSON (chiavi ordinate, numeri come testo) per confrontarlo.</summary>",
          "    public static string Canon(object? v) => v switch", "    {", "        null => \"null\",",
          "        IDictionary m => \"{\" + string.Join(\",\", m.Keys.Cast<object>().Select(k => k.ToString()!).OrderBy(k => k, StringComparer.Ordinal)"
          ".Select(k => Json.Write(k) + \":\" + Canon(m[k]))) + \"}\",",
          "        string s => Json.Write(s),", "        IEnumerable e => \"[\" + string.Join(\",\", e.Cast<object?>().Select(Canon)) + \"]\",",
          "        _ => Json.Write(v),", "    };", "",
          "    /// <summary>Risposta come la vede un client: stato, JSON letto (null senza corpo), testo, header.</summary>",
          "    public sealed record Result(int Status, object? Body, string Text, Dictionary<string, string> Headers)", "    {",
          "        public Dictionary<string, object?> Map() => (Dictionary<string, object?>)Body!;",
          "        public List<Dictionary<string, object?>> List() => ((IList)Body!).Cast<Dictionary<string, object?>>().ToList();",
          '        public List<Dictionary<string, object?>> Items() => ((IList)Map()["items"]!).Cast<Dictionary<string, object?>>().ToList();',
          '        public Dictionary<string, object?> Error() => (Dictionary<string, object?>)Map()["error"]!;',
          '        public object? Fields() => Error().GetValueOrDefault("fields");', "    }", "",
          "    /// <summary>ApiRouter.HandleAsync con il corpo serializzato e i parametri come testo.</summary>",
          "    public static async Task<Result> CallAsync(ApiRouter api, string method, string path, object? body, IReadOnlyDictionary<string, object?> query, Identity? who)",
          "    {", "        var q = new Dictionary<string, List<string>>();", "        foreach (var kv in query)", "        {", "            var v = Qv(kv.Value);",
          "            q[kv.Key] = v is List<string> l ? l : new List<string> { (string)v };", "        }",
          "        var payload = body is null ? null : Encoding.UTF8.GetBytes(Json.Write(body));",
          '        var headers = new Dictionary<string, string> { ["content-type"] = "application/json" };',
          "        var resp = await api.HandleAsync(new ApiRequest(method, path, q, headers, payload, who));", "        var text = resp.Text();",
          "        return new Result(resp.Status, text.Length == 0 ? null : Json.Parse(text), text, resp.Headers);", "    }"]
    if sql:
        o += ["", "    /// <summary>Un contesto nuovo sul database dei test, senza tenant legato: lo lega l'API dall'identità.</summary>",
              "    public static AppDbContext Fresh() => new(new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(KybesDb.ConnectionString()).Options);"]
    if custom:
        o += ["", "    /// <summary>Implementazione finta dei metodi custom: registra le chiamate e restituisce l'operazione.</summary>",
              "    public sealed class Recorder : IOperations", "    {", "        public List<Call> Calls { get; } = new();", "",
              "        private Task<object?> Record(Call call)", "        {", "            Calls.Add(call);",
              '            return Task.FromResult<object?>(new Dictionary<string, object?> { ["operation"] = call.Operation });', "        }"]
        for x in custom:
            o += ["", f"        public Task<object?> {x.op_id[:1].upper() + x.op_id[1:]}(Call call) => Record(call);"]
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, opts: Dict) -> Dict[str, str]:
    import runtime_api_csharp_tests as rtt
    model_ns = opts["namespace"]
    files = {"generated/KybesApiSupport.cs": support_file(tables, ops, model_ns)}
    for n, t in tables.items():
        if any(o.table == n for o in ops):
            files[f"generated/{n}ApiTests.cs"] = table_file(t, cat, tables, ops, asil, model_ns)
    if any(o.kind == "custom" for o in ops):
        files["generated/KybesApiCustomTests.cs"] = custom_file(cat, tables, ops, model_ns)
    files["generated/KybesApiRuntimeTests.cs"] = rtt.render(cat, tables, ops, asil, model_ns, api_namespace(model_ns), controller_namespace(model_ns))
    return files
