"""Emettitore Java: JPA (jakarta.persistence) con repository basato su EntityManager."""
from __future__ import annotations

from typing import Dict, Tuple

import runtime_java
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from schema import SORTABLE_TYPES, Table, index_specs, methods_of, snake

L = "java"

J_TYPE = {"uuid": "UUID", "string": "String", "text": "String", "int": "Integer", "bigint": "Long",
          "decimal": "BigDecimal", "bool": "Boolean", "date": "LocalDate", "datetime": "OffsetDateTime", "json": "String"}


def _lit(c) -> str:
    v = c.default
    if isinstance(v, bool):
        return "Boolean.TRUE" if v else "Boolean.FALSE"
    if c.type in ("string", "text"):
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if c.type == "decimal":
        return f'new BigDecimal("{v}")'
    if c.type == "bigint":
        return f"{v}L"
    return str(v)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _entity_file(t: Table, tables: Dict[str, Table], schema_rel: str, pkg: str, dialect: str) -> str:
    gpkg = f"{pkg}.{GEN_DIR}"
    m = {c.name: member(L, c.name) for c in t.columns}
    out = []
    w = out.append
    w(header(L, schema_rel).rstrip("\n"))
    w(f"package {gpkg};\n")
    w("import jakarta.persistence.*;")
    if any(c.type == "json" for c in t.columns) and dialect == "postgres":
        w("import org.hibernate.annotations.JdbcTypeCode;")
        w("import org.hibernate.type.SqlTypes;")
    if any(r.kind == "many_to_one" and r.on_delete != "restrict" for r in t.relations):
        w("import org.hibernate.annotations.OnDelete;")
        w("import org.hibernate.annotations.OnDeleteAction;")
    w("import java.math.BigDecimal;")
    w("import java.time.LocalDate;")
    w("import java.time.OffsetDateTime;")
    w("import java.util.ArrayList;")
    w("import java.util.List;")
    w("import java.util.UUID;\n")
    w(f"/** {t.name}: entità della tabella {t.db_name}.{(' ' + t.description) if t.description else ''} */")
    w("@Entity")
    specs = index_specs(t)
    uq = [s for s in specs if s.unique]
    ix = [s for s in specs if not s.unique]
    tbl = [f'name = "{t.db_name}"']
    if uq:
        tbl.append("uniqueConstraints = {" + ", ".join(
            f'@UniqueConstraint(name = "{s.name}", columnNames = {{{", ".join(chr(34) + t.col(c).db_name + chr(34) for c in s.columns)}}})' for s in uq) + "}")
    if ix:
        tbl.append("indexes = {" + ", ".join(
            f'@Index(name = "{s.name}", columnList = "{", ".join(t.col(c).db_name for c in s.columns)}")' for s in ix) + "}")
    w("@Table(" + ", ".join(tbl) + ")")
    w(f"public class {t.name} {{\n")
    for c in t.columns:
        if c.primary_key:
            w("    @Id")
            if c.auto:
                strat = "UUID" if c.type == "uuid" else "IDENTITY"
                w(f"    @GeneratedValue(strategy = GenerationType.{strat})")
        attrs = [f'name = "{c.db_name}"', f"nullable = {str(c.nullable).lower()}"]
        if c.type == "string":
            attrs.append(f"length = {c.length}")
        if c.type == "decimal":
            attrs += [f"precision = {c.precision}", f"scale = {c.scale}"]
        if c.primary_key or c.generated == "on_create":
            attrs.append("updatable = false")
        if c.type == "text":
            attrs.append('columnDefinition = "text"')
        if c.type == "json":
            attrs.append('columnDefinition = "jsonb"' if dialect == "postgres" else 'columnDefinition = "text"')
        if c.type == "json" and dialect == "postgres":
            w("    @JdbcTypeCode(SqlTypes.JSON)")
        w(f"    @Column({', '.join(attrs)})")
        init = f" = {_lit(c)}" if c.default is not None else ""
        w(f"    private {J_TYPE[c.type]} {m[c.name]}{init};\n")
    for r in t.relations:
        rn = member(L, r.name)
        if r.kind == "many_to_one":
            fkc = t.col(r.foreign_key)
            w(f"    @ManyToOne(fetch = FetchType.LAZY, optional = {str(fkc.nullable).lower()})")
            w(f'    @JoinColumn(name = "{fkc.db_name}", insertable = false, updatable = false)')
            if r.on_delete != "restrict":
                w(f"    @OnDelete(action = OnDeleteAction.{'CASCADE' if r.on_delete == 'cascade' else 'SET_NULL'})")
            w(f"    private {r.target} {rn};\n")
        else:
            w(f'    @OneToMany(mappedBy = "{member(L, r.inverse)}", fetch = FetchType.LAZY)')
            w(f"    private List<{r.target}> {rn} = new ArrayList<>();\n")
    gens = [c for c in t.columns if c.generated]
    if gens:
        w("    @PrePersist")
        w("    void onCreate() {")
        w("        OffsetDateTime now = OffsetDateTime.now();")
        for c in gens:
            w(f"        this.{m[c.name]} = now;")
        w("    }\n")
        upd = [c for c in gens if c.generated == "on_update"]
        if upd:
            w("    @PreUpdate")
            w("    void onUpdate() {")
            for c in upd:
                w(f"        this.{m[c.name]} = OffsetDateTime.now();")
            w("    }\n")
    for c in t.columns:
        jt, mm = J_TYPE[c.type], m[c.name]
        w(f"    public {jt} get{_cap(mm)}() {{ return {mm}; }}")
        if not (c.primary_key and c.auto) and not c.generated:
            rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
            if rel:
                rn = member(L, rel.name)
                tpk = _cap(member(L, tables[rel.target].pk.name))
                w(f"    public void set{_cap(mm)}({jt} value) {{")
                w(f"        this.{mm} = value;")
                w(f"        if (this.{rn} != null && !java.util.Objects.equals(this.{rn}.get{tpk}(), value)) this.{rn} = null;")
                w("    }")
            else:
                w(f"    public void set{_cap(mm)}({jt} value) {{ this.{mm} = value; }}")
    for r in t.relations:
        rn = member(L, r.name)
        jt = r.target if r.kind == "many_to_one" else f"List<{r.target}>"
        w(f"    public {jt} get{_cap(rn)}() {{ return {rn}; }}")
        if r.kind == "many_to_one":
            fk = m[r.foreign_key]
            tpk = member(L, tables[r.target].pk.name)
            w(f"    public void set{_cap(rn)}({jt} value) {{")
            w(f"        this.{rn} = value;")
            w(f"        this.{fk} = value == null ? null : value.get{_cap(tpk)}();")
            w("    }")
    w("")
    sortable_cols = [c for c in t.columns if c.type in SORTABLE_TYPES and not c.nullable]
    w("    /** Valore di una colonna ordinabile, usato dal cursore di paginazione. */")
    w("    public Object kybesValue(String field) {")
    w("        return switch (field) {")
    for c in sortable_cols:
        w(f'            case "{m[c.name]}" -> {m[c.name]};')
    w('            default -> throw new IllegalArgumentException("colonna non ordinabile: " + field);')
    w("        };")
    w("    }\n")
    # ---- validazione
    w("    /** Validazione di modello prima della persistenza. */")
    w("    public void validate() {")
    w("        java.util.Map<String, String> errors = new java.util.TreeMap<>();")
    for c in t.columns:
        mm = m[c.name]
        if c.required and not (c.primary_key and c.auto) and not c.generated:
            w(f'        if ({mm} == null) errors.put("{c.name}", "obbligatorio");')
        if c.type == "string":
            w(f'        if ({mm} != null && {mm}.length() > {c.length}) errors.put("{c.name}", "lunghezza massima {c.length}");')
    w(f'        if (!errors.isEmpty()) throw new ModelValidationException("{t.name}", errors);')
    w("    }")
    w("}")
    return "\n".join(out) + "\n"


