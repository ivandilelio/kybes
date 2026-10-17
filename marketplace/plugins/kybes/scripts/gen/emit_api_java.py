"""Emettitore delle API Java: operazioni del contratto (Specs), controller CRUD per tabella, interfaccia dei metodi custom."""
from __future__ import annotations

import json
from typing import Dict, List

import runtime_api_java as rt
from api_plan import Operation, op_spec, prop
from emit_api_python import rel_targets
from naming import header, member, method_name, repo_class
from schema import Table
from sqlonly import has_sql

L = "java"


def api_package(model_pkg: str) -> str:
    """Pacchetto delle API accanto al modello: app.model -> app.api (come la cartella: model -> api)."""
    head, _, last = model_pkg.rpartition(".")
    return (f"{head}.api" if head else "api") if last == "model" else f"{model_pkg}_api"


def controller_package(model_pkg: str) -> str:
    """Pacchetto dei controller: app.model -> app.controllers."""
    head, _, last = model_pkg.rpartition(".")
    return (f"{head}.controllers" if head else "controllers") if last == "model" else f"{model_pkg}_controllers"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _get(c) -> str:
    return f"e.get{_cap(member(L, c.name))}()"


def to_json(c, expr: str) -> str:
    return {"uuid": f"Convert.uuidText({expr})", "bigint": f"Convert.text({expr})", "decimal": f"Convert.decimalText({expr}, {c.scale})",
            "date": f"Convert.dateText({expr})", "datetime": f"Convert.datetimeText({expr})", "json": f"Convert.jsonValue({expr})"}.get(c.type, expr)


def to_model(c, expr: str) -> str:
    return {"uuid": f"Convert.toUuid({expr})", "int": f"Convert.toInt({expr})", "bigint": f"Convert.toBigint({expr})",
            "decimal": f"Convert.toDecimal({expr})", "date": f"Convert.toDate({expr})", "datetime": f"Convert.toDatetime({expr})",
            "json": f"Convert.toJsonText({expr})", "bool": f"(Boolean) {expr}"}.get(c.type, f"(String) {expr}")


def _conv_fn(c) -> str:
    return {"uuid": "Convert::toUuid", "int": "Convert::toInt", "bigint": "Convert::toBigint", "decimal": "Convert::toDecimal",
            "date": "Convert::toDate", "datetime": "Convert::toDatetime", "bool": "x -> (Boolean) x"}.get(c.type, "x -> (String) x")


