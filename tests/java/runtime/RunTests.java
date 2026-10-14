import java.lang.reflect.*;
import java.util.*;

/** Esegue i metodi @Test di una classe di test senza JUnit (asserzioni degli stub), saltando quelli indicati. */
public class RunTests {
    public static void main(String[] args) throws Exception {
        Class<?> c = Class.forName(args[0]);
        Set<String> skip = new HashSet<>(Arrays.asList(args).subList(1, args.length));
        int ok = 0, ko = 0;
        for (Method m : c.getDeclaredMethods()) {
            if (!m.isAnnotationPresent(org.junit.jupiter.api.Test.class) || skip.contains(m.getName())) continue;
            Constructor<?> k = c.getDeclaredConstructor();
            k.setAccessible(true);
            Object o = k.newInstance();
            m.setAccessible(true);
            try {
                m.invoke(o);
                ok++;
                System.out.println("ok   " + m.getName());
            } catch (InvocationTargetException e) {
                ko++;
                System.out.println("FAIL " + m.getName() + ": " + e.getCause());
                StackTraceElement[] st = e.getCause().getStackTrace();
                for (int i = 0; i < Math.min(6, st.length); i++) System.out.println("       at " + st[i]);
            }
        }
        System.out.println(ok + " ok, " + ko + " falliti");
        if (ko > 0) System.exit(1);
    }
}
