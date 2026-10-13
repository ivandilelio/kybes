"""Classi di supporto Java generate: paginazione a cursore e Unit of Work."""
from __future__ import annotations

from typing import Dict

from sqlonly import strip_sql
from naming import GEN_DIR, header
from schema import Table


def paging_file(pkg: str, sql: bool = True) -> str:
    return header("java", "kit").rstrip("\n") + f"\npackage {pkg}.{GEN_DIR};\n" + strip_sql(r'''
// kybes:sql-begin
import jakarta.persistence.EntityManager;
import jakarta.persistence.TypedQuery;
// kybes:sql-end
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.function.BiFunction;

/**
 * Paginazione a cursore (keyset), uguale per UI, API e DB-Model.
 * La UI invia limit, cursor e sort (es. "-data,numero", nomi JSON); riceve items e nextCursor.
 * Il cursore e' opaco: base64url di {"s": ordinamento, "v": [valori dell'ultima riga]}, come negli altri linguaggi.
 */
public final class Paging {

    private Paging() {
    }

    public enum SortType { UUID, STRING, INT, BIGINT, DECIMAL, DATE, DATETIME }

    /** Richiesta di pagina: tutti i campi sono facoltativi. */
    public record PageRequest(Integer limit, String cursor, String sort) {
        public static PageRequest first() { return new PageRequest(null, null, null); }

        public static PageRequest of(int limit) { return new PageRequest(limit, null, null); }

        public PageRequest next(String nextCursor) { return new PageRequest(limit, nextCursor, sort); }
    }

    public record Page<T>(List<T> items, String nextCursor, int limit) {
        public boolean hasMore() { return nextCursor != null; }
    }

    /** field: campo Java; json: nome nel contratto API. */
    public record OrderItem(String field, String json, SortType type, boolean desc) {
    }

    public record Spec(String table, String entity, OrderItem pk, Map<String, OrderItem> sortable,
                       List<OrderItem> defaultOrder, int defaultLimit, int maxLimit) {
    }

    // kybes:sql-begin
    public static String likePrefix(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
    }
    // kybes:sql-end

    private static ModelValidationException invalid(Spec spec, String field, String rule) {
        return new ModelValidationException(spec.table(), Map.of(field, rule));
    }

    public static List<OrderItem> resolveOrder(Spec spec, String sort) {
        if (sort == null || sort.isBlank()) return new ArrayList<>(spec.defaultOrder());
        List<OrderItem> order = new ArrayList<>();
        for (String raw : sort.split(",")) {
            String token = raw.trim();
            if (token.isEmpty()) continue;
            boolean desc = token.startsWith("-");
            String name = token.replaceFirst("^[-+]", "");
            OrderItem col = name.equals(spec.pk().json()) ? spec.pk() : spec.sortable().get(name);
            if (col == null) throw invalid(spec, "sort", "colonna non ordinabile: " + name);
            order.add(new OrderItem(col.field(), col.json(), col.type(), desc));
        }
        if (order.stream().noneMatch(o -> o.field().equals(spec.pk().field()))) order.add(spec.pk());
        return order;
    }

    private static String signature(List<OrderItem> order) {
        StringBuilder sb = new StringBuilder();
        for (OrderItem o : order) {
            if (sb.length() > 0) sb.append(',');
            if (o.desc()) sb.append('-');
            sb.append(o.json());
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ cursore (JSON minimo, senza dipendenze)

    private static void jsonString(StringBuilder sb, String s) {
        sb.append('"');
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        sb.append('"');
    }

    public static <T> String encodeCursor(List<OrderItem> order, T row, BiFunction<T, String, Object> value) {
        StringBuilder sb = new StringBuilder("{\"s\":");
        jsonString(sb, signature(order));
        sb.append(",\"v\":[");
        for (int i = 0; i < order.size(); i++) {
            if (i > 0) sb.append(',');
            Object v = value.apply(row, order.get(i).field());
            if (v == null) throw new IllegalStateException("colonna di ordinamento nulla: " + order.get(i).field());
            if (order.get(i).type() == SortType.INT) sb.append(((Number) v).intValue());
            else jsonString(sb, String.valueOf(v));
        }
        sb.append("]}");
        return Base64.getUrlEncoder().withoutPadding().encodeToString(sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** Lettore del solo formato del cursore: {"s": stringa, "v": [stringhe o interi]}. */
    private static final class Reader {
        private final String s;
        private int i;

        Reader(String s) { this.s = s; }

        void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

        void expect(char c) {
            ws();
            if (i >= s.length() || s.charAt(i) != c) throw new IllegalArgumentException("atteso " + c);
            i++;
        }

        boolean peek(char c) { ws(); return i < s.length() && s.charAt(i) == c; }

        String string() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    char e = s.charAt(i++);
                    switch (e) {
                        case 'n' -> sb.append('\n');
                        case 'r' -> sb.append('\r');
                        case 't' -> sb.append('\t');
                        case 'b' -> sb.append('\b');
                        case 'f' -> sb.append('\f');
                        case 'u' -> { sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; }
                        default -> sb.append(e);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new IllegalArgumentException("stringa non chiusa");
        }

        Object value() {
            ws();
            if (peek('"')) return string();
            int start = i;
            if (i < s.length() && s.charAt(i) == '-') i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            if (start == i) throw new IllegalArgumentException("valore non valido");
            return Long.parseLong(s.substring(start, i));
        }
    }

    public static List<Object> decodeCursor(Spec spec, List<OrderItem> order, String cursor) {
        try {
            String json = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            Reader r = new Reader(json);
            String sig = null;
            List<Object> raw = null;
            r.expect('{');
            while (!r.peek('}')) {
                String key = r.string();
                r.expect(':');
                if (key.equals("s")) {
                    sig = r.string();
                } else if (key.equals("v")) {
                    raw = new ArrayList<>();
                    r.expect('[');
                    while (!r.peek(']')) {
                        raw.add(r.value());
                        if (r.peek(',')) r.expect(',');
                    }
                    r.expect(']');
                } else {
                    r.value();
                }
                if (r.peek(',')) r.expect(',');
            }
            r.expect('}');
            if (!signature(order).equals(sig) || raw == null || raw.size() != order.size()) {
                throw new IllegalArgumentException("ordinamento diverso");
            }
            List<Object> out = new ArrayList<>();
            for (int k = 0; k < order.size(); k++) out.add(decodeValue(raw.get(k), order.get(k).type()));
            return out;
        } catch (RuntimeException e) {
            throw invalid(spec, "cursor", "non valido");
        }
    }

    private static Object decodeValue(Object v, SortType type) {
        if (type == SortType.INT) {
            if (!(v instanceof Long l) || l > Integer.MAX_VALUE || l < Integer.MIN_VALUE) throw new IllegalArgumentException("intero atteso");
            return l.intValue();
        }
        if (!(v instanceof String s)) throw new IllegalArgumentException("stringa attesa");
        return switch (type) {
            case UUID -> UUID.fromString(s);
            case BIGINT -> Long.parseLong(s);
            case DECIMAL -> new BigDecimal(s);
            case DATE -> LocalDate.parse(s);
            case DATETIME -> OffsetDateTime.parse(s);
            default -> s;
        };
    }

    // kybes:sql-begin
    // ------------------------------------------------------------------ query

    private static String orderBy(List<OrderItem> order) {
        StringBuilder sb = new StringBuilder(" ORDER BY ");
        for (int k = 0; k < order.size(); k++) {
            if (k > 0) sb.append(", ");
            sb.append("e.").append(order.get(k).field()).append(order.get(k).desc() ? " DESC" : " ASC");
        }
        return sb.toString();
    }

    private static <T> TypedQuery<T> query(EntityManager em, Class<T> cls, Spec spec, String where, Map<String, Object> params,
                                           List<OrderItem> order, List<Object> after) {
        StringBuilder jpql = new StringBuilder("SELECT e FROM ").append(spec.entity()).append(" e");
        List<String> conds = new ArrayList<>();
        if (where != null) conds.add("(" + where + ")");
        Map<String, Object> all = new LinkedHashMap<>(params);
        if (after != null) {
            // (a, b, c) > (x, y, z) espanso colonna per colonna, rispettando la direzione di ognuna
            List<String> branches = new ArrayList<>();
            for (int k = 0; k < order.size(); k++) {
                StringBuilder b = new StringBuilder("(");
                for (int j = 0; j < k; j++) b.append("e.").append(order.get(j).field()).append(" = :kc").append(j).append(" AND ");
                b.append("e.").append(order.get(k).field()).append(order.get(k).desc() ? " < :kc" : " > :kc").append(k).append(')');
                branches.add(b.toString());
                all.put("kc" + k, after.get(k));
            }
            conds.add("(" + String.join(" OR ", branches) + ")");
        }
        if (!conds.isEmpty()) jpql.append(" WHERE ").append(String.join(" AND ", conds));
        jpql.append(orderBy(order));
        TypedQuery<T> q = em.createQuery(jpql.toString(), cls);
        all.forEach(q::setParameter);
        return q;
    }

    public static <T> Page<T> runPage(EntityManager em, Class<T> cls, Spec spec, String where, Map<String, Object> params,
                                      PageRequest page, List<OrderItem> fixedOrder, BiFunction<T, String, Object> value) {
        Prepared prep = prepare(spec, page, fixedOrder);
        List<OrderItem> order = prep.order();
        int limit = prep.limit();
        List<T> rows = query(em, cls, spec, where, params, order, prep.after()).setMaxResults(limit + 1).getResultList();
        boolean more = rows.size() > limit;
        List<T> items = more ? new ArrayList<>(rows.subList(0, limit)) : rows;
        String next = more ? encodeCursor(order, items.get(items.size() - 1), value) : null;
        return new Page<>(items, next, limit);
    }
    // kybes:sql-end

    /** Ordinamento, limite e valori del cursore validati di una richiesta di pagina (comune a SQL e MongoDB). */
    public record Prepared(List<OrderItem> order, int limit, List<Object> after) {
    }

    public static Prepared prepare(Spec spec, PageRequest page, List<OrderItem> fixedOrder) {
        PageRequest p = page == null ? PageRequest.first() : page;
        if (fixedOrder != null && p.sort() != null && !p.sort().isBlank()) {
            throw invalid(spec, "sort", "questa query ha un ordinamento fisso");
        }
        List<OrderItem> order = fixedOrder != null ? fixedOrder : resolveOrder(spec, p.sort());
        int limit = p.limit() == null ? spec.defaultLimit() : p.limit();
        if (limit < 1 || limit > spec.maxLimit()) throw invalid(spec, "limit", "tra 1 e " + spec.maxLimit());
        List<Object> after = p.cursor() == null || p.cursor().isEmpty() ? null : decodeCursor(spec, order, p.cursor());
        return new Prepared(order, limit, after);
    }

    // kybes:sql-begin
    public static <T> List<T> listRows(EntityManager em, Class<T> cls, Spec spec, String where, Map<String, Object> params,
                                       List<OrderItem> order) {
        return query(em, cls, spec, where, params, order, null).setMaxResults(spec.maxLimit()).getResultList();
    }

    public static <T> Optional<T> firstRow(EntityManager em, Class<T> cls, Spec spec, String where, Map<String, Object> params,
                                           List<OrderItem> order) {
        return query(em, cls, spec, where, params, order, null).setMaxResults(1).getResultStream().findFirst();
    }
    // kybes:sql-end

    public static <T> Page<T> emptyPage(Spec spec, PageRequest page) {
        int limit = page == null || page.limit() == null ? spec.defaultLimit() : page.limit();
        return new Page<>(List.of(), null, limit);
    }
}
''', sql)


