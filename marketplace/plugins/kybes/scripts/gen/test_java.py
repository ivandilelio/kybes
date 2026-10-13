"""Rende il catalogo dei casi di test in JUnit 5 (Java, Hibernate) per i progetti che usano kybes.

I test girano sul PostgreSQL indicato da KYBES_TEST_DATABASE_URL: lo schema viene creato una volta da Hibernate
e le tabelle vengono svuotate prima di ogni test.
"""
from __future__ import annotations

import json
from typing import Dict, List

from emit_java import J_TYPE, _java_value
from naming import header, member, method_name, repo_class
from schema import Table
from verification import METHODS, Catalog, TestCase, table_asil

L = "java"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _get(cn: str) -> str:
    return "get" + _cap(member(L, cn))


def _set(cn: str) -> str:
    return "set" + _cap(member(L, cn))


def _jstr(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _sample(t: Table, cn: str, tables: Dict[str, Table]) -> str:
    c = t.col(cn)
    rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == cn), None)
    if rel:
        return f"build{rel.target}(em).{_get(tables[rel.target].pk.name)}()"
    if c.type == "string":
        return f"textValue(nextN(), {c.length})"
    return {"uuid": "UUID.randomUUID()", "text": '"testo " + nextN()', "int": "nextN()", "bigint": "(long) nextN()",
            "decimal": 'new BigDecimal(nextN() + ".50")', "bool": "Boolean.TRUE", "date": "LocalDate.of(2026, 1, 1).plusDays(nextN())",
            "datetime": "OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC).plusHours(nextN())",
            "json": '"{\\"n\\": " + nextN() + "}"'}[c.type]


def _missing_pk(t: Table) -> str:
    return {"uuid": 'UUID.fromString("00000000-0000-4000-8000-000000000999")', "int": "987654321", "bigint": "987654321L",
            "string": '"kybes-non-esiste"'}[t.pk.type]


def _new_value(t: Table, cn: str) -> str:
    c = t.col(cn)
    if c.type == "string":
        return f'"u" + textValue(nextN(), {max(c.length - 1, 1)})'
    return {"text": '"testo aggiornato"', "int": "nextN() + 500", "bigint": "nextN() + 500L", "decimal": 'new BigDecimal("99.25")'}[c.type]


def _imports(pkg: str, tables: Dict[str, Table], extra: List[str] = ()) -> List[str]:
    out = ["import static org.junit.jupiter.api.Assertions.*;", f"import static {pkg}.generated.KybesBuilders.*;",
           f"import static {pkg}.generated.KybesDb.*;", ""]
    for n in tables:
        out.append(f"import {pkg}.{repo_class(L, n)};")
    out += ["import jakarta.persistence.EntityManager;", "import jakarta.persistence.EntityNotFoundException;",
            "import jakarta.persistence.PersistenceException;", "import java.math.BigDecimal;", "import java.time.LocalDate;",
            "import java.time.OffsetDateTime;", "import java.time.ZoneOffset;", "import java.util.*;",
            "import org.junit.jupiter.api.AfterEach;", "import org.junit.jupiter.api.BeforeEach;",
            "import org.junit.jupiter.api.DisplayName;", "import org.junit.jupiter.api.Test;", *extra]
    return out


# ------------------------------------------------------------------------------------------- infrastruttura

def db_file(pkg: str, tables: Dict[str, Table]) -> str:
    classes = "\n".join(f"        cfg.addAnnotatedClass({n}.class);" for n in tables)
    names = ", ".join('\\"' + t.db_name + '\\"' for t in tables.values())
    return header(L, "kit") + f'''package {pkg}.generated;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import java.net.URI;
import org.hibernate.cfg.Configuration;
import org.junit.jupiter.api.function.Executable;

/**
 * Database dei test generati e custom: il PostgreSQL indicato da KYBES_TEST_DATABASE_URL
 * (postgresql://utente:password@host:porta/database oppure un URL jdbc:postgresql://...).
 * Lo schema lo crea Hibernate dalle entità; ogni test parte da tabelle vuote e lavora in una transazione annullata alla fine.
 */
public final class KybesDb {{

    private static EntityManagerFactory emf;

    private KybesDb() {{
    }}

    public static synchronized EntityManagerFactory emf() {{
        if (emf == null) {{
            String url = System.getenv("KYBES_TEST_DATABASE_URL");
            if (url == null || url.isBlank()) {{
                throw new IllegalStateException("Imposta KYBES_TEST_DATABASE_URL (PostgreSQL di test) per eseguire i test generati");
            }}
            String[] jdbc = jdbc(url);
            Configuration cfg = new Configuration();
            cfg.setProperty("hibernate.connection.url", jdbc[0]);
            if (jdbc[1] != null) cfg.setProperty("hibernate.connection.username", jdbc[1]);
            if (jdbc[2] != null) cfg.setProperty("hibernate.connection.password", jdbc[2]);
            cfg.setProperty("hibernate.connection.pool_size", "4");
            cfg.setProperty("hibernate.hbm2ddl.auto", "create-drop");
            cfg.setProperty("hibernate.show_sql", "false");
{classes}
            emf = cfg.buildSessionFactory();
        }}
        return emf;
    }}

    /** postgresql://u:p@h:5432/db → jdbc:postgresql://h:5432/db, utente, password. */
    static String[] jdbc(String url) {{
        if (url.startsWith("jdbc:")) return new String[] {{url, null, null}};
        URI u = URI.create(url.replaceFirst("^[a-z+]+://", "http://"));
        String user = null;
        String password = null;
        if (u.getUserInfo() != null) {{
            String[] parts = u.getUserInfo().split(":", 2);
            user = parts[0];
            password = parts.length > 1 ? parts[1] : null;
        }}
        String port = u.getPort() > 0 ? ":" + u.getPort() : "";
        return new String[] {{"jdbc:postgresql://" + u.getHost() + port + u.getPath(), user, password}};
    }}

    /** Svuota tutte le tabelle del modello. */
    public static void reset() {{
        EntityManager em = emf().createEntityManager();
        try {{
            em.getTransaction().begin();
            em.createNativeQuery("TRUNCATE TABLE {names} RESTART IDENTITY CASCADE").executeUpdate();
            em.getTransaction().commit();
        }} finally {{
            em.close();
        }}
    }}

    /** Tabelle vuote e una transazione aperta: alla fine del test close() la annulla. */
    public static EntityManager open() {{
        reset();
        EntityManager em = emf().createEntityManager();
        em.getTransaction().begin();
        return em;
    }}

    public static void close(EntityManager em) {{
        try {{
            if (em.getTransaction().isActive()) em.getTransaction().rollback();
        }} catch (RuntimeException ignored) {{
            // la transazione può essere già compromessa dall'errore che il test si aspettava
        }} finally {{
            em.close();
        }}
    }}

    /** L'operazione è rifiutata con un errore di validazione sul campo indicato. */
    public static ModelValidationException assertInvalid(String field, Executable operation) {{
        ModelValidationException e = assertThrows(ModelValidationException.class, operation);
        assertTrue(e.getFields().containsKey(field), () -> "errore atteso su " + field + ", trovati " + e.getFields().keySet());
        assertFalse(e.getTable().isEmpty());
        assertTrue(e.getMessage().contains(field));
        return e;
    }}

    public static void assertRule(String field, String rule, Executable operation) {{
        assertEquals(rule, assertInvalid(field, operation).getFields().get(field));
    }}
}}
'''


