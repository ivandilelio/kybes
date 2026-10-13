"""Rende il catalogo dei casi di test in node:test (TypeScript) per i progetti che usano kybes."""
from __future__ import annotations

import json
import re
from typing import Dict, List

from emit_typescript import _ts_value
from naming import header, member, method_name, repo_class
from schema import Table, snake
from verification import METHODS, Catalog, TestCase, table_asil

L = "typescript"
_ID_TYPE = ["uuid"]
HEAD_LINT = "/* eslint-disable */\n"


def _a(name: str) -> str:
    return member(L, name)


def _type(t: Table, cn: str) -> str:
    return t.col(cn).type


def db_file(dialect: str, n_first: str) -> str:
    if dialect == "sqlite":
        source = '''    const ds = new DataSource({ type: "sqljs", entities: ENTITIES, synchronize: true, logging: false });
    await ds.initialize();
    await ds.query("PRAGMA foreign_keys = ON");'''
        note = "SQLite in memoria (sql.js)"
    else:
        source = '''    const url = process.env.KYBES_TEST_DATABASE_URL;
    if (!url) throw new Error("Imposta KYBES_TEST_DATABASE_URL (PostgreSQL di test) per eseguire i test generati");
    const ds = new DataSource({ type: "postgres", url, entities: ENTITIES, synchronize: true, dropSchema: true, logging: false });
    await ds.initialize();'''
        note = "PostgreSQL indicato da KYBES_TEST_DATABASE_URL (schema ricreato a ogni test)"
    return header(L, "kit") + HEAD_LINT + f'''// Database isolato per ogni test generato: {note}.
import "reflect-metadata";
import {{ DataSource }} from "typeorm";
import type {{ EntityManager }} from "typeorm";
import {{ ENTITIES, bindTenant }} from "../../src/model/generated";
import {{ TENANT_A }} from "./kybes_builders";

export async function withDb(work: (em: EntityManager, ds: DataSource) => Promise<void>): Promise<void> {{
{source}
  try {{
    bindTenant(ds.manager, TENANT_A); // le tabelle multi-tenant richiedono un tenant legato
    await work(ds.manager, ds);
  }} finally {{
    await ds.destroy();
  }}
}}
'''


def _sample(t: Table, cn: str, tables: Dict[str, Table]) -> str:
    c = t.col(cn)
    rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == cn), None)
    if rel:
        return f"(await build{rel.target}(em)).{_a(tables[rel.target].pk.name)}"
    if c.type == "string":
        return f"textValue(nextN(), {c.length})"
    return {"uuid": "randomUUID()", "text": "`testo ${nextN()}`", "int": "nextN()", "bigint": "String(nextN())",
            "decimal": "`${nextN()}.50`", "bool": "true", "date": "dayValue(nextN())", "datetime": "new Date(Date.UTC(2026, 0, 1) + nextN() * 3600000)",
            "json": "{ n: nextN() }"}[c.type]


