package org.junit.jupiter.api;
import java.util.function.Supplier;
import org.junit.jupiter.api.function.Executable;
/** Stub delle firme usate dai test generati (solo compilazione). */
public final class Assertions {
    private Assertions() { }
    public static void assertEquals(Object a, Object b) { }
    public static void assertEquals(Object a, Object b, String m) { }
    public static void assertEquals(long a, long b) { }
    public static void assertEquals(long a, long b, String m) { }
    public static void assertTrue(boolean c) { }
    public static void assertTrue(boolean c, String m) { }
    public static void assertTrue(boolean c, Supplier<String> m) { }
    public static void assertFalse(boolean c) { }
    public static void assertFalse(boolean c, String m) { }
    public static void assertNull(Object o) { }
    public static void assertNotNull(Object o) { }
    public static void assertNotNull(Object o, String m) { }
    public static <T> T assertInstanceOf(Class<T> c, Object o) { return null; }
    public static <T extends Throwable> T assertThrows(Class<T> c, Executable e) { return null; }
}
