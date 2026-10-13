"""Emettitore TypeScript: TypeORM (decorator) con repository basato su EntityManager."""
from __future__ import annotations

import json
from typing import Dict, Tuple

import runtime_tenant
import runtime_typescript
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from schema import Table, index_specs, methods_of, snake, tenant_column

L = "typescript"

TS_TYPE = {"uuid": "string", "string": "string", "text": "string", "int": "number", "bigint": "string",
           "decimal": "string", "bool": "boolean", "date": "string", "datetime": "Date", "json": "unknown"}
DB_TYPE = {
    "postgres": {"uuid": "uuid", "string": "varchar", "text": "text", "int": "integer", "bigint": "bigint",
                 "decimal": "decimal", "bool": "boolean", "date": "date", "datetime": "timestamptz", "json": "jsonb"},
    "sqlite": {"uuid": "varchar", "string": "varchar", "text": "text", "int": "integer", "bigint": "bigint",
               "decimal": "decimal", "bool": "boolean", "date": "date", "datetime": "datetime", "json": "simple-json"},
}


def _col_opts(c, dialect: str, extra: Dict = None) -> str:
    o = {"name": c.db_name, "type": DB_TYPE[dialect][c.type]}
    if c.type == "string":
        o["length"] = c.length
    if c.type == "uuid" and dialect == "sqlite":
        o["length"] = 36
    if c.type == "decimal":
        o["precision"], o["scale"] = c.precision, c.scale
    if not c.primary_key:
        o["nullable"] = c.nullable
    if c.default is not None:
        o["default"] = c.default
    o.update(extra or {})
    return "{ " + ", ".join(f"{k}: {json.dumps(v)}" for k, v in o.items()) + " }"


def _ts_type(c) -> str:
    return TS_TYPE[c.type] + (" | null" if c.nullable else "")


