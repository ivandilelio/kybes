"""Emettitore Java: JPA (jakarta.persistence) con repository basato su EntityManager."""
from __future__ import annotations

from typing import Dict, List, Tuple

import runtime_archive
import runtime_mongo
import runtime_java
import runtime_tenant
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from sqlonly import has_sql
from schema import SORTABLE_TYPES, Table, index_specs, methods_of, snake, tenant_column

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
    orderable = ({t.pk.name} | set(t.pagination.sortable) | {cn for cn, _ in t.order(None)}
                 | {cn for q in t.queries for cn, _ in t.order(q.order_by or None)})
    sortable_cols = [c for c in t.columns if c.name in orderable and c.type in SORTABLE_TYPES and not c.nullable]
    if t.archive and t.archive.read_through:
        w("    /** Record archiviato (archive.read_through): entità non gestita dall'EntityManager, in sola lettura. */")
        w(f"    static {t.name} kybesFromArchive(com.fasterxml.jackson.databind.JsonNode doc) {{")
        w(f"        {t.name} e = new {t.name}();")
        for c in t.columns:
            w(f'        e.{m[c.name]} = Archive.{runtime_archive.JAVA_DECODE[c.type]}(doc.get("{c.name}"));')
        w("        return e;")
        w("    }\n")
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
        if c.tenant:
            continue  # impostata dal repository con il tenant dell'EntityManager
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
    rt = bool(t.archive and t.archive.read_through)
    out = []
    w = out.append
    w(header(L, schema_rel).rstrip("\n"))
    w(f"package {gpkg};\n")
    w("import jakarta.persistence.EntityManager;")
    w("import jakarta.persistence.EntityNotFoundException;")
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
    if t.tenancy != "none":
        w(f"        Tenancy.of(em); // tenancy: {t.tenancy}: senza un tenant legato all'EntityManager il repository non lavora")
    w("    }\n")
    tc = tenant_column(t)
    tm = m[tc.name] if tc else None
    T = t.name
    tq = f" AND e.{tm} = :kybesTenant" if tc else ""                     # condizione JPQL aggiunta
    tset = '.setParameter("kybesTenant", Tenancy.of(em))' if tc else ""

    def scoped(where):
        """(clausola where, parametri) per la paginazione, con il filtro sul tenant."""
        if not tc:
            return where, None
        cond = f"e.{tm} = :kybesTenant"
        return (cond if where is None else f"{cond} AND {where}"), 'Map.entry("kybesTenant", (Object) Tenancy.of(em))'

    def wh(where):
        return "null" if where is None else f'"{where}"'

    if tc:
        parents = [r for r in t.relations if r.kind == "many_to_one" and tables[r.target].tenancy == "column"]
        w("    /** Il record appartiene al tenant dell'EntityManager; i record collegati anche. */")
        w(f"    protected void checkTenant({T} entity) {{")
        w(f"        {J_TYPE[tc.type]} tenant = Tenancy.of(em);")
        w(f"        if (entity.get{_cap(tm)}() != null && !entity.get{_cap(tm)}().equals(tenant)) {{")
        w(f'            throw new ModelValidationException("{T}", Map.of("{tc.name}", "tenant diverso da quello della sessione"));')
        w("        }")
        w(f"        entity.set{_cap(tm)}(tenant);")
        if parents:
            w("        Map<String, String> errors = new java.util.TreeMap<>();")
            for r in parents:
                tg = tables[r.target]
                fk, tpk, ttm = _cap(m[r.foreign_key]), member(L, tg.pk.name), member(L, tenant_column(tg).name)
                w(f'        if (entity.get{fk}() != null && em.createQuery("SELECT COUNT(p) FROM {r.target} p WHERE p.{tpk} = :id AND p.{ttm} = :tenant", Long.class)')
                w(f'                .setParameter("id", entity.get{fk}()).setParameter("tenant", tenant).getSingleResult() == 0) {{')
                w(f'            errors.put("{r.foreign_key}", "non trovato");')
                w("        }")
            w(f'        if (!errors.isEmpty()) throw new ModelValidationException("{T}", errors);')
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
        if k == "get_by_id" and rt:
            ten = "Tenancy.of(em)" if t.tenancy != "none" else "null"
            w(f"    public Optional<{t.name}> {name}({pkt} id) {{")
            w(f"        Optional<{t.name}> found = kybesHot(id);")
            w(f"        if (found.isPresent()) return found;")
            w(f'        com.fasterxml.jackson.databind.JsonNode doc = Archive.read(em, "{t.db_name}", {ten}, id);')
            w(f"        return doc == null ? Optional.empty() : Optional.of({t.name}.kybesFromArchive(doc));")
            w("    }\n")
            w("    /** Lettura dalla tabella hot: aggiornamento e cancellazione non toccano l'archivio. */")
            w(f"    private Optional<{t.name}> kybesHot({pkt} id) {{")
            if tc:
                w(f'        return em.createQuery("SELECT e FROM {T} e WHERE e.{pkm} = :id{tq}", {T}.class)')
                w(f'                .setParameter("id", id){tset}.setMaxResults(1).getResultStream().findFirst();')
            else:
                w(f"        return Optional.ofNullable(em.find({t.name}.class, id));")
        elif k == "get_by_id":
            w(f"    public Optional<{t.name}> {name}({pkt} id) {{")
            if tc:
                w(f'        return em.createQuery("SELECT e FROM {T} e WHERE e.{pkm} = :id{tq}", {T}.class)')
                w(f'                .setParameter("id", id){tset}.setMaxResults(1).getResultStream().findFirst();')
            else:
                w(f"        return Optional.ofNullable(em.find({t.name}.class, id));")
        elif k == "list_page":
            w(f"    public Paging.Page<{t.name}> {name}() {{")
            w(f"        return {name}(Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{t.name}> {name}(Paging.PageRequest page) {{")
            wq, ent = scoped(None)
            mp = f"Map.ofEntries({ent})" if ent else "Map.of()"
            w(f"        return Paging.runPage(em, {t.name}.class, PAGING, {wh(wq)}, {mp}, page, null, {t.name}::kybesValue);")
        elif k == "count":
            w(f"    public long {name}() {{")
            if tc:
                w(f'        return em.createQuery("SELECT COUNT(e) FROM {T} e WHERE e.{tm} = :kybesTenant", Long.class){tset}.getSingleResult();')
            else:
                w(f'        return em.createQuery("SELECT COUNT(e) FROM {t.name} e", Long.class).getSingleResult();')
        elif k == "exists":
            w(f"    public boolean {name}({pkt} id) {{")
            w(f'        return em.createQuery("SELECT COUNT(e) FROM {t.name} e WHERE e.{pkm} = :id{tq}", Long.class)')
            w(f'                .setParameter("id", id){tset}.getSingleResult() > 0;')
        elif k == "create":
            w(f"    public {t.name} {name}({t.name} entity) {{")
            if sync:
                w("        syncRelations(entity);")
            if tc:
                w("        checkTenant(entity);")
            w("        entity.validate();")
            w("        em.persist(entity);")
            w("        return entity;")
        elif k == "update":
            w(f"    public {t.name} {name}({t.name} entity) {{")
            w(f'        if (entity.get{_cap(pkm)}() == null) throw new IllegalArgumentException("{t.name}: update senza chiave");')
            if tc:
                w(f'        if (!{method_name(L, "exists")}(entity.get{_cap(pkm)}())) throw new EntityNotFoundException("{t.name}: record inesistente");')
            else:
                w(f'        if (em.find({t.name}.class, entity.get{_cap(pkm)}()) == null) throw new EntityNotFoundException("{t.name}: record inesistente");')
            if sync:
                w("        syncRelations(entity);")
            if tc:
                w("        checkTenant(entity);")
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
            if tc:
                w(f"        {t.name} entity = {'kybesHot' if rt else method_name(L, 'get_by_id')}(id).orElse(null);")
            else:
                w(f"        {t.name} entity = em.find({t.name}.class, id);")
            w("        if (entity == null) return false;")
            w("        em.remove(entity);")
            w("        return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    public Optional<{t.name}> {name}({J_TYPE[c.type]} value) {{")
            w(f'        return em.createQuery("SELECT e FROM {t.name} e WHERE e.{m[arg]} = :value{tq}", {t.name}.class)')
            w(f'                .setParameter("value", value){tset}.setMaxResults(1).getResultStream().findFirst();')
        elif k == "list_by":
            c = t.col(arg)
            w(f"    public Paging.Page<{t.name}> {name}({J_TYPE[c.type]} value) {{")
            w(f"        return {name}(value, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{t.name}> {name}({J_TYPE[c.type]} value, Paging.PageRequest page) {{")
            w(f'        Objects.requireNonNull(value, "{m[arg]}");')
            wq, ent = scoped(f"e.{m[arg]} = :value")
            mp = f'Map.ofEntries(Map.entry("value", (Object) value), {ent})' if ent else 'Map.of("value", value)'
            w(f'        return Paging.runPage(em, {t.name}.class, PAGING, {wh(wq)}, {mp}, page, null, {t.name}::kybesValue);')
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"    public Optional<{r.target}> {name}({pkt} id) {{")
            w(f'        return em.createQuery("SELECT e.{member(L, r.name)} FROM {t.name} e WHERE e.{pkm} = :id{tq}", {r.target}.class)')
            w(f'                .setParameter("id", id){tset}.setMaxResults(1).getResultStream().findFirst();')
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id) {{")
            w(f"        return {name}(id, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id, Paging.PageRequest page) {{")
            ctc = tenant_column(tables[r.target])
            if ctc:
                w(f'        return Paging.runPage(em, {r.target}.class, {base_class(L, r.target)}.PAGING, '
                  f'"e.{member(L, r.foreign_key)} = :id AND e.{member(L, ctc.name)} = :kybesTenant", '
                  f'Map.ofEntries(Map.entry("id", (Object) id), Map.entry("kybesTenant", (Object) Tenancy.of(em))), page, null, {r.target}::kybesValue);')
            else:
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
            where, ent = scoped(" AND ".join(conds))
            if ent:
                binds.append(ent)
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
    session = f"{pkg}.{GEN_DIR}.MongoSession" if t.mongo else "jakarta.persistence.EntityManager"
    return (f"package {pkg};\n\n"
            f"import {session};\n"
            f"import {pkg}.{GEN_DIR}.{base};\n\n"
            f"/**\n * {t.name}: punto d'ingresso per l'accesso ai dati della tabella {t.db_name}.\n"
            f" * Entità in {GEN_DIR}/{t.name}.java, CRUD e relazioni ereditati da {GEN_DIR}/{base}.java (vedi MODEL_INDEX.md).\n"
            " * Qui vanno SOLO i metodi custom di questa tabella, con nomi diversi da quelli generati.\n */\n"
            f"public class {repo_class(L, t.name)} extends {base} {{\n\n"
            f"    public {repo_class(L, t.name)}({'MongoSession' if t.mongo else 'EntityManager'} em) {{\n"
            "        super(em);\n"
            "    }\n"
            "}\n")


def emit(tables: Dict[str, Table], schema_rel: Dict[str, str], opts: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    pkg, dialect = opts["package"], opts.get("dialect", "postgres")
    sql = has_sql(tables)
    gen = {f"{GEN_DIR}/ModelValidationException.java": _common_file(pkg),
           f"{GEN_DIR}/Paging.java": runtime_java.paging_file(pkg, sql),
           f"{GEN_DIR}/Tenancy.java": runtime_tenant.java_file(pkg, opts.get("tenant_id_type", "uuid"), sql)}
    if sql:  # con sole collection MongoDB: niente Unit of Work SQL né archivio (che lavora sulle tabelle SQL)
        gen[f"{GEN_DIR}/UnitOfWork.java"] = runtime_java.uow_file(pkg, tables, dialect)
        gen[f"{GEN_DIR}/Archive.java"] = runtime_archive.java_file(pkg)
    for n, t in tables.items():
        if t.mongo:
            gen[f"{GEN_DIR}/{n}.java"] = _mongo_entity_file(t, tables, schema_rel[n], pkg)
            gen[f"{GEN_DIR}/{base_class(L, n)}.java"] = _mongo_repo_file(t, tables, schema_rel[n], pkg)
        else:
            gen[f"{GEN_DIR}/{n}.java"] = _entity_file(t, tables, schema_rel[n], pkg, dialect)
            gen[f"{GEN_DIR}/{base_class(L, n)}.java"] = _repo_file(t, tables, schema_rel[n], pkg)
    if any(t.mongo for t in tables.values()):
        gen[f"{GEN_DIR}/MongoSession.java"] = runtime_mongo.java_file(pkg, opts.get("tenant_id_type", "uuid"))
        gen[f"{GEN_DIR}/MongoIndexes.java"] = _mongo_indexes_file(tables, pkg)
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


# ------------------------------------------------------------------------------------------- MongoDB

def _mongo_entity_file(t: Table, tables: Dict[str, Table], schema_rel: str, pkg: str) -> str:
    import mongo_plan
    m = {c.name: member(L, c.name) for c in t.columns}
    T = t.name
    out: List[str] = []
    w = out.append
    w(header(L, schema_rel).rstrip("\n"))
    w(f"package {pkg}.{GEN_DIR};\n")
    w("import java.math.BigDecimal;")
    w("import java.time.LocalDate;")
    w("import java.time.OffsetDateTime;")
    w("import java.util.UUID;")
    w("import org.bson.Document;\n")
    w(f"/** {T}: documento della collection MongoDB {t.db_name}.{(' ' + t.description) if t.description else ''} */")
    w(f"public class {T} {{\n")
    for c in t.columns:
        init = f" = {_java_value(c, c.default)}" if c.default is not None else ""
        w(f"    private {J_TYPE[c.type]} {m[c.name]}{init};")
    w("")
    for c in t.columns:
        jt, mm = J_TYPE[c.type], m[c.name]
        w(f"    public {jt} get{_cap(mm)}() {{ return {mm}; }}")
        if not (c.primary_key and c.auto) and not c.generated:
            w(f"    public void set{_cap(mm)}({jt} value) {{ this.{mm} = value; }}")
    w("")
    w("    /** Chiave e date generate: le imposta il repository. */")
    w("    void kybesGenerated(String field, Object value) {")
    w("        switch (field) {")
    for c in t.columns:
        if (c.primary_key and c.auto) or c.generated:
            w(f'            case "{m[c.name]}" -> this.{m[c.name]} = ({J_TYPE[c.type]}) value;')
    w('            default -> throw new IllegalArgumentException(field);')
    w("        }")
    w("    }\n")
    orderable = ({t.pk.name} | set(t.pagination.sortable) | {cn for cn, _ in t.order(None)}
                 | {cn for q in t.queries for cn, _ in t.order(q.order_by or None)})
    sortable_cols = [c for c in t.columns if c.name in orderable and c.type in SORTABLE_TYPES and not c.nullable]
    w("    /** Valore di una colonna ordinabile, usato dal cursore di paginazione. */")
    w("    public Object kybesValue(String field) {")
    w("        return switch (field) {")
    for c in sortable_cols:
        w(f'            case "{m[c.name]}" -> {m[c.name]};')
    w('            default -> throw new IllegalArgumentException("colonna non ordinabile: " + field);')
    w("        };")
    w("    }\n")
    w("    /** Validazione di modello prima della persistenza. */")
    w("    public void validate() {")
    w("        java.util.Map<String, String> errors = new java.util.TreeMap<>();")
    for c in t.columns:
        mm = m[c.name]
        if c.tenant:
            continue
        if c.required and not (c.primary_key and c.auto) and not c.generated:
            w(f'        if ({mm} == null) errors.put("{c.name}", "obbligatorio");')
        if c.type == "string":
            w(f'        if ({mm} != null && {mm}.length() > {c.length}) errors.put("{c.name}", "lunghezza massima {c.length}");')
    w(f'        if (!errors.isEmpty()) throw new ModelValidationException("{T}", errors);')
    w("    }\n")
    w("    /** Documento MongoDB del record: le colonne vuote non compaiono. */")
    w("    public Document toDocument() {")
    w("        Document d = new Document();")
    for c in t.columns:
        f = mongo_plan.field_name(t, c)
        w(f'        if ({m[c.name]} != null) d.append("{f}", MongoSession.toBson({m[c.name]}, "{c.type}"));' if c.nullable or (c.primary_key and c.auto) or c.generated
          else f'        d.append("{f}", MongoSession.toBson({m[c.name]}, "{c.type}"));')
    w("        return d;")
    w("    }\n")
    w(f"    public static {T} fromDocument(Document d) {{")
    w(f"        {T} e = new {T}();")
    for c in t.columns:
        w(f'        e.{m[c.name]} = ({J_TYPE[c.type]}) MongoSession.fromBson(d.get("{mongo_plan.field_name(t, c)}"), "{c.type}");')
    w("        return e;")
    w("    }")
    w("}")
    return "\n".join(out) + "\n"


def _mongo_cond_java(field: str, op: str, val: str) -> str:
    return {"eq": f'new Document("{field}", {val})', "ne": f'new Document("{field}", new Document("$nin", java.util.Arrays.asList({val}, null)))',
            "lt": f'new Document("{field}", new Document("$lt", {val}))', "lte": f'new Document("{field}", new Document("$lte", {val}))',
            "gt": f'new Document("{field}", new Document("$gt", {val}))', "gte": f'new Document("{field}", new Document("$gte", {val}))',
            "in": f'new Document("{field}", new Document("$in", {val}))', "prefix": f'new Document("{field}", MongoSession.prefix({val}))',
            "is_null": f'new Document("{field}", null)', "not_null": f'new Document("{field}", new Document("$ne", null))'}[op]


def _mongo_repo_file(t: Table, tables: Dict[str, Table], schema_rel: str, pkg: str) -> str:
    import mongo_plan
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], J_TYPE[pk.type]
    T = t.name
    base = base_class(L, T)
    tc = tenant_column(t)
    fields = {m[c.name]: mongo_plan.field_name(t, c) for c in t.columns}
    out: List[str] = []
    w = out.append
    w(header(L, schema_rel).rstrip("\n"))
    w(f"package {pkg}.{GEN_DIR};\n")
    w("import com.mongodb.client.MongoDatabase;")
    w("import com.mongodb.client.model.IndexOptions;")
    w("import jakarta.persistence.EntityNotFoundException;")
    w("import java.math.BigDecimal;")
    w("import java.time.LocalDate;")
    w("import java.time.OffsetDateTime;")
    w("import java.util.ArrayList;")
    w("import java.util.Collection;")
    w("import java.util.List;")
    w("import java.util.Map;")
    w("import java.util.Objects;")
    w("import java.util.Optional;")
    w("import java.util.UUID;")
    w("import org.bson.Document;\n")
    w(f"/** CRUD, relazioni e query di {T} su MongoDB. Le transazioni le apre il chiamante (MongoSession.transaction). Metodi custom: model/{custom_file(L, T)}. */")
    w(f"public abstract class {base} {{\n")

    def oi(cn, d):
        return f'new Paging.OrderItem("{m[cn]}", "{member("typescript", cn)}", Paging.SortType.{t.col(cn).type.upper()}, {str(d).lower()})'
    w(f'    public static final Paging.Spec PAGING = new Paging.Spec("{T}", "{T}",')
    w(f"            {oi(pk.name, False)},")
    entries = ", ".join(f'Map.entry("{member("typescript", cn)}", {oi(cn, False)})' for cn in t.pagination.sortable)
    w(f"            Map.ofEntries({entries}),")
    w(f"            List.of({', '.join(oi(cn, d) for cn, d in t.order())}),")
    w(f"            {t.pagination.default_limit}, {t.pagination.max_limit});")
    w(f'    public static final String COLLECTION = "{t.db_name}";')
    w("    public static final Map<String, String> FIELDS = Map.ofEntries(" + ", ".join(f'Map.entry("{a}", "{f}")' for a, f in fields.items()) + ");\n")
    w("    protected final MongoSession em;\n")
    w(f"    protected {base}(MongoSession em) {{")
    w("        this.em = em;")
    if t.tenancy != "none":
        w(f"        em.requireTenant(); // tenancy: {t.tenancy}: senza un tenant legato alla sessione il repository non lavora")
    w("    }\n")
    w("    /** Indici della collection (stessi nomi del DDL SQL); idempotente: si chiama all'avvio o nel deploy. */")
    w("    public static void ensureIndexes(MongoDatabase db) {")
    ixs = mongo_plan.indexes(t)
    for ix in ixs:
        keys = "new Document()" + "".join(f'.append("{f}", 1)' for f in ix.fields)
        opts = f'new IndexOptions().name("{ix.name}")'
        if ix.unique:
            opts += ".unique(true)"
        if ix.partial:
            opts += ".partialFilterExpression(new Document()" + "".join(f'.append("{f}", new Document("$exists", true))' for f in ix.partial) + ")"
        if ix.ttl is not None:
            opts += f".expireAfter({ix.ttl}L, java.util.concurrent.TimeUnit.SECONDS)"
        w(f"        db.getCollection(COLLECTION).createIndex({keys}, {opts});")
    if not ixs:
        w("        Objects.requireNonNull(db); // nessun indice oltre a _id")
    w("    }\n")
    w("    protected Document scope(Document filter) {")
    if tc:
        w(f'        return MongoSession.and(filter, new Document("{tc.db_name}", MongoSession.toBson(em.requireTenant(), "{tc.type}")));')
    else:
        w("        return filter;")
    w("    }\n")
    w("    /** Lettura per chiave (anche dai repository collegati). */")
    w(f"    public Optional<{T}> find({pkt} id) {{")
    w(f'        Document d = em.findOne(COLLECTION, scope(new Document("_id", MongoSession.toBson(id, "{pk.type}"))));')
    w(f"        return d == null ? Optional.empty() : Optional.of({T}.fromDocument(d));")
    w("    }\n")
    parents = [r for r in t.relations if r.kind == "many_to_one"]
    w("    /** Tenant della sessione e record collegati esistenti (MongoDB non ha chiavi esterne). */")
    w(f"    protected void check({T} entity) {{")
    if tc:
        tm = m[tc.name]
        w(f"        {J_TYPE[tc.type]} tenant = em.requireTenant();")
        w(f"        if (entity.get{_cap(tm)}() != null && !entity.get{_cap(tm)}().equals(tenant)) {{")
        w(f'            throw new ModelValidationException("{T}", Map.of("{tc.name}", "tenant diverso da quello della sessione"));')
        w("        }")
        w(f"        entity.set{_cap(tm)}(tenant);")
    w("        entity.validate();")
    if parents:
        w("        Map<String, String> errors = new java.util.TreeMap<>();")
        for r in parents:
            fk = _cap(m[r.foreign_key])
            w(f"        if (entity.get{fk}() != null && new {base_class(L, r.target)}(em) {{ }}.find(entity.get{fk}()).isEmpty()) {{")
            w(f'            errors.put("{r.foreign_key}", "non trovato");')
            w("        }")
        w(f'        if (!errors.isEmpty()) throw new ModelValidationException("{T}", errors);')
    w("    }\n")
    paging_call = f"em.runPage(COLLECTION, PAGING, FIELDS, {{flt}}, page, {{order}}, {T}::fromDocument, {T}::kybesValue)"
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"    /** {meth.summary} */")
        if k == "get_by_id":
            w(f"    public Optional<{T}> {name}({pkt} id) {{")
            w("        return find(id);")
        elif k == "list_page":
            w(f"    public Paging.Page<{T}> {name}() {{")
            w(f"        return {name}(Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{T}> {name}(Paging.PageRequest page) {{")
            w("        return " + paging_call.format(flt="scope(new Document())", order="null") + ";")
        elif k == "count":
            w(f"    public long {name}() {{")
            w("        return em.count(COLLECTION, scope(new Document()), 0);")
        elif k == "exists":
            w(f"    public boolean {name}({pkt} id) {{")
            w(f'        return em.count(COLLECTION, scope(new Document("_id", MongoSession.toBson(id, "{pk.type}"))), 1) > 0;')
        elif k == "create":
            w(f"    public {T} {name}({T} entity) {{")
            w("        check(entity);")
            if pk.auto:
                gen = "UUID.randomUUID()" if pk.type == "uuid" else ("em.nextId(COLLECTION)" if pk.type == "bigint" else "(int) em.nextId(COLLECTION)")
                w(f'        entity.kybesGenerated("{pkm}", {gen});')
            for c in t.columns:
                if c.generated:
                    w(f'        entity.kybesGenerated("{m[c.name]}", MongoSession.nowMs());')
            w("        em.insert(COLLECTION, entity.toDocument());")
            w("        return entity;")
        elif k == "update":
            w(f"    public {T} {name}({T} entity) {{")
            w(f'        if (entity.get{_cap(pkm)}() == null) throw new IllegalArgumentException("{T}: update senza chiave");')
            w(f"        {T} stored = find(entity.get{_cap(pkm)}()).orElseThrow(() -> new EntityNotFoundException(\"{T}: record inesistente\"));")
            w("        check(entity);")
            for c in t.columns:
                if c.generated == "on_create":
                    w(f'        entity.kybesGenerated("{m[c.name]}", stored.get{_cap(m[c.name])}());')
                elif c.generated == "on_update":
                    w(f'        entity.kybesGenerated("{m[c.name]}", MongoSession.nowMs());')
            if not any(c.generated == "on_create" for c in t.columns):
                w("        Objects.requireNonNull(stored);")
            w(f'        em.replace(COLLECTION, scope(new Document("_id", MongoSession.toBson(entity.get{_cap(pkm)}(), "{pk.type}"))), entity.toDocument());')
            w("        return entity;")
        elif k == "delete":
            w(f"    public boolean {name}({pkt} id) {{")
            w("        if (find(id).isEmpty()) return false;")
            for c, r in mongo_plan.children(t, tables):
                ctc = tenant_column(c)
                fk_f = mongo_plan.field_name(c, c.col(r.foreign_key))
                flt = f'new Document("{fk_f}", MongoSession.toBson(id, "{pk.type}"))' + (f'.append("{ctc.db_name}", MongoSession.toBson(em.requireTenant(), "{ctc.type}"))' if ctc else "")
                if r.on_delete == "restrict":
                    w(f'        if (em.count("{c.db_name}", {flt}, 1) > 0) {{')
                    w(f'            throw new ModelValidationException("{T}", Map.of("{mongo_plan.child_label(t, c, r)}", "record collegati"));')
                    w("        }")
                else:
                    w(f'        em.updateMany("{c.db_name}", {flt}, new Document("$unset", new Document("{fk_f}", "")));')
            w(f'        em.delete(COLLECTION, scope(new Document("_id", MongoSession.toBson(id, "{pk.type}"))));')
            w("        return true;")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    public Optional<{T}> {name}({J_TYPE[c.type]} value) {{")
            w(f'        Document d = em.findOne(COLLECTION, scope(new Document("{fields[m[arg]]}", MongoSession.toBson(value, "{c.type}"))));')
            w(f"        return d == null ? Optional.empty() : Optional.of({T}.fromDocument(d));")
        elif k == "list_by":
            c = t.col(arg)
            w(f"    public Paging.Page<{T}> {name}({J_TYPE[c.type]} value) {{")
            w(f"        return {name}(value, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{T}> {name}({J_TYPE[c.type]} value, Paging.PageRequest page) {{")
            w(f'        Objects.requireNonNull(value, "{m[arg]}");')
            w("        return " + paging_call.format(flt=f'scope(new Document("{fields[m[arg]]}", MongoSession.toBson(value, "{c.type}")))', order="null") + ";")
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            fk = _cap(m[r.foreign_key])
            w(f"    public Optional<{r.target}> {name}({pkt} id) {{")
            w(f"        return find(id).map({T}::get{fk}).flatMap(fk -> new {base_class(L, r.target)}(em) {{ }}.find(fk));")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id) {{")
            w(f"        return {name}(id, Paging.PageRequest.first());")
            w("    }\n")
            w(f"    public Paging.Page<{r.target}> {name}({pkt} id, Paging.PageRequest page) {{")
            w(f"        return new {base_class(L, r.target)}(em) {{ }}.{method_name(L, 'list_by:' + r.foreign_key)}(id, page);")
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params, conds, guards = [], [], []
            for c in q.where:
                col = t.col(c.column)
                jt = J_TYPE[col.type]
                if c.param:
                    pn = member(L, c.param)
                    params.append(f"Collection<{jt}> {pn}" if c.op == "in" else f"{jt} {pn}")
                    raw = pn
                    if c.op == "in":
                        guards.append(pn)
                else:
                    raw = _java_value(col, c.value) if c.has_value else "null"
                if c.op == "in":
                    val = f'{raw}.stream().map(x -> MongoSession.toBson(x, "{col.type}")).toList()'
                elif c.op == "prefix":
                    val = raw
                else:
                    val = f'MongoSession.toBson({raw}, "{col.type}")'
                conds.append(_mongo_cond_java(mongo_plan.field_name(t, col), c.op, val))
            order = ", ".join(oi(cn, d) for cn, d in t.order(q.order_by or None))
            ret = {"query_page": f"Paging.Page<{T}>", "query_list": f"List<{T}>", "query_one": f"Optional<{T}>"}[k]
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
            w(f"        Document filter = scope(MongoSession.and({', '.join(conds)}));")
            if k == "query_page":
                w("        return " + paging_call.format(flt="filter", order="order") + ";")
            else:
                lim = "PAGING.maxLimit()" if k == "query_list" else "1"
                w(f"        List<{T}> rows = new ArrayList<>();")
                w(f"        for (Document d : em.find(COLLECTION, filter, MongoSession.sort(FIELDS, order), {lim})) rows.add({T}.fromDocument(d));")
                w("        return rows;" if k == "query_list" else "        return rows.stream().findFirst();")
            if k == "query_page":
                w("    }\n")
                args = ", ".join(p.split(" ")[-1] for p in params)
                w(f"    public {ret} {name}({', '.join(params)}) {{")
                w(f"        return {name}({args + ', ' if args else ''}Paging.PageRequest.first());")
        w("    }\n")
    out[-1] = out[-1].rstrip("\n")
    w("}")
    return "\n".join(out) + "\n"


def _mongo_indexes_file(tables: Dict[str, Table], pkg: str) -> str:
    mongo = [n for n, t in tables.items() if t.mongo]
    return (header(L, "kit").rstrip("\n") + f"\npackage {pkg}.{GEN_DIR};\n\nimport com.mongodb.client.MongoDatabase;\n\n"
            "/** Indici di tutte le collection MongoDB del modello. */\npublic final class MongoIndexes {\n\n"
            "    private MongoIndexes() {\n    }\n\n"
            "    /** Crea gli indici (idempotente): all'avvio dell'applicazione o nel deploy. */\n"
            "    public static void ensure(MongoDatabase db) {\n" + "".join(f"        {base_class(L, n)}.ensureIndexes(db);\n" for n in mongo) +
            "    }\n}\n")