def _table_file(t: Table, tables: Dict[str, Table], ops: List[Operation], api_pkg: str, ctrl_pkg: str, model_pkg: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    exposed = [c for c in t.columns if not c.tenant]
    writable = [c for c in exposed if not (c.primary_key and c.auto) and not c.generated]
    read, write = ("data.mongoRead(call.tenant(), ", "data.mongoWrite(call.tenant(), ") if t.mongo else \
        ("data.read(call.tenant(), ", f'data.write(List.of("{n}"), call.tenant(), ')
    targets = sorted({next(r for r in t.relations if r.name == o.arg).target for o in ops if o.kind == "rel"} - {n})
    key = to_model(t.pk, 'call.path().get("id")')
    b = [f"/** API REST di {n}: JSON &lt;-&gt; modello e controller delle operazioni generate (blocco api dello schema). */",
         f"public final class {n}Api {{", "", f"    private {n}Api() {{", "    }", "",
         f"    /** {n} nel formato del contratto (senza tenant). */", f"    public static Map<String, Object> toJson({n} e) {{",
         "        Map<String, Object> out = new LinkedHashMap<>();"]
    b += [f'        out.put("{prop(c.name)}", {to_json(c, _get(c))});' for c in exposed]
    b += ["        return out;", "    }"]
    if any(o.kind in ("create", "update") for o in ops):
        b += ["", "    /** Campi presenti nel corpo (già validato) come valori del modello. */", "    @SuppressWarnings(\"unchecked\")",
              f"    static void apply({n} e, Object body) {{", "        Map<String, Object> m = (Map<String, Object>) body;"]
        for c in writable:
            p = prop(c.name)
            b.append(f'        if (m.containsKey("{p}")) e.set{_cap(member(L, c.name))}({to_model(c, f"m.get({json.dumps(p)})")});')
        b.append("    }")
    reg = []
    for op in ops:
        fn = op.op_id
        reg.append(fn)
        b += ["", f"    /** {op.method.upper()} {op.path}: {op.summary}. */", f"    public static Object {fn}(ApiData data, Call call) {{"]
        if op.kind == "list":
            b.append(f"        return {read}em -> Convert.page(new {repo}(em).listPage(Convert.request(call.query())), {n}Api::toJson));")
        elif op.kind == "get":
            b += [f"        return {read}em -> toJson(new {repo}(em).getById({key})",
                  '                .orElseThrow(() -> new ApiError("NOT_FOUND", "RECORD_NOT_FOUND"))));']
        elif op.kind == "create":
            b += [f"        Map<String, Object> body = {write}em -> {{", f"            {n} e = new {n}();", "            apply(e, call.body());",
                  f"            return toJson(new {repo}(em).create(e));", "        });",
                  f'        return ApiResponse.reply(201, body, Map.of("content-type", "application/json", "location", call.basePath() + "{op.path}/" + body.get("{prop(t.pk.name)}")));']
        elif op.kind == "update":
            b += [f"        return {write}em -> {{", f"            {repo} repo = new {repo}(em);",
                  f'            {n} e = repo.getById({key}).orElseThrow(() -> new ApiError("NOT_FOUND", "RECORD_NOT_FOUND"));',
                  "            apply(e, call.body());", "            return toJson(repo.update(e));", "        });"]
        elif op.kind == "delete":
            b += [f"        {write}em -> {{", f'            if (!new {repo}(em).delete({key})) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");',
                  "            return null;", "        });", "        return ApiResponse.reply(204);"]
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            args = []
            for c in q.where:
                if not c.param:
                    continue
                col = t.col(c.column)
                v = f'call.query().get("{member(L, c.param)}")'
                args.append(f"Convert.each({v}, {_conv_fn(col)})" if c.op == "in" else to_model(col, v))
            if q.returns == "page":
                args.append("Convert.request(call.query())")
            meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
            call = f"new {repo}(em).{meth}({', '.join(args)})"
            if q.returns == "page":
                b.append(f"        return {read}em -> Convert.page({call}, {n}Api::toJson));")
            elif q.returns == "list":
                b.append(f"        return {read}em -> {call}.stream().map({n}Api::toJson).toList());")
            else:
                b += [f"        return {read}em -> toJson({call}", '                .orElseThrow(() -> new ApiError("NOT_FOUND", "RECORD_NOT_FOUND"))));']
        elif op.kind == "rel":
            r = next(x for x in t.relations if x.name == op.arg)
            conv = f"{r.target}Api::toJson"
            b += [f"        return {read}em -> {{", f"            {repo} repo = new {repo}(em);"]
            if r.kind == "many_to_one":
                b += [f"            return {r.target}Api.toJson(repo.{method_name(L, 'get_rel:' + r.name)}({key})",
                      '                    .orElseThrow(() -> new ApiError("NOT_FOUND", "RECORD_NOT_FOUND")));']
            else:
                b += [f'            if (!repo.exists({key})) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");',
                      f"            return Convert.page(repo.{method_name(L, 'list_rel:' + r.name)}({key}, Convert.request(call.query())), {conv});"]
            b.append("        });")
        b.append("    }")
    if ops:
        b += ["", "    /** Controller delle operazioni di questa tabella. */", "    public static void register(Map<String, Controller> out) {"]
        b += [f'        out.put("{fn}", {n}Api::{fn});' for fn in reg]
        b.append("    }")
    b.append("}")
    body = "\n".join(b)
    imports = [f"import {model_pkg}.generated.{n};", "import java.util.LinkedHashMap;", "import java.util.Map;"]
    if ops:
        imports.append(f"import {model_pkg}.{repo};")
        imports.append(f"import {api_pkg}.generated.ApiError;")
        imports.append(f"import {api_pkg}.generated.Call;")
        imports.append(f"import {api_pkg}.generated.Controller;")
    if any(op.kind in ("create", "delete") for op in ops):
        imports.append(f"import {api_pkg}.generated.ApiResponse;")
    if "List.of(" in body:
        imports.append("import java.util.List;")
    for tg in targets:
        pass  # stesso pacchetto: <Target>Api senza import
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n"), f"package {ctrl_pkg}.generated;", ""] + sorted(imports) + ["", body]
    return "\n".join(o) + "\n"


def _custom_file(ops: List[Operation], api_pkg: str) -> str:
    o = [header(L, "schemas/openapi.yaml").rstrip("\n"), f"package {api_pkg}.generated;", "",
         "/**", " * Endpoint custom del contratto (schemas/openapi.yaml): un metodo per operationId, da implementare nel service.",
         " * Ogni metodo riceve il Call con path, query e body già validati e l'identità; restituisce il corpo JSON della",
         " * risposta (stato del contratto) o ApiResponse.reply(stato, corpo). Gli errori applicativi si sollevano con ApiError.",
         " */", "public interface Operations {"]
    for op in ops:
        ins = ", ".join(f"{p.loc} {p.name}" for p in op.params) + (", body" if op.body is not None else "")
        o += ["", f"    /** {op.method.upper()} {op.path} ({op.context}): {op.summary}." + (f" Input: {ins}." if ins else "") + " */",
              f"    Object {op.op_id}(Call call);"]
    o.append("}")
    return "\n".join(o) + "\n"


def _specs_file(ops: List[Operation], api_pkg: str) -> str:
    o = [header(L, "schemas/generated/openapi.yaml").rstrip("\n"), f"package {api_pkg}.generated;", "", "import java.util.List;", "",
         "/** Operazioni del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo. */",
         "public final class Specs {", "",
         "    public static final List<Spec> ALL = List.of(" + ", ".join(f"op{i}()" for i in range(len(ops))) + ");", "",
         "    private Specs() {", "    }"]
    for i, op in enumerate(ops):
        o += ["", f"    private static Spec op{i}() {{", f"        return Spec.of({rt.jstr(json.dumps(op_spec(op), ensure_ascii=False))});", "    }"]
    o.append("}")
    return "\n".join(o) + "\n"


def _index_file(tables: Dict[str, Table], ops: List[Operation], ac: Dict, api_pkg: str, ctrl_pkg: str) -> str:
    registered = [n for n in tables if any(o.table == n for o in ops)]
    custom = [o for o in ops if o.kind == "custom"]
    o = [header(L, "kit").rstrip("\n"), f"package {api_pkg}.generated;", "", "import java.util.ArrayList;", "import java.util.HashMap;",
         "import java.util.List;", "import java.util.Map;"]
    if custom:
        o.append("import java.util.function.Function;")
    o.append(f"import {ctrl_pkg}.generated.ApiData;")
    for rn in registered:
        o.append(f"import {ctrl_pkg}.generated.{rn}Api;")
    o += ["", "/** API REST generate: build(data, custom, contexts) -> Api; adattatori LambdaAdapter, HttpServerAdapter e SpringAdapter. */",
          "public final class KybesApi {", "", f"    public static final String BASE_PATH = {rt.jstr(ac.get('base_path', ''))};", "",
          "    private static final Map<String, Controller> CONTROLLERS = new HashMap<>();"]
    if custom:
        o += ["    private static final Map<String, Function<Operations, Handler>> CUSTOM = Map.ofEntries("]
        o += [f'            Map.entry("{x.op_id}", c -> c::{x.op_id}){"," if i < len(custom) - 1 else ");"}' for i, x in enumerate(custom)]
    o += ["", "    static {"] + [f"        {n}Api.register(CONTROLLERS);" for n in registered] + ["    }", "",
                                                                                               "    private KybesApi() {", "    }", ""]
    cparam = "Operations custom, " if custom else ""
    carg = "custom, " if custom else ""
    o += ["    /** Api con le operazioni dei contesti indicati (tutti se null)" + ("; custom implementa i metodi di Operations" if custom else "") + ". */",
          f"    public static Api build(ApiData data, {cparam}List<String> contexts, String basePath) {{",
          "        Map<String, Handler> handlers = new HashMap<>();", "        List<Spec> chosen = new ArrayList<>();", "        for (Spec spec : Specs.ALL) {",
          "            if (contexts != null && !contexts.contains(spec.context())) continue;"]
    if custom:
        o += ['            if (spec.kind().equals("custom")) {',
              '                if (custom == null) throw new IllegalArgumentException("manca l\'implementazione di Operations per l\'operazione " + spec.id());',
              "                handlers.put(spec.id(), CUSTOM.get(spec.id()).apply(custom));", "            } else {",
              "                Controller c = CONTROLLERS.get(spec.id());", "                handlers.put(spec.id(), call -> c.handle(data, call));", "            }"]
    else:
        o += ["            Controller c = CONTROLLERS.get(spec.id());", "            handlers.put(spec.id(), call -> c.handle(data, call));"]
    o += ["            chosen.add(spec);", "        }", "        return new Api(chosen, handlers, basePath);", "    }", "",
          f"    public static Api build(ApiData data, {cparam}List<String> contexts) {{", f"        return build(data, {carg}contexts, BASE_PATH);", "    }", "",
          f"    public static Api build(ApiData data{', Operations custom' if custom else ''}) {{", f"        return build(data, {carg}null, BASE_PATH);", "    }", "}"]
    return "\n".join(o) + "\n"


def emit(tables: Dict[str, Table], ops: List[Operation], ac: Dict, opts: Dict):
    """Restituisce (api_files, controller_files): file separati per il layer HTTP e per i controller."""
    model_pkg = opts["package"]
    api_pkg = api_package(model_pkg)
    ctrl_pkg = controller_package(model_pkg)
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    rt_files = rt.files(f"{api_pkg}.generated", model_pkg, sql, mongo, ac["claims"], ac["headers"])
    ctrl_rt_keys = {"ApiData.java", "Convert.java"}
    api_files: Dict[str, str] = {}
    ctrl_files: Dict[str, str] = {}
    for k, v in rt_files.items():
        text = header(L, "kit").rstrip("\n") + "\n" + v
        if k in ctrl_rt_keys:
            text = text.replace(f"package {api_pkg}.generated;", f"package {ctrl_pkg}.generated;", 1)
            if k == "Convert.java":
                text = text.replace(f"package {ctrl_pkg}.generated;\n",
                                    f"package {ctrl_pkg}.generated;\n\nimport {api_pkg}.generated.Json;\n", 1)
            ctrl_files[f"generated/{k}"] = text
        else:
            api_files[f"generated/{k}"] = text
    # Controller.java (interfaccia funzionale) resta nelle API ma referenzia ApiData nei controller
    if "generated/Controller.java" in api_files:
        ct = api_files["generated/Controller.java"]
        ct = ct.replace(f"package {api_pkg}.generated;\n",
                        f"package {api_pkg}.generated;\n\nimport {ctrl_pkg}.generated.ApiData;\n", 1)
        api_files["generated/Controller.java"] = ct
    api_files["generated/Specs.java"] = _specs_file(ops, api_pkg)
    targets = rel_targets(tables, ops)
    for n, t in tables.items():
        tops = [o for o in ops if o.table == n]
        if tops or n in targets:
            ctrl_files[f"generated/{n}Api.java"] = _table_file(t, tables, tops, api_pkg, ctrl_pkg, model_pkg)
    if any(o.kind == "custom" for o in ops):
        api_files["generated/Operations.java"] = _custom_file([o for o in ops if o.kind == "custom"], api_pkg)
    api_files["generated/KybesApi.java"] = _index_file(tables, ops, ac, api_pkg, ctrl_pkg)
    return api_files, ctrl_files