def _table_file(t: Table, tables: Dict[str, Table], schema_rel: str, dialect: str) -> str:
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], TS_TYPE[pk.type]
    targets = sorted({r.target for r in t.relations if r.target != t.name})
    deco = {"Entity", "Column", "EntityManager", "Repository", "DeepPartial"}
    if pk.auto:
        deco.add("PrimaryGeneratedColumn")
    else:
        deco.add("PrimaryColumn")
    if any(c.generated == "on_create" for c in t.columns):
        deco.add("CreateDateColumn")
    if any(c.generated == "on_update" for c in t.columns):
        deco.add("UpdateDateColumn")
    specs = index_specs(t)
    if any(not s.unique for s in specs):
        deco.add("Index")
    if any(s.unique for s in specs):
        deco.add("Unique")
    if any(r.kind == "many_to_one" for r in t.relations):
        deco |= {"ManyToOne", "JoinColumn"}
    if any(r.kind == "one_to_many" for r in t.relations):
        deco.add("OneToMany")
    if t.relations:
        deco.add("Relation")
    types_only = {"EntityManager", "Repository", "DeepPartial", "Relation"}
    out = []
    w = out.append
    w(header(L, schema_rel) + "/* eslint-disable */")
    w(f"// {t.name}: entità, CRUD e relazioni (tabella {t.db_name}).{(' ' + t.description) if t.description else ''}")
    w("import { " + ", ".join(sorted(deco - types_only)) + ' } from "typeorm";')
    w("import type { " + ", ".join(sorted(deco & types_only)) + ' } from "typeorm";')
    w('import { ModelValidationError } from "./_base";')
    tc = tenant_column(t)
    tm = m[tc.name] if tc else None
    if t.tenancy != "none":
        w('import { tenantOf } from "./_tenant";')
    paging_names = ["runPage", "orderRows", "likePrefix", "emptyPage"]
    w('import { ' + ", ".join(sorted(paging_names)) + ' } from "./_paging";')
    w('import type { OrderItem, Page, PageRequest, PagingSpec } from "./_paging";')
    for tg in targets:
        if any(r.kind == "one_to_many" and r.target == tg for r in t.relations):
            w(f'import {{ {tg}, PAGING_{snake(tg).upper()} }} from "./{tg}";')
        else:
            w(f'import {{ {tg} }} from "./{tg}";')
    w("")
    for s in specs:
        props = json.dumps([m[c] for c in s.columns])
        w(f'@{"Unique" if s.unique else "Index"}("{s.name}", {props})')
    w(f'@Entity({{ name: "{t.db_name}" }})')
    w(f"export class {t.name} {{")
    for c in t.columns:
        if c.primary_key and c.auto:
            strat = '"uuid"' if c.type == "uuid" else '"increment"'
            opts = {"name": c.db_name}
            if c.type != "uuid":
                # SQLite autoincrementa solo INTEGER PRIMARY KEY
                opts["type"] = "integer" if dialect == "sqlite" else DB_TYPE[dialect][c.type]
            w(f"  @PrimaryGeneratedColumn({strat}, {{ " + ", ".join(f"{k}: {json.dumps(v)}" for k, v in opts.items()) + " })")
        elif c.primary_key:
            w(f"  @PrimaryColumn({_col_opts(c, dialect)})")
        elif c.generated == "on_create":
            w(f"  @CreateDateColumn({_col_opts(c, dialect)})")
        elif c.generated == "on_update":
            w(f"  @UpdateDateColumn({_col_opts(c, dialect)})")
        else:
            w(f"  @Column({_col_opts(c, dialect)})")
        w(f"  {m[c.name]}!: {_ts_type(c)};\n")
    for r in t.relations:
        rn = member(L, r.name)
        if r.kind == "many_to_one":
            fkc = t.col(r.foreign_key)
            od = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}[r.on_delete]
            inv = f", (x) => x.{member(L, r.inverse)}" if r.inverse else ""
            w(f'  @ManyToOne(() => {r.target}{inv}, {{ onDelete: "{od}", nullable: {json.dumps(fkc.nullable)} }})')
            w(f'  @JoinColumn({{ name: "{fkc.db_name}" }})')
            w(f"  {rn}?: Relation<{r.target}>;\n")
        else:
            w(f"  @OneToMany(() => {r.target}, (x) => x.{member(L, r.inverse)})")
            w(f"  {rn}?: Relation<{r.target}[]>;\n")
    out[-1] = out[-1].rstrip("\n")
    w("}\n")

    # ---- validazione
    w(f"/** Validazione di modello prima della persistenza. */")
    w(f"export function validate{t.name}(e: Partial<{t.name}>): void {{")
    w("  const errors: Record<string, string> = {};")
    for c in t.columns:
        mm = m[c.name]
        if c.tenant:
            continue  # impostata dal repository con il tenant dell'EntityManager
        if c.required and not (c.primary_key and c.auto) and not c.generated and c.default is None:
            w(f'  if (e.{mm} === undefined || e.{mm} === null) errors["{c.name}"] = "obbligatorio";')
        elif c.required and not c.generated and c.default is not None:
            w(f'  if (e.{mm} === null) errors["{c.name}"] = "obbligatorio"; // assente: vale il default')
        if c.type == "string":
            w(f'  if (typeof e.{mm} === "string" && e.{mm}.length > {c.length}) errors["{c.name}"] = "lunghezza massima {c.length}";')
    w(f'  if (Object.keys(errors).length > 0) throw new ModelValidationError("{t.name}", errors);')
    w("}\n")

    sortable = ", ".join(f'{member(L, cn)}: {{ prop: "{m[cn]}", type: "{t.col(cn).type}" }}' for cn in t.pagination.sortable)
    order0 = ", ".join(f'{{ prop: "{m[cn]}", json: "{member(L, cn)}", type: "{t.col(cn).type}", desc: {str(d).lower()} }}' for cn, d in t.order())
    w(f"export const PAGING_{snake(t.name).upper()}: PagingSpec = {{")
    w(f'  table: "{t.name}",')
    w(f'  pk: {{ prop: "{pkm}", json: "{member(L, pk.name)}", type: "{pk.type}" }},')
    w(f"  sortable: {{ {sortable} }},")
    w(f"  defaultOrder: [{order0}],")
    w(f"  defaultLimit: {t.pagination.default_limit},")
    w(f"  maxLimit: {t.pagination.max_limit},")
    w("};\n")

    updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated and not c.tenant]
    T = t.name
    tw = f", {tm}: tenantOf(this.em)" if tc else ""   # filtro sul tenant negli oggetti where di TypeORM
    parents = [r for r in t.relations if r.kind == "many_to_one" and tables[r.target].tenancy == "column"] if tc else []
    upd_t = f"Pick<{t.name}, " + (" | ".join(json.dumps(x) for x in updatable) or "never") + ">"
    w(f"export type {t.name}Changes = Partial<{upd_t}>;\n")
    w(f"/** CRUD e relazioni di {t.name}. Per una transazione passa l'EntityManager della transazione. */")
    w(f"export class {base_class(L, t.name)} {{")
    if t.tenancy != "none":
        w(f"  constructor(protected readonly em: EntityManager) {{")
        w(f"    tenantOf(em); // tenancy: {t.tenancy}: senza un tenant legato all'EntityManager il repository non lavora")
        w("  }\n")
    else:
        w("  constructor(protected readonly em: EntityManager) {}\n")
    if tc:
        w(f"  /** Il record appartiene al tenant dell'EntityManager; i record collegati anche. */")
        w(f"  protected async checkTenant(entity: {T}): Promise<void> {{")
        w("    const tenant = tenantOf(this.em);")
        w(f"    if (entity.{tm} !== undefined && entity.{tm} !== null && entity.{tm} !== tenant) {{")
        w(f'      throw new ModelValidationError("{T}", {{ {tc.name}: "tenant diverso da quello della sessione" }});')
        w("    }")
        w(f"    entity.{tm} = tenant;")
        if parents:
            w("    const errors: Record<string, string> = {};")
            for r in parents:
                tg = tables[r.target]
                fk, tpk, ttm = m[r.foreign_key], member(L, tg.pk.name), member(L, tenant_column(tg).name)
                w(f"    if (entity.{fk} !== undefined && entity.{fk} !== null && (await this.em.getRepository({r.target}).countBy({{ {tpk}: entity.{fk}, {ttm}: tenant }})) === 0) {{")
                w(f'      errors["{r.foreign_key}"] = "non trovato";')
                w("    }")
            w(f'    if (Object.keys(errors).length > 0) throw new ModelValidationError("{T}", errors);')
        w("  }\n")
    w(f"  protected get repo(): Repository<{t.name}> {{")
    w(f"    return this.em.getRepository({t.name});")
    w("  }\n")
    paging = f"PAGING_{snake(t.name).upper()}"
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"  /** {meth.summary} */")
        if k == "get_by_id":
            w(f"  async {name}(id: {pkt}): Promise<{t.name} | null> {{")
            w(f"    return this.repo.findOneBy({{ {pkm}: id{tw} }});")
        elif k == "list_page":
            w(f"  async {name}(page: PageRequest = {{}}): Promise<Page<{t.name}>> {{")
            if tc:
                w(f'    const qb = this.repo.createQueryBuilder("e").where("e.{tm} = :tenant", {{ tenant: tenantOf(this.em) }});')
                w(f'    return runPage(qb, "e", {paging}, page);')
            else:
                w(f'    return runPage(this.repo.createQueryBuilder("e"), "e", {paging}, page);')
        elif k == "count":
            w(f"  async {name}(): Promise<number> {{")
            w(f"    return this.repo.countBy({{ {tm}: tenantOf(this.em) }});" if tc else "    return this.repo.count();")
        elif k == "exists":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w(f"    return (await this.repo.countBy({{ {pkm}: id{tw} }})) > 0;")
        elif k == "create":
            w(f"  async {name}(data: DeepPartial<{t.name}>): Promise<{t.name}> {{")
            w("    const entity = this.repo.create(data);")
            for r in t.relations:
                if r.kind == "many_to_one":
                    rn, fk = member(L, r.name), m[r.foreign_key]
                    tpk = member(L, tables[r.target].pk.name)
                    w(f"    if (entity.{rn}) entity.{fk} = entity.{rn}.{tpk}; // collegato come oggetto: la chiave segue l'oggetto")
            if tc:
                w("    await this.checkTenant(entity);")
            w(f"    validate{t.name}(entity);")
            w("    return this.repo.save(entity);")
        elif k == "update":
            w(f"  async {name}(id: {pkt}, changes: {t.name}Changes): Promise<{t.name} | null> {{")
            w(f"    const allowed = new Set<string>({json.dumps(updatable)});")
            w("    const unknown = Object.keys(changes).filter((key) => !allowed.has(key));")
            w(f'    if (unknown.length > 0) throw new ModelValidationError("{t.name}", Object.fromEntries(unknown.map((key) => [key, "campo non modificabile"])));')
            w(f"    const entity = await this.repo.findOneBy({{ {pkm}: id{tw} }});")
            w("    if (!entity) return null;")
            w("    Object.assign(entity, changes);")
            if tc:
                w("    await this.checkTenant(entity);")
            w(f"    validate{t.name}(entity);")
            w("    return this.repo.save(entity);")
        elif k == "delete":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w(f"    if ((await this.repo.countBy({{ {pkm}: id{tw} }})) === 0) return false;")
            w(f"    await this.repo.delete({{ {pkm}: id{tw} }});")
            w("    return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}): Promise<{t.name} | null> {{")
            w(f"    return this.repo.findOneBy({{ {m[arg]}: value{tw} }});")
        elif k == "list_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}, page: PageRequest = {{}}): Promise<Page<{t.name}>> {{")
            w(f'    const qb = this.repo.createQueryBuilder("e").where("e.{m[arg]} = :value", {{ value }});')
            if tc:
                w(f'    qb.andWhere("e.{tm} = :tenant", {{ tenant: tenantOf(this.em) }});')
            w(f'    return runPage(qb, "e", {paging}, page);')
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            rn = member(L, r.name)
            w(f"  async {name}(id: {pkt}): Promise<{r.target} | null> {{")
            w(f"    const entity = await this.repo.findOne({{ where: {{ {pkm}: id{tw} }}, relations: {{ {rn}: true }} }});")
            w(f"    return entity?.{rn} ?? null;")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"  async {name}(id: {pkt}, page: PageRequest = {{}}): Promise<Page<{r.target}>> {{")
            w(f'    const qb = this.em.getRepository({r.target}).createQueryBuilder("e").where("e.{member(L, r.foreign_key)} = :id", {{ id }});')
            ctc = tenant_column(tables[r.target])
            if ctc:
                w(f'    qb.andWhere("e.{member(L, ctc.name)} = :tenant", {{ tenant: tenantOf(this.em) }});')
            w(f'    return runPage(qb, "e", PAGING_{snake(r.target).upper()}, page);')
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params, clauses, guards = [], [], []
            for i, c in enumerate(q.where):
                col = t.col(c.column)
                prop = f"e.{m[c.column]}"
                if c.param:
                    pn = member(L, c.param)
                    pt = f"{TS_TYPE[col.type]}[]" if c.op == "in" else TS_TYPE[col.type]
                    params.append(f"{pn}: {pt}")
                    key, val = pn, ("likePrefix(" + pn + ")" if c.op == "prefix" else pn)
                    if c.op == "in":
                        guards.append(pn)
                else:
                    key, val = f"k{i}", (_ts_value(col, c.value) if c.has_value else None)
                    if c.has_value and c.op == "prefix":
                        val = f"likePrefix({val})"
                clauses.append(_ts_cond(prop, c.op, key, val))
            order = [(m[cn], member(L, cn), t.col(cn).type, d) for cn, d in t.order(q.order_by or None)]
            order_lit = "[" + ", ".join(f'{{ prop: "{a}", json: "{j}", type: "{ty}", desc: {str(d).lower()} }}' for a, j, ty, d in order) + "]"
            if k == "query_page":
                params.append("page: PageRequest = {}")
            sig = ", ".join(params)
            ret = {"query_page": f"Page<{t.name}>", "query_list": f"{t.name}[]", "query_one": f"{t.name} | null"}[k]
            w(f"  async {name}({sig}): Promise<{ret}> {{")
            for g in guards:
                empty = {"query_page": f"emptyPage<{t.name}>({paging}, page)", "query_list": "[]", "query_one": "null"}[k]
                w(f"    if ({g}.length === 0) return {empty};")
            w(f'    const qb = this.repo.createQueryBuilder("e");')
            if tc:
                w(f'    qb.where("e.{tm} = :tenant", {{ tenant: tenantOf(this.em) }});')
            for i, (cond, prm) in enumerate(clauses):
                fn = "where" if i == 0 and not tc else "andWhere"
                w(f"    qb.{fn}({json.dumps(cond)}{', ' + prm if prm else ''});")
            w(f"    const order: OrderItem[] = {order_lit};")
            if k == "query_page":
                w(f'    return runPage(qb, "e", {paging}, page, order);')
            elif k == "query_list":
                w(f'    return orderRows(qb, "e", order).limit({paging}.maxLimit).getMany();')
            else:
                w('    return orderRows(qb, "e", order).limit(1).getOne();')
        w("  }\n")
    out[-1] = out[-1].rstrip("\n")
    w("}")
    return _prune_imports("\n".join(out) + "\n")


