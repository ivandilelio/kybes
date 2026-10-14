package org.junit.jupiter.api;
import java.util.Objects;
import java.util.function.Supplier;
import org.junit.jupiter.api.function.Executable;
/** Stub delle firme usate dai test generati: le asserzioni funzionano davvero (per i test eseguiti senza JUnit). */
public final class Assertions {
    private Assertions() { }
    private static void fail(String m) { throw new AssertionError(m); }
    public static void assertEquals(Object a, Object b) { assertEquals(a, b, "valori diversi"); }
    public static void assertEquals(Object a, Object b, String m) { if (!Objects.equals(a, b)) fail(m + ": atteso <" + a + "> ottenuto <" + b + ">"); }
    public static void assertEquals(long a, long b) { assertEquals(a, b, "valori diversi"); }
    public static void assertEquals(long a, long b, String m) { if (a != b) fail(m + ": atteso <" + a + "> ottenuto <" + b + ">"); }
    public static void assertEquals(double a, double b) { if (Double.compare(a, b) != 0) fail("atteso <" + a + "> ottenuto <" + b + ">"); }
    public static void assertTrue(boolean c) { assertTrue(c, "atteso vero"); }
    public static void assertTrue(boolean c, String m) { if (!c) fail(m); }
    public static void assertTrue(boolean c, Supplier<String> m) { if (!c) fail(m.get()); }
    public static void assertFalse(boolean c) { assertTrue(!c, "atteso falso"); }
    public static void assertFalse(boolean c, String m) { assertTrue(!c, m); }
    public static void assertNull(Object o) { if (o != null) fail("atteso null, ottenuto <" + o + ">"); }
    public static void assertNull(Object o, String m) { if (o != null) fail(m + ": atteso null, ottenuto <" + o + ">"); }
    public static void assertNotEquals(Object a, Object b) { if (Objects.equals(a, b)) fail("valori uguali <" + a + ">"); }
    public static void assertSame(Object a, Object b) { if (a != b) fail("oggetti diversi"); }
    public static void assertNotNull(Object o) { assertNotNull(o, "atteso non null"); }
    public static void assertNotNull(Object o, String m) { if (o == null) fail(m); }
    public static <T> T assertInstanceOf(Class<T> c, Object o) { if (!c.isInstance(o)) fail("atteso " + c.getName() + ", ottenuto " + o); return c.cast(o); }
    public static <T extends Throwable> T assertThrows(Class<T> c, Executable e, String m) {
        try {
            return assertThrows(c, e);
        } catch (AssertionError err) {
            throw new AssertionError(m + ": " + err.getMessage(), err);
        }
    }
    public static <T extends Throwable> T assertThrows(Class<T> c, Executable e) {
        try {
            e.execute();
        } catch (Throwable t) {
            if (c.isInstance(t)) return c.cast(t);
            throw new AssertionError("attesa " + c.getName() + ", sollevata " + t, t);
        }
        throw new AssertionError("attesa " + c.getName() + ", nessuna eccezione");
    }
}
