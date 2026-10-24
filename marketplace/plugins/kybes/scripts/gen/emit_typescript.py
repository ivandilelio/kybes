"""Emettitore TypeScript: TypeORM (decorator) con repository basato su EntityManager."""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

import runtime_archive
import runtime_mongo
import runtime_neo4j
import runtime_tenant
import runtime_typescript
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from sqlonly import has_sql
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
    if t.archive and t.archive.read_through:
        w('import { ' + ("asDateTime, " if any(c.type == "datetime" for c in t.columns) else "") + 'readArchived } from "./_archive";')
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

    out += _validation_paging_lines(t, m)

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
            if t.archive and t.archive.read_through:
                ten = "tenantOf(this.em)" if t.tenancy != "none" else "null"
                key = "id.toLowerCase()" if pk.type == "uuid" else ("String(id)" if pkt != "string" else "id")
                w(f"    const found = await this.repo.findOneBy({{ {pkm}: id{tw} }});")
                w("    return found ?? this.fromArchive(id);")
                w("  }\n")
                w("  /** Record archiviato (archive.read_through): oggetto non collegato all'EntityManager, in sola lettura. */")
                w(f"  protected async fromArchive(id: {pkt}): Promise<{t.name} | null> {{")
                w(f'    const doc = await readArchived(this.em, "{t.db_name}", {ten}, {key});')
                w("    if (doc === null) return null;")
                w("    return this.repo.create({")
                for c in t.columns:
                    v = f'doc["{c.name}"]'
                    w(f"      {m[c.name]}: " + (f"asDateTime({v})" if c.type == "datetime" else v) + ",")
                w(f"    }} as DeepPartial<{t.name}>);")
            else:
                w(f"    return this.repo.findOneBy({{ {pkm}: id{tw} }});")
        elif k == "list_page":
            w(f"  async {name}(page: PageRequest = {{}}): Promise<Page<{t.name}>> {{")
            if tc:
                w(f'    const qb = this.repo.createQueryBuilder("e").where("e.{tm} = :tenant", {{ tenant: tenantOf(this.em) }});')
                w(f'    return runPage(qb, "e", {paging}, page);')
            else:
                w(f'    return runPage(this.repo.createQueryBuilder("e"), "e", {paging}, page);')
        elif k == "list_page_expand":
            expandable = [r for r in t.relations if r.kind == "many_to_one" and t.api and r.name in t.api.expandable]
            if expandable:
                w(f"  async {name}(expand: string[], page: PageRequest = {{}}): Promise<Page<{t.name}>> {{")
                if tc:
                    w(f'    const qb = this.repo.createQueryBuilder("e").where("e.{tm} = :tenant", {{ tenant: tenantOf(this.em) }});')
                else:
                    w(f'    const qb = this.repo.createQueryBuilder("e");')
                w("    for (const rel of expand) {")
                for r in expandable:
                    alias = member(L, r.name)
                    w(f'      if (rel === {r.name!r}) qb.leftJoinAndSelect("e.{alias}", "{alias}");')
                w("    }")
                w(f'    return runPage(qb, "e", {paging}, page);')
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


def _validation_paging_lines(t: Table, m: Dict[str, str]) -> List[str]:
    out: List[str] = []
    w = out.append
    pk = t.pk
    pkm = m[pk.name]
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

    return out


