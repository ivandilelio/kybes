"""Emettitore delle API C#: operazioni del contratto (Specs), controller CRUD per tabella, interfaccia dei metodi custom."""
from __future__ import annotations

import json
from typing import Dict, List

import runtime_api_csharp as rt
from api_plan import Operation, op_spec, prop
from emit_api_python import rel_targets
from naming import header, member, method_name, repo_class
from schema import Table
from sqlonly import has_sql

L = "csharp"
VALUE_TYPES = {"uuid", "int", "bigint", "decimal", "date", "datetime", "bool"}


def api_namespace(model_ns: str) -> str:
    """Namespace delle API accanto al modello: App.Model -> App.Api (come la cartella: model -> api)."""
    head, _, last = model_ns.rpartition(".")
    return (f"{head}.Api" if head else "Api") if last == "Model" else f"{model_ns}Api"


def controller_namespace(model_ns: str) -> str:
    """Namespace dei controller: App.Model -> App.Controllers."""
    head, _, last = model_ns.rpartition(".")
    return (f"{head}.Controllers" if head else "Controllers") if last == "Model" else f"{model_ns}Controllers"


def pascal(s: str) -> str:
    return s[:1].upper() + s[1:]


def to_json(c, expr: str) -> str:
    return {"uuid": f"ApiConvert.UuidText({expr})", "bigint": f"ApiConvert.Text({expr})", "decimal": f"ApiConvert.DecimalText({expr}, {c.scale})",
            "date": f"ApiConvert.DateText({expr})", "datetime": f"ApiConvert.DatetimeText({expr})", "json": f"ApiConvert.JsonValue({expr})"}.get(c.type, expr)


def _conv(c, expr: str) -> str:
    return {"uuid": f"ApiConvert.ToUuid({expr})", "int": f"ApiConvert.ToInt({expr})", "bigint": f"ApiConvert.ToBigint({expr})",
            "decimal": f"ApiConvert.ToDecimal({expr})", "date": f"ApiConvert.ToDate({expr})", "datetime": f"ApiConvert.ToDatetime({expr})",
            "json": f"ApiConvert.ToJsonText({expr})", "bool": f"(bool?){expr}"}.get(c.type, f"(string?){expr}")


def to_model(c, expr: str, nullable: bool) -> str:
    """Valore JSON già validato -> valore del modello (non nullo se la colonna non lo ammette)."""
    if c.type == "bool":
        return f"(bool?){expr}" if nullable else f"(bool){expr}!"
    if c.type in ("string", "text"):
        return f"(string?){expr}" if nullable else f"(string){expr}!"
    v = _conv(c, expr)
    if nullable:
        return v
    return f"{v}!.Value" if c.type in VALUE_TYPES else f"{v}!"


