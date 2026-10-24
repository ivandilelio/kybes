"""Emettitore delle API TypeScript: operazioni del contratto, controller CRUD per tabella, interfaccia dei metodi custom."""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

import runtime_api_typescript as rt
from api_plan import Operation, op_spec, prop
from emit_api_python import rel_targets
from naming import header, member, method_name, repo_class
from schema import Table, camel
from sqlonly import has_sql

L = "typescript"


def _to_json(c, expr: str) -> str:
    if c.type == "uuid":
        return f"uuidText({expr})"
    if c.type == "bigint":
        return f"text({expr})"
    if c.type == "decimal":
        return f"decimalText({expr}, {c.scale})"
    if c.type == "date":
        return f"dateText({expr})"
    if c.type == "datetime":
        return f"datetimeText({expr})"
    return expr


def _to_model(c, expr: str) -> str:
    if c.type == "uuid":
        return f"toUuid({expr})"
    if c.type == "datetime":
        return f"toDatetime({expr})"
    return expr


def _ts_relpath(from_dir: str, to_dir: str) -> str:
    """Percorso relativo per import TypeScript."""
    parts_from = from_dir.split("/")
    parts_to = to_dir.split("/")
    common = 0
    for a, b in zip(parts_from, parts_to):
        if a != b:
            break
        common += 1
    ups = len(parts_from) - common
    return "/".join([".."] * ups + parts_to[common:])