def _prune_imports(text: str) -> str:
    """Tiene negli import da ./_paging solo i nomi usati (tsconfig con noUnusedLocals)."""
    import re
    lines = text.split("\n")
    body = "\n".join(l for l in lines if not l.startswith("import "))
    out = []
    for l in lines:
        mt = re.match(r'^import (type )?\{ (.+) \} from "\./_paging";$', l)
        if mt:
            used = [n for n in mt.group(2).split(", ") if re.search(r"\b" + re.escape(n) + r"\b", body)]
            if not used:
                continue
            l = f'import {mt.group(1) or ""}{{ {", ".join(used)} }} from "./_paging";'
        out.append(l)
    return "\n".join(out)


def _base_file() -> str:
    return (header(L, "kit") + "/* eslint-disable */\n" +
            "/** Dati non validi per la tabella: fields contiene campo -> regola violata (mai valori). */\n"
            "export class ModelValidationError extends Error {\n"
            "  constructor(public readonly table: string, public readonly fields: Record<string, string>) {\n"
            '    super(`${table}: dati non validi (${Object.keys(fields).sort().join(", ")})`);\n'
            '    this.name = "ModelValidationError";\n'
            "  }\n"
            "}\n")


def _index_file(tables: Dict[str, Table]) -> str:
    lines = [header(L, "kit") + "/* eslint-disable */\n// Elenco di tutte le entità generate: usalo nella configurazione del DataSource.",
             'export { ModelValidationError } from "./_base";',
             'export type { Page, PageRequest } from "./_paging";',
             'export { runInTransaction, isolationFor } from "./_uow";',
             'export { TenantError, bindTenant, databaseUrlFor, schemaFor, searchPathFor, tenantOf } from "./_tenant";',
             'export type { Isolation, TransactionOptions } from "./_uow";']
    for n in tables:
        lines.append(f'import {{ {n} }} from "./{n}";')
        lines.append(f'export {{ {n}, {base_class(L, n)}, validate{n}, PAGING_{snake(n).upper()} }} from "./{n}";')
        lines.append(f'export type {{ {n}Changes }} from "./{n}";')
    lines.append(f"\nexport const ENTITIES = [{', '.join(tables)}];")
    return "\n".join(lines) + "\n"