def _table_file(t: Table, ops: List[Operation], ns: str, model_ns: str, api_ns: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    exposed = [c for c in t.columns if not c.tenant and c.api_visible]
    writable = [c for c in exposed if not (c.primary_key and c.auto) and not c.generated]
    if t.mongo:
        read, write = "data.MongoReadAsync(call.Tenant, async db =>", "data.MongoWriteAsync(call.Tenant, async db =>"
    elif t.neo4j:
        read, write = "data.Neo4jReadAsync(call.Tenant, async db =>", "data.Neo4jWriteAsync(call.Tenant, async db =>"
    else:
        read, write = "data.ReadAsync(call.Tenant, async db =>", f'data.WriteAsync(new[] {{ "{n}" }}, call.Tenant, async db =>'
    key = to_model(t.pk, 'call.Path["id"]', False)
    nf = 'throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND")'
    b = [f"/// <summary>API REST di {n}: JSON &lt;-&gt; modello e controller delle operazioni generate (blocco api dello schema).</summary>",
         f"public static class {n}Api", "{", f"    /// <summary>{n} nel formato del contratto (senza tenant).</summary>",
         f"    public static Dictionary<string, object?> ToJson({n} e) => new()", "    {"]
    b += [f'        ["{prop(c.name)}"] = {to_json(c, "e." + member(L, c.name))},' for c in exposed]
    b += ["    };"]
    if any(o.kind in ("create", "update") for o in ops):
        b += ["", "    /// <summary>Campi presenti nel corpo (già validato) come valori del modello.</summary>",
              f"    internal static void Apply({n} e, object? body)", "    {", "        var m = (IReadOnlyDictionary<string, object?>)body!;"]
        for c in writable:
            p = prop(c.name)
            b.append(f'        if (m.TryGetValue("{p}", out var {p}Value)) e.{member(L, c.name)} = {to_model(c, p + "Value", c.nullable)};')
        b.append("    }")
    reg = []
    for op in ops:
        fn = pascal(op.op_id)
        reg.append((op.op_id, fn))
        b += ["", f"    /// <summary>{op.method.upper()} {op.path}: {op.summary}.</summary>", f"    public static async Task<object?> {fn}(ApiData data, Call call)", "    {"]
        if op.kind == "list":
            expandable = [r for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable] if (t.api and t.api.expandable and not t.mongo and not t.neo4j) else []
            if expandable:
                exp_allowed = ", ".join(f'"{prop(r.name)}"' for r in expandable)
                exp_map_entries = ", ".join(f'{{ "{prop(r.name)}", "{r.name}" }}' for r in expandable)
                b += [f'        var expandRaw = call.Query.TryGetValue("expand", out var ev) ? (string?)ev ?? "" : "";',
                      f"        var expand = string.IsNullOrWhiteSpace(expandRaw) ? Array.Empty<string>() : expandRaw.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).ToArray();",
                      f"        var allowedExpand = new HashSet<string> {{ {exp_allowed} }};",
                      f"        var bad = expand.Where(x => !allowedExpand.Contains(x)).ToArray();",
                      f'        if (bad.Length > 0) throw new ApiError("VALIDATION", $"invalid expand: {{string.Join(", ", bad)}}");',
                      f"        var expMap = new Dictionary<string, string> {{ {exp_map_entries} }};",
                      f"        var modelExpand = expand.Select(x => expMap[x]).ToList();",
                      f"        return await {read}",
                      f"        {{",
                      f"            var repo = new {repo}(db);",
                      f"            var p = modelExpand.Count > 0 ? await repo.ListPageExpandAsync(modelExpand, ApiConvert.Request(call.Query)) : await repo.ListPageAsync(ApiConvert.Request(call.Query));"]
                b.append(f"            return ApiConvert.PageJson(p, e =>")
                b.append(f"            {{")
                b.append(f"                var d = ToJson(e);")
                b.append(f"                foreach (var rel in expand)")
                b.append(f"                {{")
                for r in expandable:
                    target_conv = "ToJson" if r.target == n else f"{r.target}Api.ToJson"
                    fk_nullable = t.col(r.foreign_key).nullable
                    if fk_nullable:
                        b.append(f'                    if (rel == "{prop(r.name)}") {{ var v = e.{member(L, r.name)}; d["{prop(r.name)}"] = v != null ? {target_conv}(v) : null; }}')
                    else:
                        b.append(f'                    if (rel == "{prop(r.name)}") d["{prop(r.name)}"] = {target_conv}(e.{member(L, r.name)});')
                b += ["                }",
                      "                return d;",
                      "            });",
                      "        });"]
            else:
                b.append(f"        return await {read} ApiConvert.PageJson(await new {repo}(db).ListPageAsync(ApiConvert.Request(call.Query)), ToJson));")
        elif op.kind == "get":
            b.append(f"        return await {read} ToJson(await new {repo}(db).GetByIdAsync({key}) ?? {nf}));")
        elif op.kind == "create":
            b += [f"        var body = await {write}", "        {", f"            var e = new {n}();", "            Apply(e, call.Body);",
                  f"            return ToJson(await new {repo}(db).CreateAsync(e));", "        });",
                  "        return ApiResponse.Reply(201, body, new Dictionary<string, string> { [\"content-type\"] = \"application/json\", "
                  f'["location"] = call.BasePath + "{op.path}/" + body["{prop(t.pk.name)}"] }});']
        elif op.kind == "update":
            b += [f"        return await {write}", "        {", f"            var repo = new {repo}(db);",
                  f"            var e = await repo.GetByIdAsync({key}) ?? {nf};", "            Apply(e, call.Body);",
                  "            return ToJson(await repo.UpdateAsync(e));", "        });"]
        elif op.kind == "delete":
            b += [f"        await {write}", "        {", f"            if (!await new {repo}(db).DeleteAsync({key})) {nf};", "            return true;", "        });",
                  "        return ApiResponse.Reply(204);"]
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            args = []
            for c in q.where:
                if not c.param:
                    continue
                col = t.col(c.column)
                v = f'call.Query["{member("java", c.param)}"]'
                if c.op == "in":
                    args.append(f"ApiConvert.Each({v}, x => {to_model(col, 'x', False)})")
                else:
                    args.append(to_model(col, v, False))
            if q.returns == "page":
                args.append("ApiConvert.Request(call.Query)")
            meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
            call = f"await new {repo}(db).{meth}({', '.join(args)})"
            if q.returns == "page":
                b.append(f"        return await {read} ApiConvert.PageJson({call}, ToJson));")
            elif q.returns == "list":
                b.append(f"        return await {read} ({call}).Select(x => (object?)ToJson(x)).ToList());")
            else:
                b.append(f"        return await {read} ToJson({call} ?? {nf}));")
        elif op.kind == "rel":
            r = next(x for x in t.relations if x.name == op.arg)
            b += [f"        return await {read}", "        {", f"            var repo = new {repo}(db);"]
            if r.kind == "many_to_one":
                b.append(f"            return {r.target}Api.ToJson(await repo.{method_name(L, 'get_rel:' + r.name)}({key}) ?? {nf});")
            else:
                b += [f"            if (!await repo.ExistsAsync({key})) {nf};",
                      f"            return ApiConvert.PageJson(await repo.{method_name(L, 'list_rel:' + r.name)}({key}, ApiConvert.Request(call.Query)), {r.target}Api.ToJson);"]
            b.append("        });")
        b.append("    }")
    if ops:
        b += ["", "    /// <summary>Controller delle operazioni di questa tabella.</summary>",
              "    internal static void Register(IDictionary<string, Func<ApiData, Call, Task<object?>>> output)", "    {"]
        b += [f'        output["{i}"] = {f};' for i, f in reg]
        b.append("    }")
    b.append("}")
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n"), "// <auto-generated />", rt.USINGS.rstrip("\n"), f"using {model_ns};", f"using {api_ns};", "",
         f"namespace {ns};", ""] + b
    return "\n".join(o) + "\n"