def builders_file(tables: Dict[str, Table]) -> str:
    o = [header(L, "kit") + HEAD_LINT + "// Costruttori di dati validi per i test generati: un record per chiamata, valori deterministici.",
         'import { randomUUID } from "node:crypto";', 'import type { EntityManager } from "typeorm";']
    for n in tables:
        o.append(f'import {{ {n}, {repo_class(L, n)} }} from "../../src/model/{n}";')
    tval = ('"00000000-0000-4000-8000-00000000000{}"' if _ID_TYPE[0] == "uuid" else '"tenant-{}"')
    o += ["", "// tenant di prova: withDb lega TENANT_A", f"export const TENANT_A = {tval.format('a')};", f"export const TENANT_B = {tval.format('b')};"]
    o += ["", "let seq = 0;", "export function nextN(): number {", "  seq += 1;", "  return seq;", "}", "",
          "export function textValue(n: number, length: number): string {", "  return `v${n}`.slice(0, length);", "}", "",
          "export function dayValue(n: number): string {", "  return new Date(Date.UTC(2026, 0, 1) + n * 86400000).toISOString().slice(0, 10);", "}", "",
          "export type Kind = \"uuid\" | \"string\" | \"text\" | \"int\" | \"bigint\" | \"decimal\" | \"bool\" | \"date\" | \"datetime\";", "",
          "/** Confronto tra valori di una colonna: -1, 0, 1 (gestisce le rappresentazioni diverse dei driver). */",
          "export function cmp(a: unknown, b: unknown, kind: Kind): number {",
          "  if (kind === \"int\" || kind === \"decimal\") return Math.sign(Number(a) - Number(b));",
          "  if (kind === \"bigint\") { const d = BigInt(String(a)) - BigInt(String(b)); return d === 0n ? 0 : d > 0n ? 1 : -1; }",
          "  if (kind === \"datetime\") return Math.sign(new Date(a as Date).getTime() - new Date(b as Date).getTime());",
          "  if (kind === \"bool\") return Number(Boolean(a)) - Number(Boolean(b));",
          "  const x = String(a), y = String(b);",
          "  return x === y ? 0 : x > y ? 1 : -1;",
          "}", "",
          "export function different(v: unknown, kind: Kind, length = 0): unknown {",
          "  switch (kind) {",
          "    case \"uuid\": return randomUUID();",
          "    case \"int\": return Number(v) + 1000003;",
          "    case \"bigint\": return String(BigInt(String(v)) + 1000003n);",
          "    case \"decimal\": return (Number(v) + 1000003).toFixed(2);",
          "    case \"bool\": return !v;",
          "    case \"date\": return dayValue(401 + Math.round((Date.parse(String(v)) - Date.UTC(2026, 0, 1)) / 86400000));",
          "    case \"datetime\": return new Date(new Date(v as Date).getTime() + 401 * 86400000);",
          "    default: {",
          "      const s = \"x\" + String(v);",
          "      const out = length && s.length > length ? s.slice(0, length) : s;",
          "      return out === v ? out.slice(0, -1) + \"y\" : out;",
          "    }",
          "  }",
          "}", "",
          "export function greater(v: unknown, kind: Kind): unknown {",
          "  switch (kind) {",
          "    case \"uuid\": return \"ffffffff-ffff-ffff-ffff-ffffffffffff\";",
          "    case \"int\": return Number(v) + 1;",
          "    case \"bigint\": return String(BigInt(String(v)) + 1n);",
          "    case \"decimal\": return (Number(v) + 1).toFixed(2);",
          "    case \"date\": return dayValue(1 + Math.round((Date.parse(String(v)) - Date.UTC(2026, 0, 1)) / 86400000));",
          "    case \"datetime\": return new Date(new Date(v as Date).getTime() + 86400000);",
          "    default: return String(v) + \"~\";",
          "  }",
          "}", "",
          "export function smaller(v: unknown, kind: Kind): unknown {",
          "  switch (kind) {",
          "    case \"uuid\": return \"00000000-0000-0000-0000-000000000000\";",
          "    case \"int\": return Number(v) - 1;",
          "    case \"bigint\": return String(BigInt(String(v)) - 1n);",
          "    case \"decimal\": return (Number(v) - 1).toFixed(2);",
          "    case \"date\": return dayValue(-1 + Math.round((Date.parse(String(v)) - Date.UTC(2026, 0, 1)) / 86400000));",
          "    case \"datetime\": return new Date(new Date(v as Date).getTime() - 86400000);",
          "    default: return \"\";",
          "  }",
          "}"]
    for n, t in tables.items():
        o += ["", f"/** Inserisce un {n} valido; over sostituisce i valori. */",
              f"export async function build{n}(em: EntityManager, over: Record<string, unknown> = {{}}): Promise<{n}> {{",
              "  const data: Record<string, unknown> = {};"]
        for c in t.columns:
            if (c.primary_key and c.auto) or c.generated or c.default is not None or c.tenant:
                continue
            a = _a(c.name)
            rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
            if rel:
                if c.required:
                    o.append(f'  if (!("{a}" in over)) data["{a}"] = (await build{rel.target}(em)).{_a(tables[rel.target].pk.name)};')
                continue
            o.append(f'  data["{a}"] = {_sample(t, c.name, tables)};')
        o += [f"  return new {repo_class(L, n)}(em).create({{ ...data, ...over }} as never);", "}"]
    return "\n".join(o) + "\n"


def _missing_pk(t: Table) -> str:
    return {"uuid": '"00000000-0000-4000-8000-000000000999"', "int": "987654321", "bigint": '"987654321"', "string": '"kybes-non-esiste"'}[t.pk.type]


def _new_value(t: Table, cn: str) -> str:
    c = t.col(cn)
    if c.type == "string":
        return f'"u" + textValue(nextN(), {max(c.length - 1, 1)})'
    return {"text": '"testo aggiornato"', "int": "nextN() + 500", "bigint": "String(nextN() + 500)", "decimal": '"99.25"'}[c.type]


def _check(a: str, op: str, val, kind: str) -> str:
    x = f"x.{a}"
    k = json.dumps(kind)
    return {"eq": f"cmp({x}, {val}, {k}) === 0", "ne": f"cmp({x}, {val}, {k}) !== 0", "lt": f"cmp({x}, {val}, {k}) < 0",
            "lte": f"cmp({x}, {val}, {k}) <= 0", "gt": f"cmp({x}, {val}, {k}) > 0", "gte": f"cmp({x}, {val}, {k}) >= 0",
            "in": f"({val} as unknown[]).some((v) => cmp({x}, v, {k}) === 0)", "prefix": f"String({x}).startsWith(String({val}))",
            "is_null": f"{x} === null || {x} === undefined", "not_null": f"{x} !== null && {x} !== undefined"}[op]


