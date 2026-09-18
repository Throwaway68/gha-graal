import org.graalvm.nativeimage.CurrentIsolate;
import org.graalvm.nativeimage.ImageInfo;
import org.graalvm.nativeimage.IsolateThread;
import org.graalvm.nativeimage.c.function.CEntryPoint;

/**
 * Probe for one question `complex` deliberately avoids: can C reach an image's @CEntryPoint
 * through the *symbol* the annotation names, rather than through a function pointer? The C side
 * looks the symbol up in the running executable itself - GetProcAddress(GetModuleHandleA(NULL))
 * on Windows, dlsym(RTLD_DEFAULT) elsewhere - which is what a C host embedding an image does.
 * That path needs the image's export table (Windows) or dynamic symbol table (ELF/Mach-O) to
 * carry the entry point, so it tests the linker side of the LLVM backend, not the codegen side.
 * The library path arrives as -Dexport.lib=<path> from dev-run.sh.
 */
public class Export {
    static int failures;

    static void check(boolean ok, String name) {
        System.out.println((ok ? "OK " : "FAIL ") + name);
        if (!ok) failures++;
    }

    /** Resolves gha_export_add in the running executable and calls it with (thread, 40, 2). */
    static native long callExported(long thread);

    @CEntryPoint(name = "gha_export_add")
    static long exportedAdd(IsolateThread thread, long a, long b) {
        return a + b;
    }

    public static void main(String[] args) {
        System.out.println("Export on " + System.getProperty("os.name") + ", image=" + ImageInfo.inImageRuntimeCode());
        System.load(System.getProperty("export.lib"));
        if (ImageInfo.inImageRuntimeCode()) {
            // Negative results are the C side's diagnostics (symbol not found); it prints the
            // OS error to stderr before returning them.
            long r = callExported(CurrentIsolate.getCurrentThread().rawValue());
            if (r != 42) {
                System.out.println("callExported returned " + r);
            }
            check(r == 42, "centrypoint-export");
        } else {
            // A JVM has no image and no export table; the check exists only for an image, so on
            // HotSpot it passes unconditionally (as complex's centrypoint-pointer check does).
            check(true, "centrypoint-export");
        }

        if (failures == 0) {
            System.out.println("EXPORT OK");
        } else {
            System.out.println("EXPORT FAILED " + failures);
            System.exit(1);
        }
    }
}