def _table_file(t: Table, tables: Dict[str, Table], ops: List[Operation], api_rel: str, model_base: str, model_gen: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    exposed = [c for c in t.columns if not c.tenant and c.api_visible]
    writable = [c for c in exposed if not (c.primary_key and c.auto) and not c.generated]
    read, write = ("data.mongoRead", "data.mongoWrite") if t.mongo else ("data.neo4jRead", "data.neo4jWrite") if t.neo4j else ("data.read", "data.write")
    expand_targets = {r.target for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable} if t.api and t.api.expandable else set()
    targets = sorted(({next(r for r in t.relations if r.name == o.arg).target for o in ops if o.kind == "rel"} | expand_targets) - {n})
    paged = any(o.kind == "list" or (o.kind == "query" and next(q for q in t.queries if q.name == o.arg).returns == "page")
                or (o.kind == "rel" and next(r for r in t.relations if r.name == o.arg).kind == "one_to_many") for o in ops)
    b = ["", f"/** {n} nel formato del contratto (senza tenant). */", f"export function toJson(e: {n}): Record<string, unknown> {{", "  return {"]
    b += [f"    {prop(c.name)}: {_to_json(c, 'e.' + member(L, c.name))}," for c in exposed]
    b += ["  };", "}", ""]
    if any(o.kind in ("create", "update") for o in ops):
        b += ["/** Campi presenti nel corpo (già validato) come valori del modello. */",
              "function values(body: Record<string, any>): Record<string, unknown> {", "  const out: Record<string, unknown> = {};"]
        for c in writable:
            b.append(f'  if ("{prop(c.name)}" in body) out.{member(L, c.name)} = {_to_model(c, "body." + prop(c.name))};')
        b += ["  return out;", "}", ""]
    if paged:
        b += ["function page<T>(p: Page<T>, conv: (x: T) => unknown): unknown {",
              "  return { items: p.items.map(conv), nextCursor: p.nextCursor, limit: p.limit };", "}", "",
              "function request(q: Record<string, unknown>): PageRequest {",
              "  return { limit: q.limit as number | undefined, cursor: q.cursor as string | undefined, sort: q.sort as string | undefined };", "}", ""]
    key = "toUuid(call.path.id) as string" if t.pk.type == "uuid" else f"call.path.id as {'number' if t.pk.type == 'int' else 'string'}"
    handlers = []
    write_args = f'["{n}"], call.tenant' if not t.mongo else "call.tenant"
    for op in ops:
        fn = camel(op.op_id)
        handlers.append((op.op_id, fn))
        b += [f"/** {op.method.upper()} {op.path}: {op.summary}. */", f"export async function {fn}(data: ApiData, call: Call): Promise<unknown> {{"]
        if op.kind == "list":
            expandable = [r for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable] if (t.api and t.api.expandable and not t.mongo and not t.neo4j) else []
            if expandable:
                exp_allowed_ts = ", ".join(f'"{prop(r.name)}"' for r in expandable)
                exp_map_ts = ", ".join(f'{prop(r.name)}: "{r.name}"' for r in expandable)
                b += [f'  const expandRaw = (call.query.expand as string) || "";',
                      f"  const expand = expandRaw ? expandRaw.split(\",\").map(s => s.trim()).filter(Boolean) : [];",
                      f"  const allowedExpand = new Set([{exp_allowed_ts}]);",
                      f"  const bad = expand.filter(x => !allowedExpand.has(x));",
                      f'  if (bad.length) throw new ApiError("VALIDATION", "invalid expand: " + bad.join(", "));',
                      f"  const expMap: Record<string, string> = {{ {exp_map_ts} }};",
                      f"  const modelExpand = expand.map(x => expMap[x]);",
                      f"  return {read}(call.tenant, async (em) => {{",
                      f"    const repo = new {repo}(em);",
                      f"    const p = modelExpand.length ? await repo.listPageExpand(modelExpand, request(call.query)) : await repo.listPage(request(call.query));"]
                b.append(f"    const conv = (e: {n}): Record<string, unknown> => {{")
                b.append(f"      const d = toJson(e);")
                b.append(f"      for (const rel of expand) {{")
                for r in expandable:
                    target_conv = "toJson" if r.target == n else f"{camel(r.target)}Json"
                    b.append(f'        if (rel === "{prop(r.name)}") {{ const v = (e as any).{member(L, r.name)}; (d as any)["{prop(r.name)}"] = v != null ? {target_conv}(v) : null; }}')
                b += ["      }", "      return d;", "    };",
                      f"    return page(p, expand.length ? conv : toJson);",
                      "  });"]
            else:
                b.append(f"  return {read}(call.tenant, async (em) => page(await new {repo}(em).listPage(request(call.query)), toJson));")
        elif op.kind == "get":
            b += [f"  return {read}(call.tenant, async (em) => {{", f"    const e = await new {repo}(em).getById({key});",
                  '    if (e === null) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', "    return toJson(e);", "  });"]
        elif op.kind == "create":
            b += [f"  const body = await {write}({write_args}, async (em) => toJson(await new {repo}(em).create(values(call.body as Record<string, unknown>) as never)));",
                  f'  return reply(201, body, {{ "content-type": "application/json", location: call.basePath + "{op.path}/" + String(body.{prop(t.pk.name)}) }});']
        elif op.kind == "update":
            b += [f"  return {write}({write_args}, async (em) => {{",
                  f"    const e = await new {repo}(em).update({key}, values(call.body as Record<string, unknown>) as never);",
                  '    if (e === null) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', "    return toJson(e);", "  });"]
        elif op.kind == "delete":
            b += [f"  await {write}({write_args}, async (em) => {{",
                  f'    if (!(await new {repo}(em).delete({key}))) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', "  });", "  return reply(204);"]
        elif op.kind == "query":
            q = next(x for x in t.queries if x.name == op.arg)
            args = []
            for c in q.where:
                if not c.param:
                    continue
                col = t.col(c.column)
                v = f"call.query.{camel(c.param)}"
                ts = {"int": "number", "bool": "boolean", "datetime": "Date"}.get(col.type, "string")
                if c.op == "in":
                    args.append(f"({v} as unknown[]).map((x) => {_to_model(col, 'x')}) as {ts}[]")
                else:
                    args.append(f"{_to_model(col, v)} as {ts}")
            if q.returns == "page":
                args.append("request(call.query)")
            meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
            call = f"await new {repo}(em).{meth}({', '.join(args)})"
            if q.returns == "page":
                b.append(f"  return {read}(call.tenant, async (em) => page({call}, toJson));")
            elif q.returns == "list":
                b.append(f"  return {read}(call.tenant, async (em) => ({call}).map(toJson));")
            else:
                b += [f"  return {read}(call.tenant, async (em) => {{", f"    const e = {call};",
                      '    if (e === null) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', "    return toJson(e);", "  });"]
        elif op.kind == "rel":
            r = next(x for x in t.relations if x.name == op.arg)
            conv = "toJson" if r.target == n else f"{camel(r.target)}Json"
            b += [f"  return {read}(call.tenant, async (em) => {{", f"    const repo = new {repo}(em);"]
            if r.kind == "many_to_one":
                b += [f"    const e = await repo.{method_name(L, 'get_rel:' + r.name)}({key});",
                      '    if (e === null) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', f"    return {conv}(e);"]
            else:
                b += [f'    if (!(await repo.exists({key}))) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");',
                      f"    return page(await repo.{method_name(L, 'list_rel:' + r.name)}({key}, request(call.query)), {conv});"]
            b.append("  });")
        b += ["}", ""]
    b.append("export const HANDLERS: Record<string, (data: ApiData, call: Call) => Promise<unknown>> = { " +
             ", ".join(f"{i}: {f}" for i, f in handlers) + " };")
    body = "\n".join(b)
    conv_names = sorted(x for x in ("dateText", "datetimeText", "decimalText", "text", "toDatetime", "toUuid", "uuidText") if f"{x}(" in body)
    o = [header(L, f"schemas/db/{n}.yaml").rstrip("\n") + "\n/* eslint-disable */",
         f"// Controller di {n}: JSON <-> modello e handler delle operazioni generate (blocco api dello schema)."]
    o.append(f'import {{ {n}, {repo} }} from "{model_base}/{n}";' if ops else f'import type {{ {n} }} from "{model_base}/{n}";')
    if paged:
        o.append(f'import type {{ Page, PageRequest }} from "{model_gen}/_paging";')
    if conv_names:
        o.append(f'import {{ {", ".join(conv_names)} }} from "./_convert";')
    http = [x for x in ("ApiError", "reply") if f"{'new ' if x == 'ApiError' else ''}{x}(" in body]
    if ops:
        o.append('import type { ApiData } from "./_data";')
    if http:
        o.append(f'import {{ {", ".join(http)} }} from "{api_rel}/_http";')
    if ops:
        o.append(f'import type {{ Call }} from "{api_rel}/_http";')
    for tg in targets:
        o.append(f'import {{ toJson as {camel(tg)}Json }} from "./{tg}";')
    if not ops:
        body = body.replace("export const HANDLERS: Record<string, (data: ApiData, call: Call) => Promise<unknown>> = {  };",
                            "export const HANDLERS: Record<string, never> = {};")
    return "\n".join(o) + "\n" + body + "\n"


def _custom_file(ops: List[Operation]) -> str:
    o = [header(L, "schemas/openapi.yaml").rstrip("\n") + "\n/* eslint-disable */",
         "// Endpoint custom del contratto (schemas/openapi.yaml): un metodo per operationId, da implementare nel service.",
         "// Ogni metodo riceve il Call con path, query e body già validati e l'identità; restituisce il corpo JSON della",
         "// risposta (stato del contratto) o reply(stato, corpo). Gli errori applicativi si sollevano con ApiError.",
         'import type { Call } from "./_http";', "", "export interface Operations {"]
    for op in ops:
        ins = ", ".join(f"{p.loc} {p.name}" for p in op.params) + (", body" if op.body is not None else "")
        o += [f"  /** {op.method.upper()} {op.path} ({op.context}): {op.summary}." + (f" Input: {ins}." if ins else "") + " */",
              f"  {camel(op.op_id)}(call: Call): unknown | Promise<unknown>;"]
    o.append("}")
    return "\n".join(o) + "\n"


def _index_file(tables: Dict[str, Table], ops: List[Operation], ac: Dict, ctrl_rel: str) -> str:
    exposed = [n for n in tables if any(o.table == n for o in ops) or n in rel_targets(tables, ops)]
    custom = any(o.kind == "custom" for o in ops)
    o = [header(L, "kit").rstrip("\n") + "\n/* eslint-disable */",
         "// API REST generate: buildApi(data, custom, contexts) -> Api; adattatori per Lambda, node:http e Fastify.",
         f'import {{ ApiData }} from "{ctrl_rel}/_data";', 'import { Api } from "./_router";', 'import type { Handler, Spec } from "./_router";',
         'import { SPECS } from "./operations";']
    if custom:
        o.append('import type { Operations } from "./custom";')
    for n in exposed:
        o.append(f'import {{ HANDLERS as {camel(n)} }} from "{ctrl_rel}/{n}";')
    o += ["", f'export {{ ApiData }} from "{ctrl_rel}/_data";', f'export type {{ ApiDataOptions }} from "{ctrl_rel}/_data";',
          'export { ApiError, reply } from "./_http";', 'export type { ApiRequest, ApiResponse, Call, Identity } from "./_http";',
          'export { Api } from "./_router";', 'export { lambdaHandler } from "./lambda";', 'export { httpHandler } from "./http";',
          'export { includeApi } from "./fastify";']
    if custom:
        o.append('export type { Operations } from "./custom";')
    o += ["", "const CONTROLLERS: Record<string, (data: ApiData, call: any) => Promise<unknown>> = { " + ", ".join(f"...{camel(n)}" for n in exposed) + " };",
          f"export const BASE_PATH = {json.dumps(ac.get('base_path', ''))};", "",
          "/** Api con le operazioni dei contesti indicati (tutti se omessi); custom implementa i metodi di Operations. */",
          f"export function buildApi(data: ApiData, custom: {'Operations | null' if custom else 'unknown'} = null, contexts: string[] | null = null, basePath = BASE_PATH): Api {{",
          "  const handlers: Record<string, Handler> = {};", "  const chosen: Spec[] = [];", "  for (const spec of SPECS) {",
          "    if (contexts !== null && !contexts.includes(spec.context)) continue;"]
    if custom:
        o += ['    if (spec.kind === "custom") {', "      const fn = (custom as unknown as Record<string, unknown> | null)?.[spec.id];",
              '      if (typeof fn !== "function") throw new TypeError(`manca il metodo ${spec.id} per l\'operazione ${spec.id} (Operations)`);',
              "      handlers[spec.id] = (call) => fn.call(custom, call);", "    } else {",
              "      handlers[spec.id] = (call) => CONTROLLERS[spec.id](data, call);", "    }"]
    else:
        o += ["    handlers[spec.id] = (call) => CONTROLLERS[spec.id](data, call);"]
    o += ["    chosen.push(spec);", "  }", "  return new Api(chosen, handlers, basePath);", "}"]
    if not custom:
        o.insert(o.index("  const handlers: Record<string, Handler> = {};"), "  void custom;")
    return "\n".join(o) + "\n"


def emit(tables: Dict[str, Table], ops: List[Operation], ac: Dict, opts: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Restituisce (api_files, controller_files): file separati per il layer HTTP e per i controller."""
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    api_dir = opts.get("api_dir", "api")
    ctrl_dir = opts.get("controller_dir", "controllers")
    model_dir = opts.get("model_dir", "model")
    rt_files = rt.files(sql, mongo, ac["claims"], ac["headers"])
    api_rt_keys = {"_schema.ts", "_http.ts", "_identity.ts", "_router.ts", "lambda.ts", "http.ts", "fastify.ts"}
    ctrl_rt_keys = {"_data.ts", "_convert.ts"}
    # percorso relativo da controllers/generated a model/generated per _data.ts
    model_rel = _ts_relpath(ctrl_dir + "/generated", model_dir + "/generated")
    api_files = {f"generated/{k}": v for k, v in rt_files.items() if k in api_rt_keys}
    ctrl_files: Dict[str, str] = {}
    for k, v in rt_files.items():
        if k in ctrl_rt_keys:
            ctrl_files[f"generated/{k}"] = v
    # fix import del modello in _data.ts (controllers/generated -> model/generated)
    if "generated/_data.ts" in ctrl_files:
        ctrl_files["generated/_data.ts"] = ctrl_files["generated/_data.ts"].replace("../../model/generated", model_rel)
    # fix import del modello in _router.ts (api/generated -> model/generated)
    api_model_rel = _ts_relpath(api_dir + "/generated", model_dir + "/generated")
    if "generated/_router.ts" in api_files:
        api_files["generated/_router.ts"] = api_files["generated/_router.ts"].replace("../../model/generated", api_model_rel)
    specs = json.dumps([op_spec(o) for o in ops], ensure_ascii=False, indent=1)
    api_files["generated/operations.ts"] = (header(L, "schemas/generated/openapi.yaml").rstrip("\n") + "\n/* eslint-disable */\n"
                                            "// Operazioni del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo.\n"
                                            'import type { Spec } from "./_router";\n\nexport const SPECS: Spec[] = ' + specs + ";\n")
    # percorsi relativi per i file per tabella (controllers/generated -> api/generated e model)
    api_rel = _ts_relpath(ctrl_dir + "/generated", api_dir + "/generated")
    model_base = _ts_relpath(ctrl_dir + "/generated", model_dir)
    model_gen = _ts_relpath(ctrl_dir + "/generated", model_dir + "/generated")
    targets = rel_targets(tables, ops)
    for n, t in tables.items():
        tops = [o for o in ops if o.table == n]
        if tops or n in targets:
            ctrl_files[f"generated/{n}.ts"] = _table_file(t, tables, tops, api_rel, model_base, model_gen)
    if any(o.kind == "custom" for o in ops):
        api_files["generated/custom.ts"] = _custom_file([o for o in ops if o.kind == "custom"])
    ctrl_rel = _ts_relpath(api_dir + "/generated", ctrl_dir + "/generated")
    api_files["generated/index.ts"] = _index_file(tables, ops, ac, ctrl_rel)
    return api_files, ctrl_files