def _query_case(t: Table, tc: TestCase, tables: Dict[str, Table]) -> List[str]:
    q = next(x for x in t.queries if x.name == tc.args["query"])
    flip = tc.args.get("flip")
    empty = tc.args.get("empty")
    repo = repo_class(L, t.name)
    lines, over, params, checks, noise = [], [], [], [], []
    for i, c in enumerate(q.where):
        col = t.col(c.column)
        a = _a(c.column)
        kind = col.type
        flipped = i == flip
        ln = col.length or 0
        if c.has_value:
            lit = _ts_value(col, c.value)
            outside, inside = f'{a}: different({lit}, "{kind}", {ln})', f"{a}: {lit}"
            if c.op == "ne":
                outside, inside = inside, outside
            over.append(outside if flipped else inside)
            noise.append(outside)
            checks.append(_check(a, c.op, lit, kind))
            continue
        if c.op in ("is_null", "not_null"):
            want_null = (c.op == "is_null") != flipped
            over.append(f"{a}: null" if want_null else f"{a}: {_sample(t, c.column, tables)}")
            noise.append(f"{a}: null" if c.op == "not_null" else f"{a}: {_sample(t, c.column, tables)}")
            checks.append(_check(a, c.op, None, kind))
            continue
        if col.nullable:
            over.append(f"{a}: {_sample(t, c.column, tables)}")
        pn = member(L, c.param)
        v = f"e.{a}"
        K = f'"{kind}"'
        expr = {
            "eq": f"different({v}, {K}, {ln})" if flipped else v,
            "ne": v if flipped else f"different({v}, {K}, {ln})",
            "gte": f"greater({v}, {K})" if flipped else v,
            "lte": f"smaller({v}, {K})" if flipped else v,
            "gt": v if flipped else f"smaller({v}, {K})",
            "lt": v if flipped else f"greater({v}, {K})",
            "in": f"[different({v}, {K}, {ln})]" if flipped else f"[{v}]",
            "prefix": '"zz"' if flipped else f"String({v}).slice(0, 1)",
        }[c.op]
        params.append((pn, "[]" if i == empty else expr))
        checks.append(_check(a, c.op, pn, kind))
    lines.append(f"    const e = await build{t.name}(em{', { ' + ', '.join(over) + ' }' if over else ''});")
    if flip is None and empty is None and noise:
        lines.append(f"    await build{t.name}(em, {{ {', '.join(noise)} }}); // fuori dalla classe: non deve comparire")
    for pn, expr in params:
        lines.append(f"    const {pn} = {expr} as never;")
    args = ", ".join(pn for pn, _ in params)
    meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
    if q.returns == "page":
        lines.append(f"    const rows = (await new {repo}(em).{meth}({args + ', ' if args else ''}{{ limit: {t.pagination.max_limit} }})).items;")
    elif q.returns == "list":
        lines.append(f"    const rows = await new {repo}(em).{meth}({args});")
    else:
        lines.append(f"    const one = await new {repo}(em).{meth}({args});")
        lines.append("    const rows = one ? [one] : [];")
    pk = _a(t.pk.name)
    if empty is not None:
        lines += ["    void e;", "    assert.deepEqual(rows, []);"]
    elif flip is None:
        lines.append(f'    assert.ok(rows.some((x) => x.{pk} === e.{pk}), "il record che soddisfa le condizioni manca dal risultato");')
        lines.append(f'    assert.ok(rows.every((x) => {" && ".join("(" + c + ")" for c in checks)}), "un record restituito non soddisfa le condizioni");')
    else:
        lines.append(f'    assert.ok(rows.every((x) => x.{pk} !== e.{pk}), "la condizione {flip + 1} non determina il risultato");')
    return lines