def builders_file(pkg: str, tables: Dict[str, Table]) -> str:
    o = [header(L, "kit") + f"package {pkg}.generated;", ""]
    o += [f"import {pkg}.{repo_class(L, n)};" for n in tables]
    o += ["import jakarta.persistence.EntityManager;", "import java.math.BigDecimal;", "import java.time.LocalDate;",
          "import java.time.OffsetDateTime;", "import java.time.ZoneOffset;", "import java.util.UUID;",
          "import java.util.concurrent.atomic.AtomicInteger;", "import java.util.function.Consumer;", "",
          "/** Costruttori di dati validi per i test generati e custom: un record per chiamata, valori deterministici. */",
          "public final class KybesBuilders {", "", "    private static final AtomicInteger SEQ = new AtomicInteger();", "",
          "    private KybesBuilders() {", "    }", "",
          "    public static int nextN() {", "        return SEQ.incrementAndGet();", "    }", "",
          "    public static String textValue(int n, int length) {", '        String s = "v" + n;',
          "        return s.length() > length ? s.substring(0, length) : s;", "    }", "",
          "    /** Confronto tra valori di una colonna: -1, 0, 1 (decimali per valore, date-ora per istante, UUID come in PostgreSQL). */",
          "    @SuppressWarnings(\"unchecked\")",
          "    public static int cmp(Object a, Object b) {",
          "        if (a == null || b == null) return a == b ? 0 : (a == null ? -1 : 1);",
          "        if (a instanceof BigDecimal x && b instanceof BigDecimal y) return Integer.signum(x.compareTo(y));",
          "        if (a instanceof OffsetDateTime x && b instanceof OffsetDateTime y) return Integer.signum(x.toInstant().compareTo(y.toInstant()));",
          "        if (a instanceof UUID x && b instanceof UUID y) return Integer.signum(x.toString().compareTo(y.toString()));",
          "        if (a instanceof Number x && b instanceof Number y) return Long.signum(x.longValue() - y.longValue());",
          "        return Integer.signum(((Comparable<Object>) a).compareTo(b));",
          "    }", "",
          "    /** Un valore dello stesso tipo, sicuramente diverso (stringhe entro length caratteri). */",
          "    @SuppressWarnings(\"unchecked\")",
          "    public static <T> T different(T v, int length) {",
          "        Object out;",
          "        if (v instanceof UUID) out = UUID.randomUUID();",
          "        else if (v instanceof Integer i) out = i + 1000003;",
          "        else if (v instanceof Long l) out = l + 1000003L;",
          "        else if (v instanceof BigDecimal d) out = d.add(BigDecimal.valueOf(1000003));",
          "        else if (v instanceof Boolean b) out = !b;",
          "        else if (v instanceof LocalDate d) out = d.plusDays(401);",
          "        else if (v instanceof OffsetDateTime d) out = d.plusDays(401);",
          "        else {",
          '            String s = "x" + v;',
          "            if (length > 0 && s.length() > length) s = s.substring(0, length);",
          '            if (s.equals(v)) s = s.substring(0, s.length() - 1) + "y";',
          "            out = s;",
          "        }",
          "        return (T) out;",
          "    }", "",
          "    @SuppressWarnings(\"unchecked\")",
          "    public static <T> T greater(T v) {",
          "        Object out;",
          '        if (v instanceof UUID) out = UUID.fromString("ffffffff-ffff-ffff-ffff-ffffffffffff");',
          "        else if (v instanceof Integer i) out = i + 1;",
          "        else if (v instanceof Long l) out = l + 1L;",
          "        else if (v instanceof BigDecimal d) out = d.add(BigDecimal.ONE);",
          "        else if (v instanceof LocalDate d) out = d.plusDays(1);",
          "        else if (v instanceof OffsetDateTime d) out = d.plusDays(1);",
          '        else out = v + "~";',
          "        return (T) out;",
          "    }", "",
          "    @SuppressWarnings(\"unchecked\")",
          "    public static <T> T smaller(T v) {",
          "        Object out;",
          '        if (v instanceof UUID) out = UUID.fromString("00000000-0000-0000-0000-000000000000");',
          "        else if (v instanceof Integer i) out = i - 1;",
          "        else if (v instanceof Long l) out = l - 1L;",
          "        else if (v instanceof BigDecimal d) out = d.subtract(BigDecimal.ONE);",
          "        else if (v instanceof LocalDate d) out = d.minusDays(1);",
          "        else if (v instanceof OffsetDateTime d) out = d.minusDays(1);",
          '        else out = "";',
          "        return (T) out;",
          "    }"]
    for n, t in tables.items():
        o += ["", f"    public static {n} build{n}(EntityManager em) {{", f"        return build{n}(em, e -> {{ }});", "    }", "",
              f"    /** Inserisce un {n} valido; over cambia i valori prima dell'inserimento. */",
              f"    public static {n} build{n}(EntityManager em, Consumer<{n}> over) {{", f"        {n} e = new {n}();"]
        for c in t.columns:
            if (c.primary_key and c.auto) or c.generated or c.default is not None:
                continue
            rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
            if rel and not c.required:
                continue
            o.append(f"        e.{_set(c.name)}({_sample(t, c.name, tables)});")
        o += ["        over.accept(e);", f"        return new {repo_class(L, n)}(em).create(e);", "    }"]
    o.append("}")
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------------------------------- casi per tabella