def _index_file(tables: Dict[str, Table]) -> str:
    has = has_sql(tables)
    lines = [header(L, "kit") + "/* eslint-disable */\n// Elenco di tutte le entità generate: usalo nella configurazione del DataSource.",
             'export { ModelValidationError } from "./_base";',
             'export type { Page, PageRequest } from "./_paging";',
             *(['export { runInTransaction, isolationFor } from "./_uow";'] if has else []),
             'export { TenantError, bindTenant, databaseUrlFor, schemaFor, searchPathFor, tenantOf } from "./_tenant";',
             *(['export { FileArchiveReader, archiveOf, archivePath, bindArchive } from "./_archive";',
                'export type { ArchiveReader } from "./_archive";',
                'export type { Isolation, TransactionOptions } from "./_uow";'] if has else [])]
    sql = [n for n, t in tables.items() if t.sql_compatible]
    mongo = [n for n, t in tables.items() if t.mongo]
    neo4j = [n for n, t in tables.items() if t.neo4j]
    for n in tables:
        if n in sql:
            lines.append(f'import {{ {n} }} from "./{n}";')
        lines.append(f'export {{ {n}, {base_class(L, n)}, validate{n}, PAGING_{snake(n).upper()} }} from "./{n}";')
        if not tables[n].neo4j:
            lines.append(f'export type {{ {n}Changes }} from "./{n}";')
    if mongo:
        lines.append('export { MongoSession, mongoSession, runInMongoTransaction } from "./_mongo";')
        lines.append('import type { Db } from "mongodb";')
        for n in mongo:
            lines.append(f'import {{ ensureIndexes{n} }} from "./{n}";')
    if neo4j:
        lines.append('export { Neo4jSession, neo4jSession, runInNeo4jTransaction } from "./_neo4j";')
    if has:
        lines.append("\n/** Entità TypeORM (tabelle SQL) per la configurazione del DataSource. */")
        lines.append(f"export const ENTITIES = [{', '.join(sql)}];")
    if mongo:
        lines += ["", "/** Crea gli indici di tutte le collection MongoDB del modello (idempotente). */",
                  "export async function ensureMongoIndexes(db: Db): Promise<void> {"] + [f"  await ensureIndexes{n}(db);" for n in mongo] + ["}"]
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
    sql = has_sql(tables)
    gen = {f"{GEN_DIR}/_base.ts": _base_file(), f"{GEN_DIR}/index.ts": _index_file(tables),
           f"{GEN_DIR}/_paging.ts": runtime_typescript.paging_file(sql),
           f"{GEN_DIR}/_tenant.ts": runtime_tenant.typescript_file(opts.get("tenant_id_type", "uuid"), sql)}
    if sql:  # con sole collection MongoDB: niente Unit of Work SQL né archivio (che lavora sulle tabelle SQL)
        gen[f"{GEN_DIR}/_uow.ts"] = runtime_typescript.uow_file(tables)
        gen[f"{GEN_DIR}/_archive.ts"] = runtime_archive.typescript_file()
    for n, t in tables.items():
        if t.mongo:
            gen[f"{GEN_DIR}/{n}.ts"] = _mongo_table_file(t, tables, schema_rel[n])
        elif t.neo4j:
            gen[f"{GEN_DIR}/{n}.ts"] = _neo4j_table_file(t, tables, schema_rel[n])
        else:
            gen[f"{GEN_DIR}/{n}.ts"] = _table_file(t, tables, schema_rel[n], dialect)
    if any(t.mongo for t in tables.values()):
        gen[f"{GEN_DIR}/_mongo.ts"] = runtime_mongo.typescript_file()
    if any(t.neo4j for t in tables.values()):
        gen[f"{GEN_DIR}/_neo4j.ts"] = runtime_neo4j.typescript_file()
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


# ------------------------------------------------------------------------------------------- MongoDB

def _mongo_cond_ts(field: str, op: str, val: str) -> str:
    return {"eq": f'{{ "{field}": {val} }}', "ne": f'{{ "{field}": {{ $nin: [{val}, null] }} }}', "lt": f'{{ "{field}": {{ $lt: {val} }} }}',
            "lte": f'{{ "{field}": {{ $lte: {val} }} }}', "gt": f'{{ "{field}": {{ $gt: {val} }} }}', "gte": f'{{ "{field}": {{ $gte: {val} }} }}',
            "in": f'{{ "{field}": {{ $in: {val} }} }}', "prefix": f'{{ "{field}": prefix({val}) }}',
            "is_null": f'{{ "{field}": null }}', "not_null": f'{{ "{field}": {{ $ne: null }} }}'}[op]