def _custom_file(ops: List[Operation], ns: str) -> str:
    o = [header(L, "schemas/openapi.yaml").rstrip("\n"), "// <auto-generated />", "#nullable enable", "using System.Threading.Tasks;", "",
         f"namespace {ns};", "", "/// <summary>",
         "/// Endpoint custom del contratto (schemas/openapi.yaml): un metodo per operationId, da implementare nel service.",
         "/// Ogni metodo riceve il Call con path, query e body già validati e l'identità; restituisce il corpo JSON della",
         "/// risposta (stato del contratto) o ApiResponse.Reply(stato, corpo). Gli errori applicativi si sollevano con ApiError.",
         "/// </summary>", "public interface IOperations", "{"]
    for i, op in enumerate(ops):
        ins = ", ".join(f"{p.loc} {p.name}" for p in op.params) + (", body" if op.body is not None else "")
        o += ([""] if i else []) + [f"    /// <summary>{op.method.upper()} {op.path} ({op.context}): {op.summary}." + (f" Input: {ins}." if ins else "") + "</summary>",
                                    f"    Task<object?> {pascal(op.op_id)}(Call call);"]
    o.append("}")
    return "\n".join(o) + "\n"


def _specs_file(ops: List[Operation], ns: str) -> str:
    o = [header(L, "schemas/generated/openapi.yaml").rstrip("\n"), "// <auto-generated />", "#nullable enable", "using System.Collections.Generic;", "",
         f"namespace {ns};", "", "/// <summary>Operazioni del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo.</summary>",
         "public static class Specs", "{", "    public static readonly IReadOnlyList<Spec> All = new[]", "    {"]
    o += [f"        Spec.Of({rt.cstr(json.dumps(op_spec(op), ensure_ascii=False))})," for op in ops]
    o += ["    };", "}"]
    return "\n".join(o) + "\n"