def _repo_file(t: Table, tables: Dict[str, Table], schema_rel: str, pkg: str) -> str:
    gpkg = f"{pkg}.{GEN_DIR}"
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], J_TYPE[pk.type]
    base = base_class(L, t.name)
    out = []
    w = out.append
    w(header(L, schema_rel).rstrip("\n"))
    w(f"package {gpkg};\n")
    w("import jakarta.persistence.EntityManager;")
    w("import java.math.BigDecimal;")
    w("import java.time.LocalDate;")
    w("import java.time.OffsetDateTime;")
    w("import java.util.Collection;")
    w("import java.util.List;")
    w("import java.util.Map;")
    w("import java.util.Objects;")
    w("import java.util.Optional;")
    w("import java.util.UUID;\n")
    w(f"/** CRUD e relazioni di {t.name}. La transazione la gestisce il chiamante. Metodi custom: model/{custom_file(L, t.name)}. */")
    w(f"public abstract class {base} {{\n")
    def oi(cn, d):
        return f'new Paging.OrderItem("{m[cn]}", "{member("typescript", cn)}", Paging.SortType.{t.col(cn).type.upper()}, {str(d).lower()})'
    w(f'    public static final Paging.Spec PAGING = new Paging.Spec("{t.name}", "{t.name}",')
    w(f"            {oi(pk.name, False)},")
    entries = ", ".join(f'Map.entry("{member("typescript", cn)}", {oi(cn, False)})' for cn in t.pagination.sortable)
    w(f"            Map.ofEntries({entries}),")
    w(f"            List.of({', '.join(oi(cn, d) for cn, d in t.order())}),")
    w(f"            {t.pagination.default_limit}, {t.pagination.max_limit});\n")
    w("    protected final EntityManager em;\n")
    w(f"    protected {base}(EntityManager em) {{")
    w("        this.em = em;")
    w("    }\n")
    sync = [r for r in t.relations if r.kind == "many_to_one"]
    if sync:
        w("    /** Allinea chiavi esterne e relazioni: vale sia impostare l'id sia impostare l'oggetto collegato. */")
        w(f"    protected void syncRelations({t.name} entity) {{")
        for r in sync:
            rn, fk = _cap(member(L, r.name)), _cap(m[r.foreign_key])
            tpk = _cap(member(L, tables[r.target].pk.name))
            w(f"        if (entity.get{rn}() != null) {{")
            w(f"            entity.set{fk}(entity.get{rn}().get{tpk}());")
            w(f"        }} else if (entity.get{fk}() != null) {{")
            w(f"            entity.set{rn}(em.getReference({r.target}.class, entity.get{fk}()));")
            w("        }")
        w("    }\n")
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"    /** {meth.summary} */")
        if k == "get_by_id":
            w(f"    public Optional<{t.name}> {name}({pkt} id) {{")
            w(f"        return Optional.ofNullable(em.find({t.name}.class, id));")
        elif k == "list_page":
            w(f"    public Paging.Page<{t.name}> {name}() {{")
            w(f"        return {name}(Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{t.name}> {name}(Paging.PageRequest page) {{")
            w(f"        return Paging.runPage(em, {t.name}.class, PAGING, null, Map.of(), page, null, {t.name}::kybesValue);")
        elif k == "count":
            w(f"    public long {name}() {{")
            w(f'        return em.createQuery("SELECT COUNT(e) FROM {t.name} e", Long.class).getSingleResult();')
        elif k == "exists":
            w(f"    public boolean {name}({pkt} id) {{")
            w(f'        return em.createQuery("SELECT COUNT(e) FROM {t.name} e WHERE e.{pkm} = :id", Long.class)')
            w('                .setParameter("id", id).getSingleResult() > 0;')
        elif k == "create":
            w(f"    public {t.name} {name}({t.name} entity) {{")
            if sync:
                w("        syncRelations(entity);")
            w("        entity.validate();")
            w("        em.persist(entity);")
            w("        return entity;")
        elif k == "update":
            w(f"    public {t.name} {name}({t.name} entity) {{")
            w(f'        if (entity.get{_cap(pkm)}() == null) throw new IllegalArgumentException("{t.name}: update senza chiave");')
            if sync:
                w("        syncRelations(entity);")
            w("        entity.validate();")
            if any(c.generated == "on_create" for c in t.columns):
                w(f"        {t.name} merged = em.merge(entity);")
                w("        em.flush();")
                w("        em.refresh(merged); // riallinea i campi non modificabili (es. data di creazione)")
                w("        return merged;")
            else:
                w("        return em.merge(entity);")
        elif k == "delete":
            w(f"    public boolean {name}({pkt} id) {{")
            w(f"        {t.name} entity = em.find({t.name}.class, id);")
            w("        if (entity == null) return false;")
            w("        em.remove(entity);")
            w("        return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    public Optional<{t.name}> {name}({J_TYPE[c.type]} value) {{")
            w(f'        return em.createQuery("SELECT e FROM {t.name} e WHERE e.{m[arg]} = :value", {t.name}.class)')
            w('                .setParameter("value", value).setMaxResults(1).getResultStream().findFirst();')
        elif k == "list_by":
            c = t.col(arg)
            w(f"    public Paging.Page<{t.name}> {name}({J_TYPE[c.type]} value) {{")
            w(f"        return {name}(value, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{t.name}> {name}({J_TYPE[c.type]} value, Paging.PageRequest page) {{")
            w(f'        Objects.requireNonNull(value, "{m[arg]}");')
            w(f'        return Paging.runPage(em, {t.name}.class, PAGING, "e.{m[arg]} = :value", Map.of("value", value), page, null, {t.name}::kybesValue);')
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"    public Optional<{r.target}> {name}({pkt} id) {{")
            w(f'        return em.createQuery("SELECT e.{member(L, r.name)} FROM {t.name} e WHERE e.{pkm} = :id", {r.target}.class)')
            w('                .setParameter("id", id).setMaxResults(1).getResultStream().findFirst();')
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id) {{")
            w(f"        return {name}(id, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id, Paging.PageRequest page) {{")
            w(f'        return Paging.runPage(em, {r.target}.class, {base_class(L, r.target)}.PAGING, "e.{member(L, r.foreign_key)} = :id", '
              f'Map.of("id", id), page, null, {r.target}::kybesValue);')
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params, conds, binds, guards = [], [], [], []
            for i, c in enumerate(q.where):
                col = t.col(c.column)
                prop = f"e.{m[c.column]}"
                jt = J_TYPE[col.type]
                if c.param:
                    pn = member(L, c.param)
                    params.append(f"Collection<{jt}> {pn}" if c.op == "in" else f"{jt} {pn}")
                    key, val = pn, (f"Paging.likePrefix({pn})" if c.op == "prefix" else pn)
                    if c.op == "in":
                        guards.append(pn)
                else:
                    key = f"k{i}"
                    val = _java_value(col, c.value) if c.has_value else None
                    if c.has_value and c.op == "prefix":
                        val = f"Paging.likePrefix({val})"
                conds.append(_java_cond(prop, c.op, key))
                if val is not None and c.op not in ("is_null", "not_null"):
                    binds.append(f'Map.entry("{key}", (Object) {val})')
            order = ", ".join(oi(cn, d) for cn, d in t.order(q.order_by or None))
            where = " AND ".join(conds)
            mp = f"Map.ofEntries({', '.join(binds)})" if binds else "Map.of()"
            ret = {"query_page": f"Paging.Page<{t.name}>", "query_list": f"List<{t.name}>", "query_one": f"Optional<{t.name}>"}[k]
            if k == "query_page":
                w(f"    public {ret} {name}({', '.join(params + ['Paging.PageRequest page'])}) {{")
            else:
                w(f"    public {ret} {name}({', '.join(params)}) {{")
            for prm in params:
                pn = prm.split(" ")[-1]
                w(f'        Objects.requireNonNull({pn}, "{pn}");')
            for g in guards:
                empty = {"query_page": "Paging.emptyPage(PAGING, page)", "query_list": "List.of()", "query_one": "Optional.empty()"}[k]
                w(f"        if ({g}.isEmpty()) return {empty};")
            w(f"        List<Paging.OrderItem> order = List.of({order});")
            if k == "query_page":
                w(f'        return Paging.runPage(em, {t.name}.class, PAGING, "{where}", {mp}, page, order, {t.name}::kybesValue);')
            elif k == "query_list":
                w(f'        return Paging.listRows(em, {t.name}.class, PAGING, "{where}", {mp}, order);')
            else:
                w(f'        return Paging.firstRow(em, {t.name}.class, PAGING, "{where}", {mp}, order);')
            if k == "query_page":
                w("    }\n")
                args = ", ".join(p.split(" ")[-1] for p in params)
                w(f"    public {ret} {name}({', '.join(params)}) {{")
                w(f"        return {name}({args + ', ' if args else ''}Paging.PageRequest.first());")
        w("    }\n")
    out[-1] = out[-1].rstrip("\n")
    w("}")
    return "\n".join(out) + "\n"


def _common_file(pkg: str) -> str:
    return (header(L, "kit").rstrip("\n") + f"\npackage {pkg}.{GEN_DIR};\n\n"
            "import java.util.Collections;\nimport java.util.Map;\nimport java.util.TreeMap;\n\n"
            "/** Dati non validi per la tabella: fields contiene campo -> regola violata (mai valori). */\n"
            "public class ModelValidationException extends RuntimeException {\n"
            "    private static final long serialVersionUID = 1L;\n\n"
            "    private final String table;\n    private final TreeMap<String, String> fields;\n\n"
            "    public ModelValidationException(String table, Map<String, String> fields) {\n"
            '        super(table + ": dati non validi (" + String.join(", ", new TreeMap<>(fields).keySet()) + ")");\n'
            "        this.table = table;\n        this.fields = new TreeMap<>(fields);\n    }\n\n"
            "    public String getTable() { return table; }\n\n"
            "    public Map<String, String> getFields() { return Collections.unmodifiableMap(fields); }\n}\n")


def custom_stub(t: Table, pkg: str) -> str:
    base = base_class(L, t.name)
    return (f"package {pkg};\n\n"
            "import jakarta.persistence.EntityManager;\n"
            f"import {pkg}.{GEN_DIR}.{base};\n\n"
            f"/**\n * {t.name}: punto d'ingresso per l'accesso ai dati della tabella {t.db_name}.\n"
            f" * Entità in {GEN_DIR}/{t.name}.java, CRUD e relazioni ereditati da {GEN_DIR}/{base}.java (vedi MODEL_INDEX.md).\n"
            " * Qui vanno SOLO i metodi custom di questa tabella, con nomi diversi da quelli generati.\n */\n"
            f"public class {repo_class(L, t.name)} extends {base} {{\n\n"
            f"    public {repo_class(L, t.name)}(EntityManager em) {{\n"
            "        super(em);\n"
            "    }\n"
            "}\n")


def emit(tables: Dict[str, Table], schema_rel: Dict[str, str], opts: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    pkg, dialect = opts["package"], opts.get("dialect", "postgres")
    gen = {f"{GEN_DIR}/ModelValidationException.java": _common_file(pkg),
           f"{GEN_DIR}/Paging.java": runtime_java.paging_file(pkg),
           f"{GEN_DIR}/UnitOfWork.java": runtime_java.uow_file(pkg, tables, dialect)}
    for n, t in tables.items():
        gen[f"{GEN_DIR}/{n}.java"] = _entity_file(t, tables, schema_rel[n], pkg, dialect)
        gen[f"{GEN_DIR}/{base_class(L, n)}.java"] = _repo_file(t, tables, schema_rel[n], pkg)
    custom = {custom_file(L, n): custom_stub(t, pkg) for n, t in tables.items()}
    return gen, custom


def _java_value(col, v) -> str:
    if isinstance(v, list):
        return "List.of(" + ", ".join(_java_value(col, x) for x in v) + ")"
    if col.type == "uuid":
        return f'UUID.fromString("{v}")'
    if col.type == "decimal":
        return f'new BigDecimal("{v}")'
    if col.type == "date":
        return f'LocalDate.parse("{v}")'
    if col.type == "datetime":
        return f'OffsetDateTime.parse("{v}")'
    if col.type == "bigint":
        return f"{int(v)}L"
    if col.type == "int":
        return str(int(v))
    if col.type == "bool":
        return "Boolean.TRUE" if v else "Boolean.FALSE"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _java_cond(prop: str, op: str, key: str) -> str:
    return {"eq": f"{prop} = :{key}", "ne": f"{prop} <> :{key}", "lt": f"{prop} < :{key}", "lte": f"{prop} <= :{key}",
            "gt": f"{prop} > :{key}", "gte": f"{prop} >= :{key}", "in": f"{prop} IN :{key}",
            "prefix": f"{prop} LIKE :{key} ESCAPE '\\\\'", "is_null": f"{prop} IS NULL", "not_null": f"{prop} IS NOT NULL"}[op]