def _mongo_table_file(t: Table, tables: Dict[str, Table], schema_rel: str) -> str:
    import mongo_plan
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], TS_TYPE[pk.type]
    T = t.name
    tc = tenant_column(t)
    fields = {m[c.name]: mongo_plan.field_name(t, c) for c in t.columns}
    parents = [r for r in t.relations if r.kind == "many_to_one"]
    kids = mongo_plan.children(t, tables)
    out: List[str] = []
    w = out.append
    w(header(L, schema_rel) + "/* eslint-disable */")
    w(f"// {T}: entità e repository della collection MongoDB {t.db_name}.{(' ' + t.description) if t.description else ''}")
    if pk.auto and pk.type == "uuid":
        w('import { randomUUID } from "node:crypto";')
    w('import type { Db, Filter } from "mongodb";')
    w('import { ModelValidationError } from "./_base";')
    w('import { findSorted, fromBson, MongoSession, nextId, prefix, runMongoPage, toBson } from "./_mongo";')
    w('import type { KybesDocument, KybesId } from "./_mongo";')
    w('import { emptyPage } from "./_paging";')
    w('import type { OrderItem, Page, PageRequest, PagingSpec } from "./_paging";')
    if t.tenancy != "none":
        w('import { tenantOf } from "./_tenant";')
    for tg in sorted({r.target for r in t.relations if r.target != T}):
        w(f'import {{ {tg}, {base_class(L, tg)} }} from "./{tg}";')
    w("")
    w(f"/** Documento della collection {t.db_name}. I valori non indicati valgono il default dello schema. */")
    w(f"export class {T} {{")
    for c in t.columns:
        if c.default is not None:
            w(f"  {m[c.name]}: {_ts_type(c)} = {_ts_value(c, c.default)};")
        else:
            w(f"  {m[c.name]}!: {_ts_type(c)};")
    w("}\n")
    out += _validation_paging_lines(t, m)
    w(f"export const FIELDS_{snake(T).upper()}: Record<string, string> = {{ " + ", ".join(f'{a}: "{f}"' for a, f in fields.items()) + " };\n")
    w("/** Documento MongoDB del record: le colonne vuote non compaiono. */")
    w(f"export function toDocument(e: {T}): KybesDocument {{")
    w("  const doc: KybesDocument = {")
    for c in t.columns:
        w(f'    "{fields[m[c.name]]}": toBson(e.{m[c.name]}, "{c.type}"){" as KybesId" if c.primary_key else ""},')
    w("  };")
    w("  return Object.fromEntries(Object.entries(doc).filter(([, v]) => v !== null)) as KybesDocument;")
    w("}\n")
    w(f"export function fromDocument(d: KybesDocument): {T} {{")
    w(f"  return Object.assign(new {T}(), {{")
    for c in t.columns:
        w(f'    {m[c.name]}: fromBson(d["{fields[m[c.name]]}"], "{c.type}"),')
    w(f"  }}) as {T};")
    w("}\n")
    w(f"/** Indici della collection (stessi nomi del DDL SQL); idempotente: si chiama all'avvio o nel deploy. */")
    w(f"export async function ensureIndexes{T}(db: Db): Promise<void> {{")
    ixs = mongo_plan.indexes(t)
    if ixs:
        w(f'  const col = db.collection("{t.db_name}");')
    for ix in ixs:
        opts = [f'name: "{ix.name}"']
        if ix.unique:
            opts.append("unique: true")
        if ix.partial:
            opts.append("partialFilterExpression: { " + ", ".join(f'"{f}": {{ $exists: true }}' for f in ix.partial) + " }")
        if ix.ttl is not None:
            opts.append(f"expireAfterSeconds: {ix.ttl}")
        w(f"  await col.createIndex({{ " + ", ".join(f'"{f}": 1' for f in ix.fields) + " }, { " + ", ".join(opts) + " });")
    if not ixs:
        w("  void db; // nessun indice oltre a _id")
    w("}\n")

    updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated and not c.tenant]
    upd_t = f"Pick<{T}, " + (" | ".join(json.dumps(x) for x in updatable) or "never") + ">"
    w(f"export type {T}Changes = Partial<{upd_t}>;\n")
    paging = f"PAGING_{snake(T).upper()}"
    w(f"/** CRUD, relazioni e query di {T} su MongoDB. Per una transazione passa la sessione di runInMongoTransaction. */")
    w(f"export class {base_class(L, T)} {{")
    w(f'  protected static readonly COLLECTION = "{t.db_name}";\n')
    if t.tenancy != "none":
        w("  constructor(protected readonly em: MongoSession) {")
        w(f"    tenantOf(em); // tenancy: {t.tenancy}: senza un tenant legato alla sessione il repository non lavora")
        w("  }\n")
    else:
        w("  constructor(protected readonly em: MongoSession) {}\n")
    w("  protected get col() {")
    w(f'    return this.em.collection("{t.db_name}");')
    w("  }\n")
    w("  protected scope(filter: Filter<KybesDocument>): Filter<KybesDocument> {")
    if tc:
        w(f'    return {{ $and: [filter, {{ "{tc.db_name}": toBson(tenantOf(this.em), "{tc.type}") }}] }};')
    else:
        w("    return filter;")
    w("  }\n")
    w(f"  /** Lettura per chiave (anche dai repository collegati). */")
    w(f"  async find(id: {pkt}): Promise<{T} | null> {{")
    w(f'    const d = await this.col.findOne(this.scope({{ _id: toBson(id, "{pk.type}") as KybesId }}), {{ session: this.em.session }});')
    w("    return d === null ? null : fromDocument(d);")
    w("  }\n")
    w("  /** Tenant della sessione e record collegati esistenti (MongoDB non ha chiavi esterne). */")
    w(f"  protected async check(entity: {T}): Promise<void> {{")
    if tc:
        tm = m[tc.name]
        w("    const tenant = tenantOf(this.em);")
        w(f"    if (entity.{tm} !== undefined && entity.{tm} !== null && entity.{tm} !== tenant) {{")
        w(f'      throw new ModelValidationError("{T}", {{ {tc.name}: "tenant diverso da quello della sessione" }});')
        w("    }")
        w(f"    entity.{tm} = tenant;")
    w(f"    validate{T}(entity);")
    if parents:
        w("    const errors: Record<string, string> = {};")
        for r in parents:
            fk = m[r.foreign_key]
            w(f"    if (entity.{fk} !== undefined && entity.{fk} !== null && (await new {base_class(L, r.target)}(this.em).find(entity.{fk})) === null) {{")
            w(f'      errors["{r.foreign_key}"] = "non trovato";')
            w("    }")
        w(f'    if (Object.keys(errors).length > 0) throw new ModelValidationError("{T}", errors);')
    w("  }\n")
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"  /** {meth.summary} */")
        if k == "get_by_id":
            w(f"  async {name}(id: {pkt}): Promise<{T} | null> {{")
            w("    return this.find(id);")
        elif k == "list_page":
            w(f"  async {name}(page: PageRequest = {{}}): Promise<Page<{T}>> {{")
            w(f'    return runMongoPage(this.em, "{t.db_name}", {paging}, FIELDS_{snake(T).upper()}, this.scope({{}}), page, fromDocument);')
        elif k == "count":
            w(f"  async {name}(): Promise<number> {{")
            w("    return this.col.countDocuments(this.scope({}), { session: this.em.session });")
        elif k == "exists":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w(f'    return (await this.col.countDocuments(this.scope({{ _id: toBson(id, "{pk.type}") as KybesId }}), {{ limit: 1, session: this.em.session }})) > 0;')
        elif k == "create":
            w(f"  async {name}(data: Partial<{T}>): Promise<{T}> {{")
            w(f"    const entity = Object.assign(new {T}(), data);")
            w("    await this.check(entity);")
            if pk.auto:
                gen = "randomUUID()" if pk.type == "uuid" else (f'String(await nextId(this.em, "{t.db_name}"))' if pk.type == "bigint" else f'await nextId(this.em, "{t.db_name}")')
                w(f"    if (entity.{pkm} === undefined || entity.{pkm} === null) entity.{pkm} = {gen};")
            for c in t.columns:
                if c.generated:
                    w(f"    entity.{m[c.name]} = new Date();")
            w("    await this.col.insertOne(toDocument(entity), { session: this.em.session });")
            w("    return entity;")
        elif k == "update":
            w(f"  async {name}(id: {pkt}, changes: {T}Changes): Promise<{T} | null> {{")
            w(f"    const allowed = new Set<string>({json.dumps(updatable)});")
            w("    const unknown = Object.keys(changes).filter((key) => !allowed.has(key));")
            w(f'    if (unknown.length > 0) throw new ModelValidationError("{T}", Object.fromEntries(unknown.map((key) => [key, "campo non modificabile"])));')
            w("    const entity = await this.find(id);")
            w("    if (entity === null) return null;")
            w("    Object.assign(entity, changes);")
            w("    await this.check(entity);")
            for c in t.columns:
                if c.generated == "on_update":
                    w(f"    entity.{m[c.name]} = new Date();")
            w(f'    await this.col.replaceOne(this.scope({{ _id: toBson(id, "{pk.type}") as KybesId }}), toDocument(entity), {{ session: this.em.session }});')
            w("    return entity;")
        elif k == "delete":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w("    if ((await this.find(id)) === null) return false;")
            for c, r in kids:
                ctc = tenant_column(c)
                fk_f = mongo_plan.field_name(c, c.col(r.foreign_key))
                flt = f'{{ "{fk_f}": toBson(id, "{pk.type}")' + (f', "{ctc.db_name}": toBson(tenantOf(this.em), "{ctc.type}")' if ctc else "") + " }"
                if r.on_delete == "restrict":
                    w(f'    if ((await this.em.collection("{c.db_name}").countDocuments({flt}, {{ limit: 1, session: this.em.session }})) > 0) {{')
                    w(f'      throw new ModelValidationError("{T}", {{ {mongo_plan.child_label(t, c, r)}: "record collegati" }});')
                    w("    }")
                else:
                    w(f'    await this.em.collection("{c.db_name}").updateMany({flt}, {{ $unset: {{ "{fk_f}": "" }} }}, {{ session: this.em.session }});')
            w(f'    await this.col.deleteOne(this.scope({{ _id: toBson(id, "{pk.type}") as KybesId }}), {{ session: this.em.session }});')
            w("    return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}): Promise<{T} | null> {{")
            w(f'    const d = await this.col.findOne(this.scope({{ "{fields[m[arg]]}": toBson(value, "{c.type}") }}), {{ session: this.em.session }});')
            w("    return d === null ? null : fromDocument(d);")
        elif k == "list_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}, page: PageRequest = {{}}): Promise<Page<{T}>> {{")
            w(f'    const filter = this.scope({{ "{fields[m[arg]]}": toBson(value, "{c.type}") }});')
            w(f'    return runMongoPage(this.em, "{t.db_name}", {paging}, FIELDS_{snake(T).upper()}, filter, page, fromDocument);')
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            fk = m[r.foreign_key]
            w(f"  async {name}(id: {pkt}): Promise<{r.target} | null> {{")
            w("    const entity = await this.find(id);")
            if t.col(r.foreign_key).nullable:
                w(f"    if (entity === null || entity.{fk} === undefined || entity.{fk} === null) return null;")
            else:
                w("    if (entity === null) return null;")
            w(f"    return new {base_class(L, r.target)}(this.em).find(entity.{fk});")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"  async {name}(id: {pkt}, page: PageRequest = {{}}): Promise<Page<{r.target}>> {{")
            w(f"    return new {base_class(L, r.target)}(this.em).{method_name(L, 'list_by:' + r.foreign_key)}(id, page);")
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params, conds, guards = [], [], []
            for c in q.where:
                col = t.col(c.column)
                if c.param:
                    pn = member(L, c.param)
                    pt = f"{TS_TYPE[col.type]}[]" if c.op == "in" else TS_TYPE[col.type]
                    params.append(f"{pn}: {pt}")
                    raw = pn
                    if c.op == "in":
                        guards.append(pn)
                else:
                    raw = _ts_value(col, c.value) if c.has_value else "null"
                if c.op == "in":
                    val = f'{raw}.map((x) => toBson(x, "{col.type}"))'
                elif c.op == "prefix":
                    val = raw
                else:
                    val = f'toBson({raw}, "{col.type}")'
                conds.append(_mongo_cond_ts(mongo_plan.field_name(t, col), c.op, val))
            order = [(m[cn], member(L, cn), t.col(cn).type, d) for cn, d in t.order(q.order_by or None)]
            order_lit = "[" + ", ".join(f'{{ prop: "{a}", json: "{j}", type: "{ty}", desc: {str(d).lower()} }}' for a, j, ty, d in order) + "]"
            if k == "query_page":
                params.append("page: PageRequest = {}")
            ret = {"query_page": f"Page<{T}>", "query_list": f"{T}[]", "query_one": f"{T} | null"}[k]
            w(f"  async {name}({', '.join(params)}): Promise<{ret}> {{")
            for g in guards:
                empty = {"query_page": f"emptyPage<{T}>({paging}, page)", "query_list": "[]", "query_one": "null"}[k]
                w(f"    if ({g}.length === 0) return {empty};")
            w(f"    const filter = this.scope({{ $and: [{', '.join(conds)}] }});")
            w(f"    const order: OrderItem[] = {order_lit};")
            if k == "query_page":
                w(f'    return runMongoPage(this.em, "{t.db_name}", {paging}, FIELDS_{snake(T).upper()}, filter, page, fromDocument, order);')
            elif k == "query_list":
                w(f'    return (await findSorted(this.em, "{t.db_name}", filter, FIELDS_{snake(T).upper()}, order, {paging}.maxLimit)).map(fromDocument);')
            else:
                w(f'    const docs = await findSorted(this.em, "{t.db_name}", filter, FIELDS_{snake(T).upper()}, order, 1);')
                w("    return docs.length > 0 ? fromDocument(docs[0]) : null;")
        w("  }\n")
    out[-1] = out[-1].rstrip("\n")
    w("}")
    return _prune_mongo_imports("\n".join(out) + "\n")