def _index_file(tables: Dict[str, Table], ops: List[Operation], ac: Dict, ns: str, ctrl_ns: str) -> str:
    registered = [n for n in tables if any(o.table == n for o in ops)]
    custom = [o for o in ops if o.kind == "custom"]
    o = [header(L, "kit").rstrip("\n"), "// <auto-generated />", rt.USINGS.rstrip("\n"), f"using {ctrl_ns};", "", f"namespace {ns};", "",
         "/// <summary>API REST generate: Build(data, custom, contexts) -> ApiRouter; adattatori LambdaAdapter e AspNetAdapter (MapKybesApi).</summary>",
         "public static class KybesApi", "{", f"    public const string BasePath = {rt.cstr(ac.get('base_path', ''))};", "",
         "    private static readonly Dictionary<string, Func<ApiData, Call, Task<object?>>> Controllers = Load();"]
    if custom:
        o += ["", "    private static readonly Dictionary<string, Func<IOperations, Handler>> Custom = new()", "    {"]
        o += [f'        ["{x.op_id}"] = c => c.{pascal(x.op_id)},' for x in custom]
        o.append("    };")
    o += ["", "    private static Dictionary<string, Func<ApiData, Call, Task<object?>>> Load()", "    {",
          "        var output = new Dictionary<string, Func<ApiData, Call, Task<object?>>>();"]
    o += [f"        {n}Api.Register(output);" for n in registered]
    o += ["        return output;", "    }", ""]
    cparam = "IOperations? custom, " if custom else ""
    o += ["    /// <summary>ApiRouter con le operazioni dei contesti indicati (tutti se null)" + ("; custom implementa i metodi di IOperations" if custom else "") + ".</summary>",
          f"    public static ApiRouter Build(ApiData data, {cparam}IReadOnlyCollection<string>? contexts = null, string basePath = BasePath)", "    {",
          "        var handlers = new Dictionary<string, Handler>();", "        var chosen = new List<Spec>();", "        foreach (var spec in Specs.All)", "        {",
          "            if (contexts is not null && !contexts.Contains(spec.Context)) continue;"]
    if custom:
        o += ['            if (spec.Kind == "custom")', "            {",
              '                if (custom is null) throw new ArgumentException("manca l\'implementazione di IOperations per l\'operazione " + spec.Id);',
              "                handlers[spec.Id] = Custom[spec.Id](custom);", "            }", "            else", "            {",
              "                var c = Controllers[spec.Id];", "                handlers[spec.Id] = call => c(data, call);", "            }"]
    else:
        o += ["            var c = Controllers[spec.Id];", "            handlers[spec.Id] = call => c(data, call);"]
    o += ["            chosen.Add(spec);", "        }", "        return new ApiRouter(chosen, handlers, basePath);", "    }", "}"]
    return "\n".join(o) + "\n"


def emit(tables: Dict[str, Table], ops: List[Operation], ac: Dict, opts: Dict):
    """Restituisce (api_files, controller_files): file separati per il layer HTTP e per i controller."""
    model_ns = opts["namespace"]
    api_ns = api_namespace(model_ns)
    ctrl_ns = controller_namespace(model_ns)
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    rt_all = rt.files(api_ns, model_ns, sql, mongo, ac["claims"], ac["headers"])
    api_rt_keys = {"Json.cs", "JsonSchema.cs", "Http.cs", "IdentityReader.cs", "Router.cs", "LambdaAdapter.cs", "AspNetAdapter.cs"}
    ctrl_rt_keys = {"ApiData.cs", "ApiConvert.cs"}
    hdr = header(L, "kit").rstrip("\n") + "\n// <auto-generated />\n"
    api_files = {f"generated/{k}": hdr + v for k, v in rt_all.items() if k in api_rt_keys}
    ctrl_files = {}
    for k, v in rt_all.items():
        if k not in ctrl_rt_keys:
            continue
        text = v.replace(f"namespace {api_ns};", f"namespace {ctrl_ns};", 1)
        if k == "ApiConvert.cs":
            text = text.replace(f"namespace {ctrl_ns};", f"using {api_ns};\n\nnamespace {ctrl_ns};", 1)
        ctrl_files[f"generated/{k}"] = hdr + text
    api_files["generated/Specs.cs"] = _specs_file(ops, api_ns)
    targets = rel_targets(tables, ops)
    for n, t in tables.items():
        tops = [o for o in ops if o.table == n]
        if tops or n in targets:
            ctrl_files[f"generated/{n}Api.cs"] = _table_file(t, tops, ctrl_ns, model_ns, api_ns)
    if any(o.kind == "custom" for o in ops):
        api_files["generated/IOperations.cs"] = _custom_file([o for o in ops if o.kind == "custom"], api_ns)
    api_files["generated/KybesApi.cs"] = _index_file(tables, ops, ac, api_ns, ctrl_ns)
    return api_files, ctrl_files
