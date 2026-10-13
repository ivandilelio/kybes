import app.model.generated.ModelValidationException;
import app.model.generated.Ordini;
import app.model.generated.OrdiniRepositoryBase;
import app.model.generated.Paging;
import app.model.generated.UnitOfWork;
import jakarta.persistence.*;
import java.math.BigDecimal;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.*;

/** Esegue la logica Java generata con un EntityManager finto che registra JPQL e parametri. */
public class PagingTest {
    static final List<String> jpql = new ArrayList<>();
    static final List<Map<String, Object>> params = new ArrayList<>();
    static List<Object> nextResult = new ArrayList<>();
    static final List<String> native_ = new ArrayList<>();

    static class FakeQuery<T> implements TypedQuery<T> {
        final Map<String, Object> p = new LinkedHashMap<>();
        int max = -1;
        @SuppressWarnings("unchecked") public List<T> getResultList() {
            params.add(p);
            List<T> r = (List<T>) new ArrayList<>(nextResult);
            return max >= 0 && r.size() > max ? r.subList(0, max) : r;
        }
        public T getSingleResult() { throw new UnsupportedOperationException(); }
        public TypedQuery<T> setMaxResults(int m) { max = m; return this; }
        public TypedQuery<T> setFirstResult(int f) { return this; }
        public TypedQuery<T> setParameter(String n, Object v) { p.put(n, v); return this; }
    }

    static class FakeEm implements EntityManager {
        boolean active;
        public void persist(Object e) {}
        public <T> T merge(T e) { return e; }
        public void remove(Object e) {}
        public <T> T find(Class<T> c, Object pk) { return null; }
        public <T> T getReference(Class<T> c, Object pk) { return null; }
        public void flush() {}
        public void refresh(Object e) {}
        public <T> TypedQuery<T> createQuery(String q, Class<T> c) { jpql.add(q); return new FakeQuery<>(); }
        public Query createNativeQuery(String sql) { native_.add(sql); return () -> 0; }
        public EntityTransaction getTransaction() {
            return new EntityTransaction() {
                public void begin() { active = true; }
                public void commit() { active = false; }
                public void rollback() { active = false; }
                public boolean isActive() { return active; }
            };
        }
        public void close() {}
        public <T> T unwrap(Class<T> cls) {
            org.hibernate.Session s = work -> {
                try { work.execute(fakeConnection()); } catch (SQLException e) { throw new RuntimeException(e); }
            };
            return cls.cast(s);
        }
    }

    static java.sql.Connection fakeConnection() {
        java.sql.Statement st = (java.sql.Statement) java.lang.reflect.Proxy.newProxyInstance(PagingTest.class.getClassLoader(),
            new Class<?>[] { java.sql.Statement.class }, (p, m, a) -> {
                if (m.getName().equals("execute")) { native_.add((String) a[0]); return false; }
                return null;
            });
        return (java.sql.Connection) java.lang.reflect.Proxy.newProxyInstance(PagingTest.class.getClassLoader(),
            new Class<?>[] { java.sql.Connection.class }, (p, m, a) -> m.getName().equals("createStatement") ? st : null);
    }

    static Ordini ordine(String numero, LocalDate data, UUID id) {
        Ordini o = new Ordini();
        o.setNumero(numero); o.setData(data); o.setTotale(BigDecimal.ONE); o.setStato("aperto");
        try { var f = Ordini.class.getDeclaredField("id"); f.setAccessible(true); f.set(o, id); } catch (ReflectiveOperationException e) { throw new RuntimeException(e); }
        return o;
    }

    static void check(boolean ok, String msg) { if (!ok) throw new AssertionError(msg); }

