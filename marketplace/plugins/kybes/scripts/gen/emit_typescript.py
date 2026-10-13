"""Emettitore TypeScript: TypeORM (decorator) con repository basato su EntityManager."""
from __future__ import annotations

import json
from typing import Dict, Tuple

from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from schema import Table, index_specs, methods_of, snake

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
    for tg in targets:
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
        if c.required and not (c.primary_key and c.auto) and not c.generated and c.default is None:
            w(f'  if (e.{mm} === undefined || e.{mm} === null) errors["{c.name}"] = "obbligatorio";')
        if c.type == "string":
            w(f'  if (typeof e.{mm} === "string" && e.{mm}.length > {c.length}) errors["{c.name}"] = "lunghezza massima {c.length}";')
    w(f'  if (Object.keys(errors).length > 0) throw new ModelValidationError("{t.name}", errors);')
    w("}\n")

    updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated]
    upd_t = f"Pick<{t.name}, " + (" | ".join(json.dumps(x) for x in updatable) or "never") + ">"
    w(f"export type {t.name}Changes = Partial<{upd_t}>;\n")
    w(f"/** CRUD e relazioni di {t.name}. Per una transazione passa l'EntityManager della transazione. */")
    w(f"export class {base_class(L, t.name)} {{")
    w("  constructor(protected readonly em: EntityManager) {}\n")
    w(f"  protected get repo(): Repository<{t.name}> {{")
    w(f"    return this.em.getRepository({t.name});")
    w("  }\n")
    order = f'{{ {pkm}: "ASC" as const }}'
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"  /** {meth.summary} */")
        if k == "get_by_id":
            w(f"  async {name}(id: {pkt}): Promise<{t.name} | null> {{")
            w(f"    return this.repo.findOneBy({{ {pkm}: id }});")
        elif k == "list":
            w(f"  async {name}(skip = 0, take = 100): Promise<{t.name}[]> {{")
            w(f"    return this.repo.find({{ order: {order}, skip, take }});")
        elif k == "count":
            w(f"  async {name}(): Promise<number> {{")
            w("    return this.repo.count();")
        elif k == "exists":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w(f"    return (await this.repo.countBy({{ {pkm}: id }})) > 0;")
        elif k == "create":
            w(f"  async {name}(data: DeepPartial<{t.name}>): Promise<{t.name}> {{")
            w("    const entity = this.repo.create(data);")
            w(f"    validate{t.name}(entity);")
            w("    return this.repo.save(entity);")
        elif k == "update":
            w(f"  async {name}(id: {pkt}, changes: {t.name}Changes): Promise<{t.name} | null> {{")
            w(f"    const allowed = new Set<string>({json.dumps(updatable)});")
            w("    const unknown = Object.keys(changes).filter((key) => !allowed.has(key));")
            w(f'    if (unknown.length > 0) throw new ModelValidationError("{t.name}", Object.fromEntries(unknown.map((key) => [key, "campo non modificabile"])));')
            w(f"    const entity = await this.repo.findOneBy({{ {pkm}: id }});")
            w("    if (!entity) return null;")
            w("    Object.assign(entity, changes);")
            w(f"    validate{t.name}(entity);")
            w("    return this.repo.save(entity);")
        elif k == "delete":
            w(f"  async {name}(id: {pkt}): Promise<boolean> {{")
            w(f"    if ((await this.repo.countBy({{ {pkm}: id }})) === 0) return false;")
            w(f"    await this.repo.delete({{ {pkm}: id }});")
            w("    return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}): Promise<{t.name} | null> {{")
            w(f"    return this.repo.findOneBy({{ {m[arg]}: value }});")
        elif k == "list_by":
            c = t.col(arg)
            w(f"  async {name}(value: {TS_TYPE[c.type]}, skip = 0, take = 100): Promise<{t.name}[]> {{")
            w(f"    return this.repo.find({{ where: {{ {m[arg]}: value }}, order: {order}, skip, take }});")
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            rn = member(L, r.name)
            w(f"  async {name}(id: {pkt}): Promise<{r.target} | null> {{")
            w(f"    const entity = await this.repo.findOne({{ where: {{ {pkm}: id }}, relations: {{ {rn}: true }} }});")
            w(f"    return entity?.{rn} ?? null;")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            tg = tables[r.target]
            tpk = member(L, tg.pk.name)
            w(f"  async {name}(id: {pkt}, skip = 0, take = 100): Promise<{r.target}[]> {{")
            w(f"    return this.em.getRepository({r.target}).find({{ where: {{ {member(L, r.foreign_key)}: id }}, "
              f'order: {{ {tpk}: "ASC" as const }}, skip, take }});')
        w("  }\n")
    out[-1] = out[-1].rstrip("\n")
    w("}")
    return "\n".join(out) + "\n"


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
             'export { ModelValidationError } from "./_base";']
    for n in tables:
        lines.append(f'import {{ {n} }} from "./{n}";')
        lines.append(f'export {{ {n}, {base_class(L, n)}, validate{n} }} from "./{n}";')
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
    gen = {f"{GEN_DIR}/_base.ts": _base_file(), f"{GEN_DIR}/index.ts": _index_file(tables)}
    for n, t in tables.items():
        gen[f"{GEN_DIR}/{n}.ts"] = _table_file(t, tables, schema_rel[n], dialect)
    custom = {custom_file(L, n): custom_stub(t) for n, t in tables.items()}
    return gen, custom