def test_file(t: Table, cat: Catalog, tables: Dict[str, Table], default_asil: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    pk = _a(t.pk.name)
    others = sorted({r.target for r in t.relations} | {n})
    o = [header(L, f"schemas/db/{n}.yaml") + HEAD_LINT +
         f"// Test di unità generati per {n} (ASIL {table_asil(t, default_asil)}). Specifica: docs/generated/verification/{n}.md",
         "// I test dei metodi custom vanno in tests/custom/.",
         'import { test } from "node:test";', 'import assert from "node:assert/strict";',
         'import { ModelValidationError, TenantError, bindTenant } from "../../src/model/generated";']
    for x in others:
        o.append(f'import {{ {repo_class(L, x)} }} from "../../src/model/{x}";')
    o += ['import { withDb } from "./_db";',
          'import { ' + ", ".join(sorted({f"build{x}" for x in others} | {"cmp", "different", "greater", "nextN", "smaller", "textValue", "TENANT_A", "TENANT_B"})) +
          ' } from "./kybes_builders";', "",
          "const invalid = (field: string) => (e: unknown) => e instanceof ModelValidationError && field in e.fields;",
          "void [cmp, different, greater, nextN, smaller, textValue, TenantError, bindTenant, TENANT_A, TENANT_B];"]
    if any(tc.kind == "page_sort_each" for tc in cat.for_table(n)):
        o.insert(o.index('import { withDb } from "./_db";'), 'import type { Kind } from "./kybes_builders";')
    compare = [(c.name, c.type) for c in t.columns if c.type not in ("datetime", "json") and not c.generated]
    for tc in cat.for_table(n):
        o += ["", f"test({json.dumps(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)}, () =>",
              "  withDb(async (em, ds) => {", f"    // atteso: {tc.expected}"]
        k = tc.kind
        b = f"build{n}"
        if k == "create_valid":
            o += [f"    const e = await {b}(em);", f"    const got = await new {repo}(em).getById(e.{pk});", "    assert.ok(got);"]
            for cn, ty in compare:
                a = _a(cn)
                o.append(f'    assert.equal(e.{a} == null ? got.{a} == null : cmp(got.{a}, e.{a}, "{ty}") === 0, true, "{cn}");')
        elif k == "read_existing":
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);", f"    assert.equal((await repo.getById(e.{pk}))?.{pk}, e.{pk});",
                  f"    assert.equal(await repo.exists(e.{pk}), true);", "    assert.ok((await repo.count()) >= 1);"]
        elif k == "read_missing":
            o += [f"    const repo = new {repo}(em);", f"    assert.equal(await repo.getById({_missing_pk(t)} as never), null);",
                  f"    assert.equal(await repo.exists({_missing_pk(t)} as never), false);"]
        elif k == "update_allowed":
            a = _a(tc.args["column"])
            ty = _type(t, tc.args["column"])
            o += [f"    const e = await {b}(em);", f"    const value = {_new_value(t, tc.args['column'])};",
                  f"    await new {repo}(em).update(e.{pk}, {{ {a}: value }} as never);",
                  f'    assert.equal(cmp((await new {repo}(em).getById(e.{pk}))?.{a}, value, "{ty}"), 0);']
        elif k == "update_missing":
            o += [f"    assert.equal(await new {repo}(em).update({_missing_pk(t)} as never, {{}}), null);"]
        elif k == "update_key":
            o += [f"    const e = await {b}(em);",
                  f'    await assert.rejects(new {repo}(em).update(e.{pk}, {{ {pk}: {_missing_pk(t)} }} as never), invalid("{pk}"));']
        elif k == "delete":
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);", f"    assert.equal(await repo.delete(e.{pk}), true);",
                  f"    assert.equal(await repo.getById(e.{pk}), null);", f"    assert.equal(await repo.delete(e.{pk}), false);"]
        elif k == "find_by":
            a = _a(tc.args["column"])
            meth = method_name(L, "find_by:" + tc.args["column"])
            ty = _type(t, tc.args["column"])
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);", f"    assert.equal((await repo.{meth}(e.{a} as never))?.{pk}, e.{pk});",
                  f'    assert.equal(await repo.{meth}(different(e.{a}, "{ty}", {t.col(tc.args["column"]).length or 0}) as never), null);']
        elif k == "required_null":
            cn = tc.args["column"]
            o += [f'    await assert.rejects({b}(em, {{ {_a(cn)}: null }}), (err: unknown) => err instanceof ModelValidationError && err.fields["{cn}"] === "obbligatorio");']
        elif k == "maxlen_at":
            cn, ln = tc.args["column"], tc.args["length"]
            o += [f'    const e = await {b}(em, {{ {_a(cn)}: "a".repeat({ln}) }});', f"    assert.equal(String(e.{_a(cn)}).length, {ln});"]
        elif k == "maxlen_over":
            cn, ln = tc.args["column"], tc.args["length"]
            o += [f'    await assert.rejects({b}(em, {{ {_a(cn)}: "a".repeat({ln + 1}) }}), invalid("{cn}"));']
        elif k == "unique_duplicate":
            a = _a(tc.args["column"])
            o += [f"    const e = await {b}(em);", f"    await assert.rejects({b}(em, {{ {a}: e.{a} }}));"]
        elif k == "default_value":
            c = t.col(tc.args["column"])
            o += [f"    const e = await {b}(em);", f"    const got = await new {repo}(em).getById(e.{pk});",
                  f'    assert.equal(cmp(got?.{_a(c.name)}, {_ts_value(c, c.default)}, "{c.type}"), 0);']
        elif k in ("rel_parent", "list_by"):
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            fk = _a(r.foreign_key)
            tpk = _a(tables[r.target].pk.name)
            o += [f"    const parent = await build{r.target}(em);", f"    const child = await {b}(em, {{ {fk}: parent.{tpk} }});"]
            if k == "rel_parent":
                o += [f"    const got = await new {repo}(em).{method_name(L, 'get_rel:' + r.name)}(child.{pk});",
                      f"    assert.equal(got?.{tpk}, parent.{tpk});",
                      f"    assert.equal(await new {repo}(em).{method_name(L, 'get_rel:' + r.name)}({_missing_pk(t)} as never), null);"]
            else:
                o += [f"    const page = await new {repo}(em).{method_name(L, 'list_by:' + r.foreign_key)}(parent.{tpk} as never, {{ limit: {t.pagination.max_limit} }});",
                      f"    assert.ok(page.items.some((x) => x.{pk} === child.{pk}));",
                      f"    assert.ok(page.items.every((x) => x.{fk} === parent.{tpk}));"]
        elif k == "rel_children":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            ct = tables[r.target]
            fk = _a(r.foreign_key)
            cpk = _a(ct.pk.name)
            o += [f"    const parent = await {b}(em);", f"    const child = await build{r.target}(em, {{ {fk}: parent.{pk} }});",
                  f"    const page = await new {repo}(em).{method_name(L, 'list_rel:' + r.name)}(parent.{pk}, {{ limit: {ct.pagination.max_limit} }});",
                  f"    assert.ok(page.items.some((x) => x.{cpk} === child.{cpk}));",
                  f"    assert.ok(page.items.every((x) => x.{fk} === parent.{pk}));"]
        elif k == "page_walk":
            o += [f"    const built = new Set<unknown>();", f"    for (let i = 0; i < 3; i++) built.add((await {b}(em)).{pk});",
                  f"    const repo = new {repo}(em);", "    const seen: unknown[] = [];", "    let cursor: string | null = null;",
                  "    for (let i = 0; i < 100; i++) {", "      const page = await repo.listPage({ limit: 1, cursor" + _sort_arg(tc) + " });",
                  f"      seen.push(...page.items.map((x) => x.{pk}));", "      if (!page.nextCursor) break;", "      cursor = page.nextCursor;", "    }",
                  "    assert.ok([...built].every((id) => seen.includes(id)));", "    assert.equal(new Set(seen).size, seen.length);"]
        elif k == "generated_values":
            cols, upd = tc.args["columns"], tc.args["update"]
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);",
                  f"    const before = await repo.getById(e.{pk});"]
            o += [f'    assert.ok(before?.{_a(cn)}, "{cn}");' for cn, _ in cols]
            if upd:
                o += [f"    await repo.update(e.{pk}, {{ {_a(upd)}: {_new_value(t, upd)} }} as never);",
                      f"    const after = await repo.getById(e.{pk});"]
                for cn, g in cols:
                    op = "=== 0" if g == "on_create" else ">= 0"
                    o.append(f'    assert.ok(cmp(after?.{_a(cn)}, before?.{_a(cn)}, "datetime") {op}, "{cn}");')
        elif k == "tenant_required":
            o += [f"    assert.throws(() => new {repo}(ds.createEntityManager()), (e: unknown) => e instanceof TenantError);"]
        elif k == "tenant_isolation":
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);"]
            kids = [r for r in t.relations if r.kind == "one_to_many" and tables[r.target].tenancy == "column"]
            for r in kids:
                o.append(f"    await build{r.target}(em, {{ {_a(r.foreign_key)}: e.{pk} }});")
            o += ["    bindTenant(em, TENANT_B);", f"    assert.equal(await repo.getById(e.{pk}), null);",
                  f"    assert.equal(await repo.exists(e.{pk}), false);", "    assert.equal(await repo.count(), 0);",
                  f"    assert.ok(!(await repo.listPage()).items.some((x) => x.{pk} === e.{pk}));",
                  f"    assert.equal(await repo.update(e.{pk}, {{}}), null);", f"    assert.equal(await repo.delete(e.{pk}), false);"]
            for c in t.columns:
                if c.unique and not c.primary_key:
                    o.append(f"    assert.equal(await repo.{method_name(L, 'find_by:' + c.name)}(e.{_a(c.name)} as never), null);")
            for r in kids:
                o.append(f"    assert.deepEqual((await repo.{method_name(L, 'list_rel:' + r.name)}(e.{pk})).items, []);")
            o += ["    bindTenant(em, TENANT_A);", f"    assert.ok(await repo.getById(e.{pk}));"]
        elif k == "tenant_assign":
            tm = _a(next(c for c in t.columns if c.tenant).name)
            o += [f"    const e = await {b}(em);", f"    assert.equal(e.{tm}, TENANT_A);",
                  f'    await assert.rejects({b}(em, {{ {tm}: TENANT_B }}), invalid("TenantId"));']
        elif k == "tenant_unique":
            a = _a(tc.args["column"])
            o += [f"    const e = await {b}(em);", "    bindTenant(em, TENANT_B);", f"    const other = await {b}(em, {{ {a}: e.{a} }});",
                  f"    assert.ok(other.{a} === e.{a} && other.{pk} !== e.{pk});"]
        elif k == "tenant_parent":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            o += ["    bindTenant(em, TENANT_B);", f"    const parent = await build{r.target}(em);", "    bindTenant(em, TENANT_A);",
                  f"    await assert.rejects({b}(em, {{ {_a(r.foreign_key)}: parent.{_a(tables[r.target].pk.name)} }}),",
                  f'      (err: unknown) => err instanceof ModelValidationError && err.fields["{r.foreign_key}"] === "non trovato");']
        elif k == "optional_null":
            a = _a(tc.args["column"])
            o += [f"    const e = await {b}(em, {{ {a}: null }});",
                  f"    assert.equal((await new {repo}(em).getById(e.{pk}))?.{a} ?? null, null);"]
        elif k == "rel_parent_object":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            fk, rn, tpk = _a(r.foreign_key), _a(r.name), _a(tables[r.target].pk.name)
            o += [f"    const parent = await build{r.target}(em);", f"    const child = await {b}(em, {{ {fk}: undefined, {rn}: parent }});",
                  f"    assert.equal(child.{fk}, parent.{tpk});",
                  f"    assert.equal((await new {repo}(em).getById(child.{pk}))?.{fk}, parent.{tpk});"]
        elif k == "page_default":
            o += [f"    const e = await {b}(em);", f"    const repo = new {repo}(em);",
                  f"    assert.equal((await repo.listPage()).limit, {t.pagination.default_limit});"]
            for r in t.relations:
                tt = tables[r.target]
                if r.kind == "many_to_one":
                    val = f"e.{_a(r.foreign_key)}" if t.col(r.foreign_key).required else f"(await build{r.target}(em)).{_a(tt.pk.name)}"
                    o.append(f"    assert.equal((await repo.{method_name(L, 'list_by:' + r.foreign_key)}({val} as never)).limit, {t.pagination.default_limit});")
                else:
                    o.append(f"    assert.equal((await repo.{method_name(L, 'list_rel:' + r.name)}(e.{pk})).limit, {tt.pagination.default_limit});")
            o.append("    void e;")
        elif k == "page_sort_each":
            sorts = ", ".join(f'["{_sort_json(x)}", "{_a(x.lstrip("-"))}", "{t.col(x.lstrip("-")).type}"]' for x in tc.args["sorts"])
            o += [f"    for (let i = 0; i < 3; i++) await {b}(em);", f"    const repo = new {repo}(em);", "    const total = await repo.count();",
                  f"    for (const [sort, prop, kind] of [{sorts}] as const) {{",
                  "      const seen: unknown[] = [];", "      const values: unknown[] = [];", "      let cursor: string | null = null;",
                  "      for (let i = 0; i < 100; i++) {", "        const page = await repo.listPage({ limit: 1, cursor, sort });",
                  f"        seen.push(...page.items.map((x) => x.{pk}));",
                  "        values.push(...page.items.map((x) => (x as unknown as Record<string, unknown>)[prop]));",
                  "        if (!page.nextCursor) break;", "        cursor = page.nextCursor;", "      }",
                  "      assert.equal(new Set(seen).size, seen.length, sort);", "      assert.equal(seen.length, total, sort);",
                  "      for (let i = 1; i < values.length; i++) {",
                  "        const c = cmp(values[i - 1], values[i], kind as Kind);",
                  '        assert.ok(sort.startsWith("-") ? c >= 0 : c <= 0, sort);', "      }", "    }"]
        elif k == "page_limit":
            o += [f'    await assert.rejects(new {repo}(em).listPage({{ limit: {tc.args["limit"]} }}), invalid("limit"));']
        elif k == "page_limit_ok":
            o += [f"    await {b}(em);", f"    const page = await new {repo}(em).listPage({{ limit: {tc.args['limit']} }});",
                  f"    assert.equal(page.limit, {tc.args['limit']});", "    assert.ok(page.items.length >= 1);"]
        elif k == "page_sort_invalid":
            o += [f'    await assert.rejects(new {repo}(em).listPage({{ sort: "kybesNonOrdinabile" }}), invalid("sort"));']
        elif k == "page_cursor_invalid":
            o += [f'    await assert.rejects(new {repo}(em).listPage({{ cursor: "kybes-non-valido" }}), invalid("cursor"));']
        elif k in ("query_match", "query_mcdc", "query_empty_in"):
            o += _query_case(t, tc, tables)
        else:
            raise ValueError(k)
        o.append("  }));")
    return _drop_unused_repos(o, [repo_class(L, x) for x in others])