    public static void main(String[] args) throws Exception {
        FakeEm em = new FakeEm();
        OrdiniRepositoryBase repo = new OrdiniRepositoryBase(em) {};
        UUID id1 = UUID.fromString("00000000-0000-0000-0000-000000000001");
        UUID id2 = UUID.fromString("00000000-0000-0000-0000-000000000002");
        UUID id3 = UUID.fromString("00000000-0000-0000-0000-000000000003");
        nextResult = List.of(ordine("A", LocalDate.parse("2026-01-03"), id1), ordine("B", LocalDate.parse("2026-01-02"), id2), ordine("C", LocalDate.parse("2026-01-01"), id3));
        Paging.Page<Ordini> p1 = repo.listPage(Paging.PageRequest.of(2));
        check(p1.items().size() == 2 && p1.hasMore(), "prima pagina");
        check(jpql.get(0).equals("SELECT e FROM Ordini e ORDER BY e.data DESC, e.id ASC"), jpql.get(0));
        repo.listPage(p1.items().isEmpty() ? null : Paging.PageRequest.of(2).next(p1.nextCursor()));
        check(jpql.get(1).equals("SELECT e FROM Ordini e WHERE ((e.data < :kc0) OR (e.data = :kc0 AND e.id > :kc1)) ORDER BY e.data DESC, e.id ASC"), jpql.get(1));
        check(params.get(1).get("kc0").equals(LocalDate.parse("2026-01-02")) && params.get(1).get("kc1").equals(id2), "valori del cursore " + params.get(1));
        repo.listDelClienteDal(id1, LocalDate.parse("2026-01-01"), Paging.PageRequest.of(10));
        check(jpql.get(2).equals("SELECT e FROM Ordini e WHERE (e.clienteId = :clienteId AND e.data >= :daData) ORDER BY e.data DESC, e.id ASC"), jpql.get(2));
        repo.listPerNumero("X%_");
        check(params.get(3).get("prefisso").equals("X\\%\\_%"), "like protetto: " + params.get(3));
        // errori del contratto
        for (Paging.PageRequest bad : List.of(new Paging.PageRequest(null, null, "note"), new Paging.PageRequest(0, null, null),
                new Paging.PageRequest(201, null, null), new Paging.PageRequest(null, "xxx", null),
                new Paging.PageRequest(5, p1.nextCursor(), "numero"))) {
            try { repo.listPage(bad); throw new AssertionError("atteso errore per " + bad); } catch (ModelValidationException e) { /* ok */ }
        }
        // compatibilità del cursore tra linguaggi
        if (args.length > 0) {
            String fromPython = args[0];
            List<Paging.OrderItem> order = Paging.resolveOrder(OrdiniRepositoryBase.PAGING, null);
            List<Object> v = Paging.decodeCursor(OrdiniRepositoryBase.PAGING, order, fromPython);
            check(v.get(0).equals(LocalDate.parse("2026-01-02")) && v.get(1).equals(id2), "cursore Python letto da Java: " + v);
            System.out.println("CURSOR " + p1.nextCursor());
        }
        // Unit of Work: retry su SQLSTATE 40001, isolamento con SET TRANSACTION
        int[] n = {0};
        EntityManagerFactory emf = () -> em;
        int r = UnitOfWork.run(emf, e -> {
            n[0]++;
            if (n[0] < 3) throw new PersistenceExceptionStub(new SQLException("conflict", "40001"));
            return n[0];
        }, List.of("RigheOrdine"), null, 3, 0);
        check(r == 3, "retry");
        check(native_.get(0).equals("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"), native_.get(0));
        check(UnitOfWork.isolationFor(List.of("Clienti", "Ordini")) == UnitOfWork.Isolation.REPEATABLE_READ, "isolamento più severo");
        try {
            UnitOfWork.run(emf, e -> { throw new IllegalStateException("errore applicativo"); }, List.of("Clienti"));
            throw new AssertionError("eccezione attesa");
        } catch (IllegalStateException e) { /* nessun retry */ }
        System.out.println("JAVA PAGING OK: JPQL keyset, parametri, like protetto, errori del contratto, cursore, Unit of Work");
    }

    static class PersistenceExceptionStub extends RuntimeException {
        private static final long serialVersionUID = 1L;
        PersistenceExceptionStub(Throwable cause) { super(cause); }
    }
}