def custom_stub(t: Table) -> str:
    return (f"// {t.name}: punto d'ingresso per l'accesso ai dati della tabella {t.db_name}.\n"
            f"// CRUD e relazioni sono ereditati da generated/{t.name}.ts (vedi MODEL_INDEX.md).\n"
            f"// Qui vanno SOLO i metodi custom di questa tabella, con nomi diversi da quelli generati.\n"
            f'import {{ {base_class(L, t.name)} }} from "./generated/{t.name}";\n\n'
            f'export {{ {t.name} }} from "./generated/{t.name}";\n'
            f'export type {{ {t.name}Changes }} from "./generated/{t.name}";\n\n'
            f"export class {repo_class(L, t.name)} extends {base_class(L, t.name)} {{\n"
            "}\n")


def emit(tables: Dict[str, Table], schema_rel: Dict[str, str], opts: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    dialect = opts.get("dialect", "postgres")
    if dialect not in DB_TYPE:
        raise ValueError(f"dialect TypeScript non supportato: {dialect} (ammessi: {', '.join(DB_TYPE)})")
    gen = {f"{GEN_DIR}/_base.ts": _base_file(), f"{GEN_DIR}/index.ts": _index_file(tables),
           f"{GEN_DIR}/_paging.ts": runtime_typescript.paging_file(), f"{GEN_DIR}/_uow.ts": runtime_typescript.uow_file(tables),
           f"{GEN_DIR}/_tenant.ts": runtime_tenant.typescript_file(opts.get("tenant_id_type", "uuid"))}
    for n, t in tables.items():
        gen[f"{GEN_DIR}/{n}.ts"] = _table_file(t, tables, schema_rel[n], dialect)
    custom = {custom_file(L, n): custom_stub(t) for n, t in tables.items()}
    return gen, custom


def _ts_value(col, v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_ts_value(col, x) for x in v) + "]"
    if col.type in ("int",):
        return str(int(v))
    if col.type == "bool":
        return "true" if v else "false"
    return json.dumps(str(v))


def _ts_cond(prop: str, op: str, key: str, val):
    p = f"{{ {key}: {val} }}" if val is not None and val != key else (f"{{ {key} }}" if val == key else "")
    expr = {"eq": f"{prop} = :{key}", "ne": f"{prop} <> :{key}", "lt": f"{prop} < :{key}", "lte": f"{prop} <= :{key}",
            "gt": f"{prop} > :{key}", "gte": f"{prop} >= :{key}", "in": f"{prop} IN (:...{key})",
            "prefix": f"{prop} LIKE :{key} ESCAPE '\\'", "is_null": f"{prop} IS NULL", "not_null": f"{prop} IS NOT NULL"}[op]
    if op in ("is_null", "not_null"):
        p = ""
    return expr, p
