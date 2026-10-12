import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * Compiles each Lua file given with Project Zomboid's own Lua compiler (Kahlua, from projectzomboid.jar on the
 * class path) and prints OK or the compile error. Nothing is run. Used by tests/test_lua.py.
 */
public class LuaCheck {
    public static void main(String[] args) throws Exception {
        Class<?> compiler = Class.forName("se.krka.kahlua.luaj.compiler.LuaCompiler");
        Class<?> table = Class.forName("se.krka.kahlua.vm.KahluaTable");
        Method load = compiler.getMethod("loadstring", String.class, String.class, table);
        int bad = 0;
        for (String f : args) {
            String src = new String(Files.readAllBytes(Paths.get(f)), StandardCharsets.UTF_8);
            try {
                load.invoke(null, src, Paths.get(f).getFileName().toString(), null);
                System.out.println("OK   " + f);
            } catch (InvocationTargetException e) {
                bad++;
                System.out.println("FAIL " + f + ": " + e.getCause());
            }
        }
        System.exit(bad == 0 ? 0 : 1);
    }
}