def _sort_json(x: str) -> str:
    return ("-" if x.startswith("-") else "") + member(L, x.lstrip("-"))


def _sort_arg(tc: TestCase) -> str:
    sort = tc.args.get("sort")
    if not sort:
        return ""
    return ', sort: "' + ",".join(("-" if x.startswith("-") else "") + member(L, x.lstrip("-")) for x in sort) + '"'


def _drop_unused_repos(lines: List[str], classes: List[str]) -> str:
    """Toglie gli import dei repository che il corpo non usa (noUnusedLocals)."""
    body = "\n".join(x for x in lines if not x.startswith("import "))
    keep = []
    for x in lines:
        m = re.match(r'import \{ (\w+) \} from "\.\./\.\./src/model/', x)
        if m and m.group(1) in classes and not re.search(rf"\b{m.group(1)}\b", body):
            continue
        keep.append(x)
    return "\n".join(keep) + "\n"


def runtime_file(cat: Catalog, tables: Dict[str, Table]) -> str:
    first = next(iter(tables.values()))
    bad = "non-un-uuid" if cat.tenant_id_type == "uuid" else "x" * 65
    extra_names = [] if cat.tenant_id_type == "uuid" else [
        '    assert.equal(tenantKey("Tenant-A"), "tenant_a");', '    assert.throws(() => tenantKey("nome non valido"), TenantError);']
    n, repo = first.name, repo_class(L, first.name)
    spec = f"PAGING_{snake(n).upper()}"
    pkj = member(L, first.pk.name)
    mods = ", ".join(f"{x}: M_{x}" for x in tables)
    bodies = {
        "rt_exports": ["    for (const [k, v] of Object.entries(API)) assert.notEqual(v, undefined, k);",
                       f"    const tables: Record<string, Record<string, unknown>> = {{ {mods} }};",
                       "    for (const [n, m] of Object.entries(tables)) {",
                       "      for (const [k, v] of Object.entries(m)) assert.notEqual(v, undefined, `${n}.${k}`);",
                       '      assert.equal(typeof m[n], "function", n);',
                       '      assert.equal(typeof m[`${n}Repository`], "function", `${n}Repository`);', "    }"],
        "rt_sort_key": [f'    assert.deepEqual(resolveOrder({spec}, "-{pkj}"), [{{ ...{spec}.pk, desc: true }}]);'],
        "rt_sort_plus": ['    const order = resolveOrder(SPEC, "+numero");', "    assert.equal(order[0].desc, false);",
                         '    assert.equal(order[order.length - 1].prop, "id");'],
        "rt_cursor_roundtrip": ['    const row = { id: "00000000-0000-0000-0000-00000000000a", numero: "A-1", quantita: 7, grande: "12345678901",',
                                '      prezzo: "3.25", giorno: "2026-02-03", istante: new Date("2026-02-03T04:05:06.000Z") };',
                                "    const values = decodeCursor(SPEC, ALL, encodeCursor(ALL, row));",
                                "    assert.deepEqual(values, ALL.map((o) => (row as Record<string, unknown>)[o.prop]));"],
        "rt_cursor_types": ["    const good: unknown[] = [\"00000000-0000-0000-0000-00000000000a\", \"x\", 1, \"1\", \"1\", \"2026-01-01\", \"2026-01-01T00:00:00.000Z\"];",
                            "    for (const [i, bad] of [[0, 1], [1, 7], [2, \"uno\"], [2, 1.5], [6, \"ieri\"], [6, 3]] as const) {",
                            "      const values = [...good];", "      values[i] = bad;",
                            '      assert.throws(() => decodeCursor(SPEC, ALL, rawCursor(ALL, values)), invalid("cursor"));', "    }",
                            '    assert.throws(() => decodeCursor(SPEC, ALL, Buffer.from("non json").toString("base64url")), invalid("cursor"));'],
        "rt_cursor_signature": ['    const cursor = rawCursor(resolveOrder(SPEC, "-numero"), ["x", "00000000-0000-0000-0000-00000000000a"]);',
                                '    assert.throws(() => decodeCursor(SPEC, resolveOrder(SPEC, "numero"), cursor), invalid("cursor"));'],
        "rt_like": ['    assert.equal(likePrefix("a%_\\\\"), "a\\\\%\\\\_\\\\\\\\%");'],
        "rt_fixed_sort": [f'    const qb = em.getRepository({n}).createQueryBuilder("e");',
                          f'    await assert.rejects(runPage(qb, "e", {spec}, {{ sort: "x" }}, {spec}.defaultOrder), invalid("sort"));',
                          f"    assert.deepEqual(emptyPage({spec}), {{ items: [], nextCursor: null, limit: {spec}.defaultLimit }});"],
        "rt_empty_page": [f"    const page = await new {repo}(em).listPage({{ limit: 5 }});", "    assert.deepEqual(page.items, []);",
                          "    assert.equal(page.nextCursor, null);"],
        "rt_isolation": ['    assert.equal(isolationFor([]), "read_committed");', '    assert.equal(isolationFor(["kybesSconosciuta"]), "read_committed");',
                         '    const rank = ["read_committed", "repeatable_read", "serializable"];',
                         "    const best = Object.values(ISOLATION).sort((a, b) => rank.indexOf(b) - rank.indexOf(a))[0];",
                         "    assert.equal(isolationFor(Object.keys(ISOLATION)), best);"],
        "rt_isolation_applied": ["    const seen: unknown[] = [];",
                                 "    const fake = { transaction: async (...args: unknown[]) => {",
                                 "      seen.push(args.length === 2 ? args[0] : null);",
                                 "      return (args[args.length - 1] as (m: EntityManager) => Promise<unknown>)(em);",
                                 "    } } as unknown as DataSource;",
                                 '    assert.equal(await runInTransaction(fake, async () => 1, { isolation: "serializable" }), 1);',
                                 '    await runInTransaction(fake, async () => 2, { isolation: "serializable", levels: { serializable: null } });',
                                 '    assert.deepEqual(seen, ["SERIALIZABLE", null]);'],
        "rt_tenant_bind": ["    const fresh = ds.createEntityManager();", "    assert.throws(() => tenantOf(fresh), TenantError);",
                           "    bindTenant(fresh, TENANT_A);", "    assert.equal(tenantOf(fresh), TENANT_A);",
                           "    bindTenant(fresh, TENANT_B.toUpperCase());" if cat.tenant_id_type == "uuid" else "    bindTenant(fresh, TENANT_B);",
                           "    assert.equal(tenantOf(fresh), TENANT_B);", "    bindTenant(fresh, null);",
                           "    assert.throws(() => tenantOf(fresh), TenantError);",
                           f"    assert.throws(() => bindTenant(fresh, {json.dumps(bad)}), TenantError);",
                           "    assert.throws(() => coerceTenant(undefined), TenantError);"],
        "rt_tenant_names": ["    const key = tenantKey(TENANT_A);", '    assert.equal(key, TENANT_A.toLowerCase().replace(/-/g, "_"));',
                            '    assert.equal(schemaFor(TENANT_A), "tenant_" + key);',
                            '    assert.equal(searchPathFor(TENANT_A), `"tenant_${key}", public`);',
                            '    assert.equal(databaseUrlFor("postgresql://h/app_{tenant}", TENANT_A), "postgresql://h/app_" + key);',
                            '    assert.throws(() => databaseUrlFor("postgresql://h/app", TENANT_A), TenantError);'] + extra_names,
        "rt_tenant_uow": ["    assert.equal(await runInTransaction(ds, async (tx) => tenantOf(tx), { ...LEVELS_SQLITE, tenant: TENANT_A }), TENANT_A);",
                          "    const pg = await runInTransaction(ds, async (tx) => tx.connection.options.type !== \"postgres\" ||",
                          "      (await tx.query(\"select current_setting('app.tenant_id', true) as t\"))[0].t === TENANT_A, { ...LEVELS_SQLITE, tenant: TENANT_A });",
                          "    assert.ok(pg);",
                          "    // su PostgreSQL app.tenant_id: verificato anche con un EntityManager finto, qualunque sia il database dei test",
                          "    const calls: unknown[] = [];",
                          "    const fake = { connection: { options: { type: \"postgres\" } }, query: async (_sql: string, params: unknown[]) => { calls.push(params); } } as unknown as EntityManager;",
                          "    bindTenant(fake, TENANT_A);", "    await applyTenantSetting(fake);", "    assert.deepEqual(calls, [[TENANT_A]]);"],
        "rt_commit": [f"    const e = await runInTransaction(ds, (tx) => build{n}(tx), {{ ...LEVELS_SQLITE, tenant: TENANT_A, tables: [\"{n}\"] }});",
                      f"    assert.ok(await new {repo}(em).getById(e.{member(L, first.pk.name)}));",
                      f"    const f = await runInTransaction(ds, (tx) => build{n}(tx), {{ ...LEVELS_SQLITE, tenant: TENANT_A, isolation: \"serializable\" }});",
                      f"    assert.ok(await new {repo}(em).getById(f.{member(L, first.pk.name)}));"],
        "rt_rollback": [f"    await assert.rejects(runInTransaction(ds, async (tx) => {{ await build{n}(tx); throw new Error(\"errore applicativo\"); }}, {{ ...LEVELS_SQLITE, tenant: TENANT_A }}), /errore applicativo/);",
                        f"    assert.equal(await new {repo}(em).count(), 0);"],
        "rt_retry": ["    let calls = 0;", "    const res = await runInTransaction(ds, async (tx) => {", "      calls++;", f"      await build{n}(tx);",
                     '      if (calls < 3) throw Object.assign(new Error("serialization failure"), { code: "40001" });', "      return calls;",
                     f'    }}, {{ ...LEVELS_SQLITE, tenant: TENANT_A, tables: ["{n}"], backoffMs: 0 }});', "    assert.equal(res, 3);",
                     f"    assert.equal(await new {repo}(em).count(), 1);"],
        "rt_retry_limit": ["    let calls = 0;", "    await assert.rejects(runInTransaction(ds, async () => {", "      calls++;",
                           '      throw Object.assign(new Error("deadlock"), { driverError: { code: "40P01" } });',
                           "    }, { ...LEVELS_SQLITE, tenant: TENANT_A, maxRetries: 2, backoffMs: 0 }), /deadlock/);", "    assert.equal(calls, 3);"],
        "rt_retry_other": ["    let calls = 0;", "    await assert.rejects(runInTransaction(ds, async () => {", "      calls++;",
                           '      throw Object.assign(new Error("duplicato"), { code: "23505" });', "    }, { ...LEVELS_SQLITE, tenant: TENANT_A, backoffMs: 0 }), /duplicato/);",
                           "    assert.equal(calls, 1);"],
    }
    o = [header(L, "kit") + HEAD_LINT + "// Test di unità generati per i moduli comuni: paginazione (_paging) e Unit of Work (_uow).",
         'import { test } from "node:test";', 'import assert from "node:assert/strict";',
         f'import {{ ModelValidationError, {n}, {spec} }} from "../../src/model/generated";',
         'import { decodeCursor, emptyPage, encodeCursor, likePrefix, resolveOrder, runPage } from "../../src/model/generated/_paging";',
         'import type { OrderItem, PagingSpec } from "../../src/model/generated/_paging";',
         'import type { DataSource, EntityManager } from "typeorm";',
         'import * as API from "../../src/model/generated";',
         *[f'import * as M_{x} from "../../src/model/{x}";' for x in tables],
         'import { ISOLATION, isolationFor, runInTransaction } from "../../src/model/generated/_uow";',
         'import { TenantError, applyTenantSetting, bindTenant, coerceTenant, databaseUrlFor, schemaFor, searchPathFor, tenantKey, tenantOf } from "../../src/model/generated/_tenant";',
         f'import {{ {repo} }} from "../../src/model/{n}";', 'import { withDb } from "./_db";', f'import {{ build{n}, TENANT_A, TENANT_B }} from "./kybes_builders";', "",
         "const invalid = (field: string) => (e: unknown) => e instanceof ModelValidationError && field in e.fields;",
         "// livelli dei test: SQLite non distingue i livelli, PostgreSQL li applica",
         'const LEVELS_SQLITE = process.env.KYBES_TEST_DATABASE_URL ? {} : { levels: { read_committed: null, repeatable_read: null, serializable: null } };',
         "const ALL: OrderItem[] = [",
         '  { prop: "id", json: "id", type: "uuid", desc: false }, { prop: "numero", json: "numero", type: "string", desc: false },',
         '  { prop: "quantita", json: "quantita", type: "int", desc: false }, { prop: "grande", json: "grande", type: "bigint", desc: false },',
         '  { prop: "prezzo", json: "prezzo", type: "decimal", desc: true }, { prop: "giorno", json: "giorno", type: "date", desc: false },',
         '  { prop: "istante", json: "istante", type: "datetime", desc: true },', "];",
         'const SPEC: PagingSpec = { table: "Prova", pk: { prop: "id", json: "id", type: "uuid" }, sortable: { numero: { prop: "numero", type: "string" } },',
         '  defaultOrder: [{ prop: "id", json: "id", type: "uuid", desc: false }], defaultLimit: 50, maxLimit: 100 };', "",
         "function rawCursor(order: OrderItem[], values: unknown[]): string {",
         '  const s = order.map((o) => (o.desc ? "-" : "") + o.json).join(",");',
         '  return Buffer.from(JSON.stringify({ s, v: values }), "utf8").toString("base64url");', "}",
         f"void [{n}, TENANT_B];"]
    for tc in cat.for_table("_runtime"):
        o += ["", f"test({json.dumps(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)}, () =>",
              "  withDb(async (em, ds) => {", "    void em; void ds;"] + bodies[tc.kind] + ["  }));"]
    return "\n".join(o) + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], default_asil: str, dialect: str = "postgres") -> Dict[str, str]:
    _ID_TYPE[0] = cat.tenant_id_type
    first = next(iter(tables))
    files = {"generated/_db.ts": db_file(dialect, first), "generated/kybes_builders.ts": builders_file(tables)}
    for n, t in tables.items():
        files[f"generated/{n}.test.ts"] = test_file(t, cat, tables, default_asil)
    files["generated/kybes_runtime.test.ts"] = runtime_file(cat, tables)
    return files