def _prune_mongo_imports(text: str) -> str:
    """Tiene negli import solo i nomi usati (tsconfig con noUnusedLocals)."""
    import re
    lines = text.split("\n")
    body = "\n".join(x for x in lines if not x.startswith("import "))
    out = []
    for x in lines:
        mt = re.match(r'^import (type )?\{ (.+) \} from "(\./_mongo|\./_paging|mongodb)";$', x)
        if mt:
            used = [n for n in mt.group(2).split(", ") if re.search(rf"\b{n}\b", body)]
            if not used:
                continue
            x = f'import {mt.group(1) or ""}{{ {", ".join(used)} }} from "{mt.group(3)}";'
        out.append(x)
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- Neo4j

def _neo4j_table_file(t: Table, tables: Dict[str, Table], schema_rel: str) -> str:
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], TS_TYPE[pk.type]
    T = t.name
    tc = tenant_column(t)
    labels = t.neo4j_config.labels if t.neo4j_config else [T]
    label_str = ":".join(labels)
    out: List[str] = []
    w = out.append
    w(header(L, schema_rel) + "/* eslint-disable */")
    w(f"// {T}: entità e repository Neo4j (storage: neo4j, nodo :{label_str}).{(' ' + t.description) if t.description else ''}")
    w('import { ModelValidationError } from "./_base";')
    w('import { Neo4jSession, toNeo4j, runNeo4jPage } from "./_neo4j";')
    w('import type { OrderItem, Page, PageRequest, PagingSpec } from "./_paging";')
    if tc:
        w('import { tenantOf } from "./_tenant";')
    w("")

    # --- class
    w(f"export class {T} {{")
    for c in t.columns:
        w(f"  {m[c.name]}!: {_ts_type(c)};")
    w("}\n")

    # --- validation + paging
    out += _validation_paging_lines(t, m)

    # --- fromRecord
    w(f"function fromRecord(record: {{ get(key: string): {{ properties: Record<string, unknown> }} }}): {T} {{")
    w('  const n = record.get("n").properties;')
    w(f"  return Object.assign(new {T}(), {{")
    for c in t.columns:
        w(f'    {m[c.name]}: n["{c.db_name}"] as {TS_TYPE[c.type]}{" | null" if c.nullable else ""},')
    w(f"  }});")
    w("}\n")

    # --- toJson
    w(f"function toJson(e: {T}): Record<string, unknown> {{")
    w("  return {")
    for c in t.columns:
        w(f'    {m[c.name]}: e.{m[c.name]},')
    w("  };")
    w("}\n")

    # --- repository
    tenant_filter = f" AND n.{tc.db_name} = $tenant" if tc else ""

    def _params(extra: str = "") -> str:
        parts = [extra] if extra else []
        if tc:
            parts.append('"tenant": tenantOf(this.session)')
        return "{ " + ", ".join(parts) + " }" if parts else "{}"

    w(f"export class {base_class(L, T)} {{")
    w(f"  private static readonly PAGING = PAGING_{snake(T).upper()};")
    w(f'  private static readonly LABELS = "{label_str}";\n')
    if tc:
        w(f"  constructor(private readonly session: Neo4jSession) {{")
        w(f"    tenantOf(session);")
        w("  }\n")
    else:
        w(f"  constructor(private readonly session: Neo4jSession) {{}}\n")

    # get_by_id
    w(f"  async getById(id: {pkt}): Promise<{T} | null> {{")
    w(f"    const result = await this.session.session.run(")
    w(f'      "MATCH (n:{label_str}) WHERE n.{pk.db_name} = $id{tenant_filter} RETURN n LIMIT 1",')
    w(f"      {_params(f'\"id\": toNeo4j(id)')},")
    w("    );")
    w("    const record = result.records[0];")
    w("    return record ? fromRecord(record) : null;")
    w("  }\n")

    # list_page
    match_clause = f"MATCH (n:{label_str})"
    if tc:
        match_clause += f" WHERE n.{tc.db_name} = $tenant"
    w(f"  async listPage(page?: PageRequest): Promise<Page<{T}>> {{")
    w(f"    return runNeo4jPage(this.session, \"{match_clause} RETURN n\",")
    w(f"      {_params()}, {base_class(L, T)}.PAGING, page, fromRecord);")
    w("  }\n")

    # count
    where = f" WHERE n.{tc.db_name} = $tenant" if tc else ""
    w(f"  async count(): Promise<number> {{")
    w(f"    const result = await this.session.session.run(")
    w(f'      "MATCH (n:{label_str}){where} RETURN count(n) AS c",')
    w(f"      {_params()},")
    w("    );")
    w("    return result.records[0].get('c').toNumber();")
    w("  }\n")

    # exists
    w(f"  async exists(id: {pkt}): Promise<boolean> {{")
    w(f"    const result = await this.session.session.run(")
    w(f'      "MATCH (n:{label_str}) WHERE n.{pk.db_name} = $id{tenant_filter} RETURN count(n) > 0 AS e",')
    w(f"      {_params(f'\"id\": toNeo4j(id)')},")
    w("    );")
    w("    return result.records[0].get('e');")
    w("  }\n")

    # create
    props_cypher = ", ".join(f"{c.db_name}: ${m[c.name]}" for c in t.columns)
    params_create = ", ".join(f'"{m[c.name]}": toNeo4j(e.{m[c.name]})' for c in t.columns)
    w(f"  async create(e: {T}): Promise<{T}> {{")
    w(f"    validate{T}(e);")
    w(f"    const result = await this.session.session.run(")
    w(f'      "CREATE (n:{label_str} {{{props_cypher}}}) RETURN n",')
    w(f"      {{ {params_create} }},")
    w("    );")
    w("    return fromRecord(result.records[0]);")
    w("  }\n")

    # update
    set_parts = ", ".join(f"n.{c.db_name} = ${m[c.name]}" for c in t.columns if not c.primary_key)
    params_update = ", ".join(f'"{m[c.name]}": toNeo4j(e.{m[c.name]})' for c in t.columns)
    w(f"  async update(e: {T}): Promise<{T}> {{")
    w(f"    validate{T}(e);")
    w(f"    const result = await this.session.session.run(")
    w(f'      "MATCH (n:{label_str}) WHERE n.{pk.db_name} = $id{tenant_filter} SET {set_parts} RETURN n",')
    w(f'      {{ "id": toNeo4j(e.{pkm}), {params_update} }},')
    w("    );")
    w("    if (result.records.length === 0) {")
    w(f'      throw new ModelValidationError("{T}", {{ id: "non trovato" }});')
    w("    }")
    w("    return fromRecord(result.records[0]);")
    w("  }\n")

    # delete
    w(f"  async delete(id: {pkt}): Promise<void> {{")
    w(f"    await this.session.session.run(")
    w(f'      "MATCH (n:{label_str}) WHERE n.{pk.db_name} = $id{tenant_filter} DETACH DELETE n",')
    w(f"      {_params(f'\"id\": toNeo4j(id)')},")
    w("    );")
    w("  }")
    w("}")

    return "\n".join(out) + "\n"