def _check(a: str, op: str, val, kind: str) -> str:
    x = f"x.{a}()"
    return {"eq": f"cmp({x}, {val}) == 0", "ne": f"cmp({x}, {val}) != 0", "lt": f"cmp({x}, {val}) < 0",
            "lte": f"cmp({x}, {val}) <= 0", "gt": f"cmp({x}, {val}) > 0", "gte": f"cmp({x}, {val}) >= 0",
            "in": f"{val}.stream().anyMatch(v -> cmp({x}, v) == 0)", "prefix": f"String.valueOf({x}).startsWith({val})",
            "is_null": f"{x} == null", "not_null": f"{x} != null"}[op]


def _query_case(t: Table, tc: TestCase, tables: Dict[str, Table]) -> List[str]:
    q = next(x for x in t.queries if x.name == tc.args["query"])
    flip, empty = tc.args.get("flip"), tc.args.get("empty")
    repo = repo_class(L, t.name)
    lines, over, params, checks, noise = [], [], [], [], []
    for i, c in enumerate(q.where):
        col = t.col(c.column)
        g, s = _get(c.column), _set(c.column)
        flipped = i == flip
        ln = col.length or 0
        if c.has_value:
            lit = _java_value(col, c.value)
            outside, inside = f"x.{s}(different({lit}, {ln}));", f"x.{s}({lit});"
            if c.op == "ne":
                outside, inside = inside, outside
            over.append(outside if flipped else inside)
            noise.append(outside)
            checks.append(_check(g, c.op, lit, col.type))
            continue
        if c.op in ("is_null", "not_null"):
            want_null = (c.op == "is_null") != flipped
            sample = _sample(t, c.column, tables)
            over.append(f"x.{s}(null);" if want_null else f"x.{s}({sample});")
            noise.append(f"x.{s}(null);" if c.op == "not_null" else f"x.{s}({sample});")
            checks.append(_check(g, c.op, None, col.type))
            continue
        if col.nullable:
            over.append(f"x.{s}({_sample(t, c.column, tables)});")
        pn = member(L, c.param)
        v = f"e.{g}()"
        jt = J_TYPE[col.type]
        expr = {
            "eq": f"different({v}, {ln})" if flipped else v,
            "ne": v if flipped else f"different({v}, {ln})",
            "gte": f"greater({v})" if flipped else v,
            "lte": f"smaller({v})" if flipped else v,
            "gt": v if flipped else f"smaller({v})",
            "lt": v if flipped else f"greater({v})",
            "in": f"List.of(different({v}, {ln}))" if flipped else f"List.of({v})",
            "prefix": '"zz"' if flipped else f"String.valueOf({v}).substring(0, 1)",
        }[c.op]
        if i == empty:
            expr = "List.of()"
        params.append((f"Collection<{jt}>" if c.op == "in" else jt, pn, expr))
        checks.append(_check(g, c.op, pn, col.type))
    body = " ".join(over)
    lines.append(f"        {t.name} e = build{t.name}(em, x -> {{ {body} }});" if over else f"        {t.name} e = build{t.name}(em);")
    if flip is None and empty is None and noise:
        lines.append(f"        build{t.name}(em, x -> {{ {' '.join(noise)} }}); // fuori dalla classe: non deve comparire")
    for jt, pn, expr in params:
        lines.append(f"        {jt} {pn} = {expr};")
    args = ", ".join(pn for _, pn, _ in params)
    meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
    if q.returns == "page" and flip is None and empty is None:
        # senza pagina: limite predefinito, sufficiente per i due record del caso
        lines.append(f"        List<{t.name}> rows = new {repo}(em).{meth}({args}).items();")
    elif q.returns == "page":
        lines.append(f"        List<{t.name}> rows = new {repo}(em).{meth}({args + ', ' if args else ''}Paging.PageRequest.of({t.pagination.max_limit})).items();")
    elif q.returns == "list":
        lines.append(f"        List<{t.name}> rows = new {repo}(em).{meth}({args});")
    else:
        lines.append(f"        List<{t.name}> rows = new {repo}(em).{meth}({args}).stream().toList();")
    pk = _get(t.pk.name)
    if empty is not None:
        lines.append("        assertTrue(rows.isEmpty());")
    elif flip is None:
        lines.append(f'        assertTrue(rows.stream().anyMatch(x -> Objects.equals(x.{pk}(), e.{pk}())), "il record che soddisfa le condizioni manca dal risultato");')
        lines.append(f'        assertTrue(rows.stream().allMatch(x -> {" && ".join("(" + c + ")" for c in checks)}), "un record restituito non soddisfa le condizioni");')
    else:
        lines.append(f'        assertTrue(rows.stream().noneMatch(x -> Objects.equals(x.{pk}(), e.{pk}())), "la condizione {flip + 1} non determina il risultato");')
    return lines


def _walk(n: str, pk: str, sort_expr: str, collect: str = "") -> List[str]:
    return ["        String cursor = null;", "        for (int i = 0; i < 100; i++) {",
            f"            Paging.Page<{n}> page = repo.listPage(new Paging.PageRequest(1, cursor, {sort_expr}));",
            f"            for ({n} x : page.items()) {{", f"                seen.add(x.{pk}());", *([collect] if collect else []), "            }",
            "            if (!page.hasMore()) break;", "            cursor = page.nextCursor();", "        }"]