def uow_file(pkg: str, tables: Dict[str, Table], dialect: str) -> str:
    entries = ",\n".join(f'        Map.entry("{n}", Isolation.{t.isolation.upper()})' for n, t in tables.items())
    set_tx = "true" if dialect == "postgres" else "false"
    return header("java", "kit").rstrip("\n") + f"\npackage {pkg}.{GEN_DIR};\n" + f'''
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import jakarta.persistence.EntityTransaction;
import java.sql.SQLException;
import java.sql.Statement;
import org.hibernate.Session;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Unit of Work: transazioni aperte dal service, con isolamento e retry sui conflitti.
 * Con Spring si puo' usare in alternativa @Transactional(isolation = ...) sul service.
 *
 * <pre>
 * UnitOfWork.run(emf, em -> {{
 *     OrdiniRepository ordini = new OrdiniRepository(em);
 *     ...
 *     return risultato;
 * }}, List.of("Ordini", "RigheOrdine"));
 * </pre>
 */
public final class UnitOfWork {{

    private UnitOfWork() {{
    }}

    public enum Isolation {{
        READ_COMMITTED("READ COMMITTED"), REPEATABLE_READ("REPEATABLE READ"), SERIALIZABLE("SERIALIZABLE");

        private final String sql;

        Isolation(String sql) {{ this.sql = sql; }}

        public String sql() {{ return sql; }}
    }}

    /** Livello di isolamento dichiarato negli schemi (transactions.isolation). */
    public static final Map<String, Isolation> ISOLATION = Map.ofEntries(
{entries}
    );

    /** SQLSTATE ritentabili: conflitto di serializzazione e deadlock. */
    public static final Set<String> RETRYABLE_SQLSTATE = Set.of("40001", "40P01");

    /** true: imposta l'isolamento con SET TRANSACTION (PostgreSQL); false: usa quello predefinito del database. */
    public static final boolean SET_ISOLATION = {set_tx};

    public static Isolation isolationFor(Collection<String> tables) {{
        Isolation best = Isolation.READ_COMMITTED;
        for (String t : tables) {{
            Isolation level = ISOLATION.getOrDefault(t, Isolation.READ_COMMITTED);
            if (level.ordinal() > best.ordinal()) best = level;
        }}
        return best;
    }}

    public static boolean isRetryable(Throwable error) {{
        for (Throwable e = error; e != null; e = e.getCause()) {{
            if (e instanceof SQLException sql && sql.getSQLState() != null && RETRYABLE_SQLSTATE.contains(sql.getSQLState())) {{
                return true;
            }}
        }}
        return false;
    }}

    public static <T> T run(EntityManagerFactory emf, Function<EntityManager, T> work, Collection<String> tables) {{
        return run(emf, work, tables, null, 3, 50);
    }}

    public static <T> T run(EntityManagerFactory emf, Function<EntityManager, T> work, Collection<String> tables,
                            Isolation isolation, int maxRetries, long backoffMs) {{
        return run(emf, work, tables, isolation, maxRetries, backoffMs, null);
    }}

    /**
     * Esegue work in una transazione; la ripete da capo sui conflitti di serializzazione e sui deadlock.
     * Con tenant, l'EntityManager della transazione è legato a quel tenant (su PostgreSQL anche app.tenant_id).
     */
    public static <T> T run(EntityManagerFactory emf, Function<EntityManager, T> work, Collection<String> tables,
                            Isolation isolation, int maxRetries, long backoffMs, Object tenant) {{
        Isolation level = isolation != null ? isolation : isolationFor(tables == null ? List.of() : tables);
        for (int attempt = 0; ; attempt++) {{
            EntityManager em = emf.createEntityManager();
            EntityTransaction tx = em.getTransaction();
            try {{
                tx.begin();
                if (SET_ISOLATION) {{
                    // prima istruzione della transazione, sulla stessa connessione; vale solo per questa transazione.
                    // Via JDBC e non con una native query, che svuoterebbe la cache di secondo livello.
                    em.unwrap(Session.class).doWork(connection -> {{
                        try (Statement st = connection.createStatement()) {{
                            st.execute("SET TRANSACTION ISOLATION LEVEL " + level.sql());
                        }}
                    }});
                }}
                if (tenant != null) {{
                    Tenancy.bind(em, tenant);
                    if (SET_ISOLATION) Tenancy.applySetting(em);
                }}
                T result = work.apply(em);
                tx.commit();
                return result;
            }} catch (RuntimeException e) {{
                rollbackQuietly(tx, e);
                if (attempt >= maxRetries || !isRetryable(e)) throw e;
                sleep(backoffMs * (1L << attempt));
            }} finally {{
                em.close();
            }}
        }}
    }}

    /** Annulla la transazione se è ancora attiva; un errore del rollback non nasconde quello originale. */
    static void rollbackQuietly(EntityTransaction tx, RuntimeException error) {{
        try {{
            if (tx.isActive()) tx.rollback();
        }} catch (RuntimeException rollbackError) {{
            error.addSuppressed(rollbackError);
        }}
    }}

    private static void sleep(long ms) {{
        try {{
            Thread.sleep(ms);
        }} catch (InterruptedException e) {{
            Thread.currentThread().interrupt();
            throw new IllegalStateException("transazione interrotta", e);
        }}
    }}
}}
'''
