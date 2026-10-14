"""Emettitore delle API TypeScript: operazioni del contratto, controller CRUD per tabella, interfaccia dei metodi custom."""
from __future__ import annotations

import json
from typing import Dict, List

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


def _table_file(t: Table, tables: Dict[str, Table], ops: List[Operation]) -> str:
    n = t.name
    repo = repo_class(L, n)
    exposed = [c for c in t.columns if not c.tenant]
    writable = [c for c in exposed if not (c.primary_key and c.auto) and not c.generated]
    read, write = ("data.mongoRead", "data.mongoWrite") if t.mongo else ("data.read", "data.write")
    targets = sorted({next(r for r in t.relations if r.name == o.arg).target for o in ops if o.kind == "rel"} - {n})
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
            b.append(f"  return {read}(call.tenant, async (em) => page(await new {repo}(em).listPage(request(call.query)), toJson));")
        elif op.kind == "get":
            b += [f"  return {read}(call.tenant, async (em) => {{", f"    const e = await new {repo}(em).getById({key});",
                  '    if (e === null) throw new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");', "    return toJson(e);", "  });"]
        elif op.kind == "create":
            b += [f"  const body = await {write}({write_args}, async (em) => toJson(await new {repo}(em).create(values(call.body as Record<string, unknown>) as never)));",
                  f'  return reply(201, body, {{ "content-type": "application/json", location: "{op.path}/" + String(body.{prop(t.pk.name)}) }});']
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
         f"// API REST di {n}: JSON <-> modello e controller delle operazioni generate (blocco api dello schema)."]
    o.append(f'import {{ {n}, {repo} }} from "../../model/{n}";' if ops else f'import type {{ {n} }} from "../../model/{n}";')
    if paged:
        o.append('import type { Page, PageRequest } from "../../model/generated/_paging";')
    if conv_names:
        o.append(f'import {{ {", ".join(conv_names)} }} from "./_convert";')
    http = [x for x in ("ApiError", "reply") if f"{'new ' if x == 'ApiError' else ''}{x}(" in body]
    if ops:
        o.append('import type { ApiData } from "./_data";')
    if http:
        o.append(f'import {{ {", ".join(http)} }} from "./_http";')
    if ops:
        o.append('import type { Call } from "./_http";')
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


def _index_file(tables: Dict[str, Table], ops: List[Operation], ac: Dict) -> str:
    exposed = [n for n in tables if any(o.table == n for o in ops) or n in rel_targets(tables, ops)]
    custom = any(o.kind == "custom" for o in ops)
    o = [header(L, "kit").rstrip("\n") + "\n/* eslint-disable */",
         "// API REST generate: buildApi(data, custom, contexts) -> Api; adattatori per Lambda, node:http e Fastify.",
         'import { ApiData } from "./_data";', 'import { Api } from "./_router";', 'import type { Handler, Spec } from "./_router";',
         'import { SPECS } from "./operations";']
    if custom:
        o.append('import type { Operations } from "./custom";')
    for n in exposed:
        o.append(f'import {{ HANDLERS as {camel(n)} }} from "./{n}";')
    o += ["", 'export { ApiData } from "./_data";', 'export type { ApiDataOptions } from "./_data";',
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


def emit(tables: Dict[str, Table], ops: List[Operation], ac: Dict, opts: Dict) -> Dict[str, str]:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    files = {f"generated/{k}": v for k, v in rt.files(sql, mongo, ac["claims"], ac["headers"]).items()}
    specs = json.dumps([op_spec(o) for o in ops], ensure_ascii=False, indent=1)
    files["generated/operations.ts"] = (header(L, "schemas/generated/openapi.yaml").rstrip("\n") + "\n/* eslint-disable */\n"
                                        "// Operazioni del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo.\n"
                                        'import type { Spec } from "./_router";\n\nexport const SPECS: Spec[] = ' + specs + ";\n")
    targets = rel_targets(tables, ops)
    for n, t in tables.items():
        tops = [o for o in ops if o.table == n]
        if tops or n in targets:
            files[f"generated/{n}.ts"] = _table_file(t, tables, tops)
    if any(o.kind == "custom" for o in ops):
        files["generated/custom.ts"] = _custom_file([o for o in ops if o.kind == "custom"])
    files["generated/index.ts"] = _index_file(tables, ops, ac)
    return files