def test_file(pkg: str, t: Table, cat: Catalog, tables: Dict[str, Table], default_asil: str) -> str:
    n = t.name
    repo = repo_class(L, n)
    pk = _get(t.pk.name)
    pkt = J_TYPE[t.pk.type]
    o = [header(L, f"schemas/db/{n}.yaml") + f"package {pkg}.generated;", ""] + _imports(pkg, tables) + [
        "", f"/** Test di unità generati per {n} (ASIL {table_asil(t, default_asil)}). Specifica: docs/generated/verification/{n}.md."
            " I test dei metodi custom vanno in custom/. */",
        f"class {n}Test {{", "", "    private EntityManager em;", "",
        "    @BeforeEach", "    void open() {", "        em = KybesDb.open();", "    }", "",
        "    @AfterEach", "    void close() {", "        KybesDb.close(em);", "    }"]
    compare = [c.name for c in t.columns if c.type != "json" and not c.generated]
    for tc in cat.for_table(n):
        o += ["", "    @Test", f"    @DisplayName({_jstr(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)})",
              f"    void {tc.slug}() {{", f"        // atteso: {tc.expected}"]
        k = tc.kind
        b = f"build{n}"
        if k == "create_valid":
            o += [f"        {n} e = {b}(em);", "        em.flush();", "        em.clear();",
                  f"        {n} got = new {repo}(em).getById(e.{pk}()).orElseThrow();"]
            o += [f'        assertEquals(0, cmp(got.{_get(cn)}(), e.{_get(cn)}()), "{cn}");' for cn in compare]
        elif k == "read_existing":
            o += [f"        {n} e = {b}(em);", f"        {repo} repo = new {repo}(em);",
                  f"        assertEquals(e.{pk}(), repo.getById(e.{pk}()).orElseThrow().{pk}());",
                  f"        assertTrue(repo.exists(e.{pk}()));", "        assertTrue(repo.count() >= 1);"]
        elif k == "read_missing":
            o += [f"        {repo} repo = new {repo}(em);", f"        assertTrue(repo.getById({_missing_pk(t)}).isEmpty());",
                  f"        assertFalse(repo.exists({_missing_pk(t)}));"]
        elif k == "update_allowed":
            cn = tc.args["column"]
            o += [f"        {n} e = {b}(em);", f"        var value = {_new_value(t, cn)};", f"        e.{_set(cn)}(value);",
                  f"        new {repo}(em).update(e);", "        em.flush();", "        em.clear();",
                  f"        assertEquals(0, cmp(new {repo}(em).getById(e.{pk}()).orElseThrow().{_get(cn)}(), value));"]
        elif k == "update_missing":
            o += [f"        {n} e = {b}(em);", f"        {repo} repo = new {repo}(em);", f"        assertTrue(repo.delete(e.{pk}()));",
                  "        em.flush();", "        long before = repo.count();",
                  "        assertThrows(EntityNotFoundException.class, () -> repo.update(e));",
                  f"        assertTrue(repo.getById(e.{pk}()).isEmpty());", "        assertEquals(before, repo.count());"]
        elif k == "update_key":
            if t.pk.auto:
                o += [f'        assertThrows(NoSuchMethodException.class, () -> {n}.class.getMethod("{_set(t.pk.name)}", {pkt}.class));',
                      f"        assertThrows(IllegalArgumentException.class, () -> new {repo}(em).update(new {n}()));"]
            else:
                o += [f"        {n} e = {b}(em);", "        em.flush();", "        em.detach(e);", f"        {pkt} original = e.{pk}();",
                      f"        e.{_set(t.pk.name)}({_missing_pk(t)});",
                      f"        assertThrows(EntityNotFoundException.class, () -> new {repo}(em).update(e));",
                      f"        assertTrue(new {repo}(em).exists(original));"]
        elif k == "delete":
            o += [f"        {n} e = {b}(em);", f"        {repo} repo = new {repo}(em);", f"        assertTrue(repo.delete(e.{pk}()));",
                  "        em.flush();", f"        assertTrue(repo.getById(e.{pk}()).isEmpty());", f"        assertFalse(repo.delete(e.{pk}()));"]
        elif k == "find_by":
            cn = tc.args["column"]
            meth = method_name(L, "find_by:" + cn)
            o += [f"        {n} e = {b}(em);", f"        {repo} repo = new {repo}(em);",
                  f"        assertEquals(e.{pk}(), repo.{meth}(e.{_get(cn)}()).orElseThrow().{pk}());",
                  f"        assertTrue(repo.{meth}(different(e.{_get(cn)}(), {t.col(cn).length or 0})).isEmpty());"]
        elif k == "required_null":
            cn = tc.args["column"]
            o += [f'        assertRule("{cn}", "obbligatorio", () -> {b}(em, x -> x.{_set(cn)}(null)));']
        elif k == "maxlen_at":
            cn, ln = tc.args["column"], tc.args["length"]
            o += [f'        {n} e = {b}(em, x -> x.{_set(cn)}("a".repeat({ln})));', "        em.flush();",
                  f"        assertEquals({ln}, e.{_get(cn)}().length());"]
        elif k == "maxlen_over":
            cn, ln = tc.args["column"], tc.args["length"]
            o += [f'        assertInvalid("{cn}", () -> {b}(em, x -> x.{_set(cn)}("a".repeat({ln + 1}))));']
        elif k == "unique_duplicate":
            cn = tc.args["column"]
            o += [f"        {n} e = {b}(em);", "        em.flush();", "        assertThrows(PersistenceException.class, () -> {",
                  f"            {b}(em, x -> x.{_set(cn)}(e.{_get(cn)}()));", "            em.flush();", "        });"]
        elif k == "default_value":
            c = t.col(tc.args["column"])
            o += [f"        {n} e = {b}(em);", "        em.flush();", "        em.clear();",
                  f"        assertEquals(0, cmp(new {repo}(em).getById(e.{pk}()).orElseThrow().{_get(c.name)}(), {_java_value(c, c.default)}));"]
        elif k in ("rel_parent", "list_by"):
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            tpk = _get(tables[r.target].pk.name)
            o += [f"        {r.target} parent = build{r.target}(em);", f"        {n} child = {b}(em, x -> x.{_set(r.foreign_key)}(parent.{tpk}()));"]
            if k == "rel_parent":
                meth = method_name(L, "get_rel:" + r.name)
                o += [f"        {repo} repo = new {repo}(em);", f"        assertEquals(parent.{tpk}(), repo.{meth}(child.{pk}()).orElseThrow().{tpk}());",
                      f"        assertTrue(repo.{meth}({_missing_pk(t)}).isEmpty());"]
            else:
                meth = method_name(L, "list_by:" + r.foreign_key)
                fk = _get(r.foreign_key)
                o += [f"        List<{n}> items = new {repo}(em).{meth}(parent.{tpk}(), Paging.PageRequest.of({t.pagination.max_limit})).items();",
                      f"        assertTrue(items.stream().anyMatch(x -> Objects.equals(x.{pk}(), child.{pk}())));",
                      f"        assertTrue(items.stream().allMatch(x -> Objects.equals(x.{fk}(), parent.{tpk}())));"]
        elif k == "rel_children":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            ct = tables[r.target]
            cpk, fk = _get(ct.pk.name), _get(r.foreign_key)
            o += [f"        {n} parent = {b}(em);", f"        {r.target} child = build{r.target}(em, x -> x.{_set(r.foreign_key)}(parent.{pk}()));",
                  f"        List<{r.target}> items = new {repo}(em).{method_name(L, 'list_rel:' + r.name)}(parent.{pk}(), Paging.PageRequest.of({ct.pagination.max_limit})).items();",
                  f"        assertTrue(items.stream().anyMatch(x -> Objects.equals(x.{cpk}(), child.{cpk}())));",
                  f"        assertTrue(items.stream().allMatch(x -> Objects.equals(x.{fk}(), parent.{pk}())));"]
        elif k == "page_walk":
            sort = tc.args.get("sort")
            sort_expr = _jstr(",".join(("-" if x.startswith("-") else "") + member("typescript", x.lstrip("-")) for x in sort)) if sort else "null"
            o += ["        Set<Object> built = new HashSet<>();", f"        for (int i = 0; i < 3; i++) built.add({b}(em).{pk}());",
                  f"        {repo} repo = new {repo}(em);", "        List<Object> seen = new ArrayList<>();"]
            o += _walk(n, pk, sort_expr)
            o += ["        assertTrue(seen.containsAll(built));", "        assertEquals(seen.size(), new HashSet<>(seen).size());"]
        elif k == "generated_values":
            cols, upd = tc.args["columns"], tc.args["update"]
            o += [f"        {n} e = {b}(em);", "        em.flush();", "        em.clear();", f"        {repo} repo = new {repo}(em);",
                  f"        {n} before = repo.getById(e.{pk}()).orElseThrow();"]
            o += [f'        assertNotNull(before.{_get(cn)}(), "{cn}");' for cn, _ in cols]
            o += [f"        Object before{i} = before.{_get(cn)}();" for i, (cn, _) in enumerate(cols)]
            if upd:
                o += [f"        before.{_set(upd)}({_new_value(t, upd)});", "        repo.update(before);", "        em.flush();", "        em.clear();",
                      f"        {n} after = repo.getById(e.{pk}()).orElseThrow();"]
                for cn, g in cols:
                    op = "== 0" if g == "on_create" else ">= 0"
                    o.append(f'        assertTrue(cmp(after.{_get(cn)}(), before{cols.index((cn, g))}) {op}, "{cn}");')
        elif k == "optional_null":
            cn = tc.args["column"]
            o += [f"        {n} e = {b}(em, x -> x.{_set(cn)}(null));", "        em.flush();", "        em.clear();",
                  f"        assertNull(new {repo}(em).getById(e.{pk}()).orElseThrow().{_get(cn)}());"]
        elif k == "rel_parent_object":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            tpk = _get(tables[r.target].pk.name)
            gfk, sfk, grel, srel = _get(r.foreign_key), _set(r.foreign_key), "get" + _cap(member(L, r.name)), "set" + _cap(member(L, r.name))
            o += [f"        {r.target} parent = build{r.target}(em);",
                  f"        {n} child = {b}(em, x -> {{ x.{sfk}(null); x.{srel}(parent); }});",
                  f"        assertEquals(parent.{tpk}(), child.{gfk}());",
                  "        // chiave e oggetto restano coerenti: la stessa chiave mantiene l'oggetto, una diversa lo scollega",
                  f"        child.{sfk}(parent.{tpk}());", f"        assertSame(parent, child.{grel}());",
                  f"        child.{sfk}(different(parent.{tpk}(), 0));", f"        assertNull(child.{grel}());",
                  f"        child.{srel}(null);", f"        assertNull(child.{gfk}());", "        em.clear();"]
        elif k == "page_default":
            o += [f"        {n} e = {b}(em);", f"        {repo} repo = new {repo}(em);",
                  f"        assertEquals({t.pagination.default_limit}, repo.listPage().limit());"]
            for r in t.relations:
                tt = tables[r.target]
                if r.kind == "many_to_one":
                    val = f"e.{_get(r.foreign_key)}()" if t.col(r.foreign_key).required else f"build{r.target}(em).{_get(tt.pk.name)}()"
                    o.append(f"        assertEquals({t.pagination.default_limit}, repo.{method_name(L, 'list_by:' + r.foreign_key)}({val}).limit());")
                else:
                    o.append(f"        assertEquals({tt.pagination.default_limit}, repo.{method_name(L, 'list_rel:' + r.name)}(e.{pk}()).limit());")
        elif k == "page_sort_each":
            o += [f"        for (int i = 0; i < 3; i++) {b}(em);", f"        {repo} repo = new {repo}(em);", "        long total = repo.count();"]
            for x in tc.args["sorts"]:
                cn = x.lstrip("-")
                sort_json = ("-" if x.startswith("-") else "") + member("typescript", cn)
                cmp_ok = ">= 0" if x.startswith("-") else "<= 0"
                o += ["        {", "            List<Object> seen = new ArrayList<>();", "            List<Object> values = new ArrayList<>();"]
                o += ["    " + line for line in _walk(n, pk, _jstr(sort_json), f"                values.add(x.{_get(cn)}());")]
                o += [f'            assertEquals(total, seen.size(), "{sort_json}");',
                      f'            assertEquals(seen.size(), new HashSet<>(seen).size(), "{sort_json}");',
                      "            for (int i = 1; i < values.size(); i++) {",
                      f'                assertTrue(cmp(values.get(i - 1), values.get(i)) {cmp_ok}, "{sort_json}");', "            }", "        }"]
        elif k == "page_limit":
            o += [f'        assertInvalid("limit", () -> new {repo}(em).listPage(Paging.PageRequest.of({tc.args["limit"]})));']
        elif k == "page_limit_ok":
            o += [f"        {b}(em);", f"        Paging.Page<{n}> page = new {repo}(em).listPage(Paging.PageRequest.of({tc.args['limit']}));",
                  f"        assertEquals({tc.args['limit']}, page.limit());", "        assertFalse(page.items().isEmpty());"]
        elif k == "page_sort_invalid":
            o += [f'        assertInvalid("sort", () -> new {repo}(em).listPage(new Paging.PageRequest(null, null, "kybesNonOrdinabile")));']
        elif k == "page_cursor_invalid":
            o += [f'        assertInvalid("cursor", () -> new {repo}(em).listPage(new Paging.PageRequest(null, "kybes-non-valido", null)));']
        elif k in ("query_match", "query_mcdc", "query_empty_in"):
            o += _query_case(t, tc, tables)
        else:
            raise ValueError(k)
        o.append("    }")
    o.append("}")
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------------------------------- moduli comuni

def runtime_file(pkg: str, cat: Catalog, tables: Dict[str, Table]) -> str:
    first = next(iter(tables.values()))
    n, repo = first.name, repo_class(L, first.name)
    pk = _get(first.pk.name)
    tbl_list = ", ".join(f"{x}.class" for x in tables)
    repo_list = ", ".join(f"{repo_class(L, x)}.class" for x in tables)
    bodies = {
        "rt_exports": [f"        for (Class<?> entity : List.<Class<?>>of({tbl_list})) {{",
                       '            assertNotNull(entity.getAnnotation(jakarta.persistence.Entity.class), entity.getSimpleName());',
                       '            Object row = entity.getDeclaredConstructor().newInstance();',
                       '            java.lang.reflect.InvocationTargetException error = assertThrows(java.lang.reflect.InvocationTargetException.class,'
                       ' () -> entity.getMethod("kybesValue", String.class).invoke(row, "kybesNonOrdinabile"));',
                       '            assertInstanceOf(IllegalArgumentException.class, error.getCause());',
                       "        }",
                       f"        for (Class<?> repoClass : List.<Class<?>>of({repo_list})) {{",
                       "            assertNotNull(repoClass.getConstructor(EntityManager.class).newInstance(em));", "        }"],
        "rt_sort_key": ['        assertEquals(List.of(new Paging.OrderItem("id", "id", Paging.SortType.UUID, true)), Paging.resolveOrder(SPEC, "-id"));',
                        '        assertEquals(SPEC.defaultOrder(), Paging.resolveOrder(SPEC, null));',
                        '        assertEquals(SPEC.defaultOrder(), Paging.resolveOrder(SPEC, " "));',
                        '        assertEquals(2, Paging.resolveOrder(SPEC, ",numero").size());'],
        "rt_sort_plus": ['        List<Paging.OrderItem> order = Paging.resolveOrder(SPEC, "+numero");', "        assertFalse(order.get(0).desc());",
                         '        assertEquals("id", order.get(order.size() - 1).field());'],
        "rt_cursor_roundtrip": ["        Map<String, Object> row = new HashMap<>(ROW);",
                                '        row.put("numero", "A \\"q\\" \\\\ \\n\\r\\t\\u0001 è");',
                                "        String cursor = Paging.encodeCursor(ALL, row, Map::get);",
                                "        List<Object> values = Paging.decodeCursor(SPEC, ALL, cursor);",
                                "        for (int i = 0; i < ALL.size(); i++) {",
                                "            assertEquals(0, cmp(values.get(i), row.get(ALL.get(i).field())), ALL.get(i).field());", "        }",
                                '        String spaced = raw(" { \\"x\\" : -5 , \\"s\\" : \\"numero,id\\" , \\"v\\" : [ \\"\\\\b\\\\f\\\\/\\\\u0041\\" , '
                                '\\"00000000-0000-0000-0000-00000000000a\\" ] } ");',
                                '        assertEquals("\\b\\f/A", Paging.decodeCursor(SPEC, Paging.resolveOrder(SPEC, "numero"), spaced).get(0));',
                                '        assertThrows(IllegalStateException.class, () -> Paging.encodeCursor(ALL, new HashMap<String, Object>(), Map::get));'],
        "rt_cursor_types": ["        List<Object> good = List.of(\"00000000-0000-0000-0000-00000000000a\", \"x\", 1L, \"1\", \"1\", \"2026-01-01\", \"2026-01-01T00:00:00Z\");",
                            "        Object[][] bad = {{0, 1L}, {1, 7L}, {2, \"uno\"}, {2, 3000000000L}, {2, -3000000000L}, {6, \"ieri\"}, {6, 3L}};",
                            "        for (Object[] b : bad) {", "            List<Object> values = new ArrayList<>(good);",
                            "            values.set((Integer) b[0], b[1]);",
                            '            assertInvalid("cursor", () -> Paging.decodeCursor(SPEC, ALL, rawCursor(ALL, values)));', "        }",
                            '        for (String json : List.of("non json", "{\\"s\\": \\"id\\", \\"v\\": [\\"aperta", "{\\"s\\": \\"id\\", \\"v\\": [x]}", "{\\"s\\": \\"id\\"}", "", "{", "{\\"s\\": \\"id\\", \\"v\\": [-", "{\\"s\\": \\"id\\", \\"v\\": [5")) {',
                            '            assertInvalid("cursor", () -> Paging.decodeCursor(SPEC, SPEC.defaultOrder(), raw(json)));', "        }",
                            '        assertInvalid("cursor", () -> Paging.decodeCursor(SPEC, SPEC.defaultOrder(), "%%%"));',
                            '        assertInvalid("cursor", () -> Paging.decodeCursor(SPEC, SPEC.defaultOrder(), rawCursor(SPEC.defaultOrder(), List.of("a", "b"))));'],
        "rt_cursor_signature": ['        String cursor = rawCursor(Paging.resolveOrder(SPEC, "-numero"), List.of("x", "00000000-0000-0000-0000-00000000000a"));',
                                '        assertInvalid("cursor", () -> Paging.decodeCursor(SPEC, Paging.resolveOrder(SPEC, "numero"), cursor));'],
        "rt_like": ['        assertEquals("a\\\\%\\\\_\\\\\\\\%", Paging.likePrefix("a%_\\\\"));'],
        "rt_fixed_sort": [f'        assertInvalid("sort", () -> Paging.runPage(em, {n}.class, {n}RepositoryBase.PAGING, null, Map.of(), '
                          f'new Paging.PageRequest(null, null, "x"), {n}RepositoryBase.PAGING.defaultOrder(), {n}::kybesValue));',
                          f"        Paging.Page<{n}> empty = Paging.emptyPage({n}RepositoryBase.PAGING, null);",
                          "        assertTrue(empty.items().isEmpty());", "        assertNull(empty.nextCursor());",
                          f"        assertEquals({n}RepositoryBase.PAGING.defaultLimit(), empty.limit());",
                          f"        assertEquals(7, Paging.emptyPage({n}RepositoryBase.PAGING, Paging.PageRequest.of(7)).limit());",
                          f"        assertEquals({n}RepositoryBase.PAGING.defaultLimit(), Paging.emptyPage({n}RepositoryBase.PAGING, Paging.PageRequest.first()).limit());",
                          f'        assertTrue(Paging.runPage(em, {n}.class, {n}RepositoryBase.PAGING, null, Map.of(), new Paging.PageRequest(null, null, " "), '
                          f'{n}RepositoryBase.PAGING.defaultOrder(), {n}::kybesValue).items().isEmpty());',
                          '        assertEquals("c", Paging.PageRequest.of(3).next("c").cursor());'],
        "rt_empty_page": [f"        Paging.Page<{n}> page = new {repo}(em).listPage(Paging.PageRequest.of(5));", "        assertTrue(page.items().isEmpty());",
                          f"        assertTrue(Paging.runPage(em, {n}.class, {n}RepositoryBase.PAGING, null, Map.of(), null, null, {n}::kybesValue).items().isEmpty());",
                          f"        assertTrue(new {repo}(em).listPage(new Paging.PageRequest(null, \"\", null)).items().isEmpty());",
                          "        assertFalse(page.hasMore());", f"        assertTrue(new {repo}(em).listPage().items().isEmpty());"],
        "rt_isolation": ["        assertEquals(UnitOfWork.Isolation.READ_COMMITTED, UnitOfWork.isolationFor(List.of()));",
                         '        assertEquals(UnitOfWork.Isolation.READ_COMMITTED, UnitOfWork.isolationFor(List.of("kybesSconosciuta")));',
                         "        UnitOfWork.Isolation best = UnitOfWork.ISOLATION.values().stream().max(Comparator.naturalOrder()).orElseThrow();",
                         "        assertEquals(best, UnitOfWork.isolationFor(UnitOfWork.ISOLATION.keySet()));"],
        "rt_isolation_applied": ['        String sql = "SELECT current_setting(\'transaction_isolation\')";',
                                 "        for (UnitOfWork.Isolation level : UnitOfWork.Isolation.values()) {",
                                 "            Object got = UnitOfWork.run(emf(), w -> w.createNativeQuery(sql).getSingleResult(), null, level, 0, 0);",
                                 "            assertEquals(level.sql().toLowerCase(Locale.ROOT), got);", "        }"],
        "rt_commit": [f'        {first.pk and J_TYPE[first.pk.type]} id = UnitOfWork.run(emf(), w -> build{n}(w).{pk}(), List.of("{n}"));',
                      f"        assertTrue(new {repo}(em).exists(id));"],
        "rt_rollback": ['        RuntimeException error = assertThrows(RuntimeException.class, () -> UnitOfWork.run(emf(), w -> {',
                        f"            build{n}(w);", '            throw new IllegalStateException("errore applicativo");', "        }, List.of()));",
                        '        assertEquals("errore applicativo", error.getMessage());', f"        assertEquals(0, new {repo}(em).count());"],
        "rt_retry": ["        AtomicInteger calls = new AtomicInteger();", "        int result = UnitOfWork.run(emf(), w -> {",
                     f"            build{n}(w);",
                     '            if (calls.incrementAndGet() < 3) throw new IllegalStateException(new SQLException("conflitto", "40001"));',
                     "            return calls.get();", f'        }}, List.of("{n}"), null, 3, 0);', "        assertEquals(3, result);",
                     f"        assertEquals(1, new {repo}(em).count());"],
        "rt_retry_limit": ["        AtomicInteger calls = new AtomicInteger();", "        assertThrows(IllegalStateException.class, () -> UnitOfWork.run(emf(), w -> {",
                           "            calls.incrementAndGet();", '            throw new IllegalStateException(new SQLException("stallo", "40P01"));',
                           "        }, List.of(), null, 2, 0));", "        assertEquals(3, calls.get());",
                           "        // attesa tra i tentativi interrotta: errore esplicito, il flag di interruzione resta impostato",
                           "        Thread.currentThread().interrupt();",
                           "        IllegalStateException stopped = assertThrows(IllegalStateException.class, () -> UnitOfWork.run(emf(), w -> {",
                           '            throw new IllegalStateException(new SQLException("conflitto", "40001"));',
                           "        }, List.of(), null, 1, 10));",
                           "        assertTrue(Thread.interrupted());", '        assertEquals("transazione interrotta", stopped.getMessage());'],
        "rt_retry_other": ["        AtomicInteger calls = new AtomicInteger();", "        assertThrows(IllegalStateException.class, () -> UnitOfWork.run(emf(), w -> {",
                           "            calls.incrementAndGet();", '            throw new IllegalStateException(new SQLException("duplicato", "23505"));',
                           "        }, List.of()));", "        assertEquals(1, calls.get());",
                           '        assertFalse(UnitOfWork.isRetryable(new IllegalStateException(new SQLException("senza codice"))));',
                           "        // rollback: solo se la transazione è attiva; un suo errore resta allegato a quello originale",
                           "        RuntimeException original = new IllegalStateException(\"originale\");",
                           "        UnitOfWork.rollbackQuietly(new FakeTx(false, null), original);",
                           "        UnitOfWork.rollbackQuietly(new FakeTx(true, new IllegalStateException(\"rollback fallito\")), original);",
                           "        assertEquals(1, original.getSuppressed().length);",
                           "        FakeTx ok = new FakeTx(true, null);", "        UnitOfWork.rollbackQuietly(ok, original);", "        assertTrue(ok.rolledBack);"],
    }
    o = [header(L, "kit") + f"package {pkg}.generated;", ""] + _imports(pkg, tables, [
        "import java.sql.SQLException;", "import java.util.concurrent.atomic.AtomicInteger;"]) + [
        "", "/** Test di unità generati per i moduli comuni: paginazione (Paging), Unit of Work (UnitOfWork) e API del modello. */",
        "class KybesRuntimeTest {", "",
        "    static final List<Paging.OrderItem> ALL = List.of(",
        '            new Paging.OrderItem("id", "id", Paging.SortType.UUID, false),',
        '            new Paging.OrderItem("numero", "numero", Paging.SortType.STRING, false),',
        '            new Paging.OrderItem("quantita", "quantita", Paging.SortType.INT, false),',
        '            new Paging.OrderItem("grande", "grande", Paging.SortType.BIGINT, false),',
        '            new Paging.OrderItem("prezzo", "prezzo", Paging.SortType.DECIMAL, true),',
        '            new Paging.OrderItem("giorno", "giorno", Paging.SortType.DATE, false),',
        '            new Paging.OrderItem("istante", "istante", Paging.SortType.DATETIME, true));',
        "    static final Map<String, Object> ROW = Map.of(\"id\", UUID.fromString(\"00000000-0000-0000-0000-00000000000a\"), \"numero\", \"A-1\",",
        "            \"quantita\", 7, \"grande\", 12345678901L, \"prezzo\", new BigDecimal(\"3.25\"), \"giorno\", LocalDate.parse(\"2026-02-03\"),",
        "            \"istante\", OffsetDateTime.parse(\"2026-02-03T04:05:06Z\"));",
        '    static final Paging.Spec SPEC = new Paging.Spec("Prova", "Prova", new Paging.OrderItem("id", "id", Paging.SortType.UUID, false),',
        '            Map.of("numero", new Paging.OrderItem("numero", "numero", Paging.SortType.STRING, false)),',
        '            List.of(new Paging.OrderItem("id", "id", Paging.SortType.UUID, false)), 50, 100);', "",
        "    private EntityManager em;", "",
        "    @BeforeEach", "    void open() {", "        em = KybesDb.open();", "    }", "",
        "    @AfterEach", "    void close() {", "        KybesDb.close(em);", "    }", "",
        "    static String raw(String json) {",
        "        return Base64.getUrlEncoder().withoutPadding().encodeToString(json.getBytes(java.nio.charset.StandardCharsets.UTF_8));", "    }", "",
        "    static String rawCursor(List<Paging.OrderItem> order, List<Object> values) {",
        "        StringBuilder sb = new StringBuilder(\"{\\\"s\\\": \\\"\");",
        "        for (int i = 0; i < order.size(); i++) sb.append(i > 0 ? \",\" : \"\").append(order.get(i).desc() ? \"-\" : \"\").append(order.get(i).json());",
        "        sb.append(\"\\\", \\\"v\\\": [\");",
        "        for (int i = 0; i < values.size(); i++) {",
        "            Object v = values.get(i);",
        "            sb.append(i > 0 ? \", \" : \"\").append(v instanceof String ? \"\\\"\" + v + \"\\\"\" : String.valueOf(v));", "        }",
        "        return raw(sb.append(\"]}\").toString());", "    }", "",
        "    /** Transazione finta per i casi di errore del rollback. */",
        "    static final class FakeTx implements jakarta.persistence.EntityTransaction {",
        "        final boolean active;", "        final RuntimeException failure;", "        boolean rolledBack;", "",
        "        FakeTx(boolean active, RuntimeException failure) {", "            this.active = active;", "            this.failure = failure;", "        }", "",
        "        public void begin() { }", "        public void commit() { }", "",
        "        public void rollback() {", "            if (failure != null) throw failure;", "            rolledBack = true;", "        }", "",
        "        public void setRollbackOnly() { }", "        public boolean getRollbackOnly() { return false; }",
        "        public void setTimeout(Integer timeout) { }", "        public Integer getTimeout() { return null; }",
        "        public boolean isActive() { return active; }", "    }"]
    for tc in cat.for_table("_runtime"):
        o += ["", "    @Test", f"    @DisplayName({_jstr(tc.id + ' · ' + ', '.join(tc.reqs) + ' · ' + METHODS[tc.method] + ': ' + tc.title)})",
              f"    void {tc.slug}() throws Exception {{"] + bodies[tc.kind] + ["    }"]
    o.append("}")
    return "\n".join(o) + "\n"


def emit(cat: Catalog, tables: Dict[str, Table], default_asil: str, pkg: str = "app.model") -> Dict[str, str]:
    """File relativi alla cartella dei test Java del pacchetto (es. libs/db-models/java/src/test/java/app/model)."""
    files = {"generated/KybesDb.java": db_file(pkg, tables), "generated/KybesBuilders.java": builders_file(pkg, tables)}
    for n, t in tables.items():
        files[f"generated/{n}Test.java"] = test_file(pkg, t, cat, tables, default_asil)
    files["generated/KybesRuntimeTest.java"] = runtime_file(pkg, cat, tables)
    return files
