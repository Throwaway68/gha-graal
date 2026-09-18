import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

import org.graalvm.nativeimage.CurrentIsolate;
import org.graalvm.nativeimage.ImageInfo;
import org.graalvm.nativeimage.IsolateThread;
import org.graalvm.nativeimage.c.function.CEntryPoint;
import org.graalvm.nativeimage.c.function.CEntryPointLiteral;
import org.graalvm.nativeimage.c.function.CFunctionPointer;

/**
 * Round 4 program: JNI in both directions against a shared library built by the bundled clang,
 * exceptions across the JNI boundary, a @CEntryPoint called through a function pointer, and a
 * spread of ordinary library code. One "OK <check>" line per check; expected.txt lists them all.
 * The library path arrives as -Dcomplex.lib=<path> from dev-run.sh.
 */
public class Complex {
    static int failures;

    static void check(boolean ok, String name) {
        System.out.println((ok ? "OK " : "FAIL ") + name);
        if (!ok) failures++;
    }

    // ---- JNI natives (complex.c) ----
    static native int add(int a, int b);
    static native String greet(String name);
    static native long sumArray(int[] arr);
    static native int upcallSquare(int n);
    static native int upcallThrowing(String msg);
    static native void nativeThrow(String msg);
    static native String upcallDescribe(String in);
    static native long callEntryPoint(long fn, long thread);

    // ---- upcall targets (registered in jni-config.json) ----
    static int square(int n) { return n * n; }
    static void throwing(String msg) { throw new IllegalStateException(msg); }
    static String describe(String in) { return "[" + in.toUpperCase() + ":" + in.length() + "]"; }

    // ---- entry point called through a function pointer from C ----
    @CEntryPoint
    static long entry(IsolateThread thread, long a, long b, long c, long d, long e) {
        return a + 10 * b + 100 * c + 1000 * d + 10000 * e;
    }
    // The literal itself is built eagerly (the image generator has to see it in a static final
    // field), but getFunctionPointer() is image-runtime-only - on HotSpot it throws
    // "Cannot invoke method during native image generation", which in a class initializer would
    // take the whole program down before the first check.
    static final CEntryPointLiteral<CFunctionPointer> ENTRY = CEntryPointLiteral.create(Complex.class, "entry",
                    IsolateThread.class, long.class, long.class, long.class, long.class, long.class);

    sealed interface Shape permits Circle, Rect {}
    record Circle(double r) implements Shape {}
    record Rect(double w, double h) implements Shape {}

    static double area(Shape s) {
        return switch (s) {
            case Circle c -> Math.PI * c.r() * c.r();
            case Rect r -> r.w() * r.h();
        };
    }

    public static void main(String[] args) throws Exception {
        System.out.println("Complex on " + System.getProperty("os.name") + ", image=" + ImageInfo.inImageRuntimeCode());
        String lib = System.getProperty("complex.lib");
        System.load(lib);

        // JNI downcalls
        check(add(40, 2) == 42, "jni-add");
        check("hello, world, from C".equals(greet("world")), "jni-string");
        check(sumArray(IntStream.rangeClosed(1, 1000).toArray()) == 500500L, "jni-array");

        // JNI upcalls
        check(upcallSquare(12) == 144, "jni-upcall");
        check("[ABC:3]".equals(upcallDescribe("abc")), "jni-upcall-string");
        check(upcallThrowing("boom from java") == 1, "jni-upcall-throw");

        // exception thrown by native code, caught in Java
        boolean caught = false;
        try {
            nativeThrow("from C");
        } catch (RuntimeException e) {
            caught = "from C".equals(e.getMessage());
        }
        check(caught, "jni-native-throw");

        // entry point through a function pointer: C calls the image, six arguments incl. the thread
        long expected = 1 + 20 + 300 + 4000 + 50000;
        if (ImageInfo.inImageRuntimeCode()) {
            long r = callEntryPoint(ENTRY.getFunctionPointer().rawValue(), CurrentIsolate.getCurrentThread().rawValue());
            check(r == expected, "centrypoint-pointer");
        } else {
            check(true, "centrypoint-pointer"); // HotSpot cannot call an entry point; the check is image-only
        }

        // JNI from several threads at once, each with upcalls and a caught native exception
        final int threads = 6;
        final CountDownLatch done = new CountDownLatch(threads);
        final Map<String, Integer> results = new ConcurrentHashMap<>();
        for (int t = 0; t < threads; t++) {
            final int id = t;
            new Thread(() -> {
                int acc = 0;
                for (int i = 0; i < 200; i++) {
                    acc += add(i, id) + upcallSquare(i % 10);
                    try { nativeThrow("t" + id); } catch (RuntimeException e) { acc += e.getMessage().length(); }
                }
                results.put("t" + id, acc);
                done.countDown();
            }, "jni-" + t).start();
        }
        done.await();
        int sumUp = 0;
        for (int i = 0; i < 200; i++) sumUp += (i % 10) * (i % 10);
        boolean threadsOk = results.size() == threads;
        for (int t = 0; t < threads; t++) {
            int exp = 199 * 200 / 2 + 200 * t + sumUp + 200 * ("t" + t).length();
            threadsOk &= results.getOrDefault("t" + t, -1) == exp;
        }
        check(threadsOk, "jni-threads");

        // ordinary library code
        List<Shape> shapes = List.of(new Circle(1), new Rect(2, 3), new Circle(0.5));
        double total = shapes.stream().mapToDouble(Complex::area).sum();
        check(Math.abs(total - (Math.PI * 1.25 + 6)) < 1e-9, "records-sealed-switch");

        Pattern p = Pattern.compile("(\\w+)@(\\w+)\\.com");
        Matcher m = p.matcher("mail alice@example.com and bob@test.com now");
        List<String> users = new ArrayList<>();
        while (m.find()) users.add(m.group(1) + "/" + m.group(2));
        check(users.equals(List.of("alice/example", "bob/test")), "regex");

        String joined = IntStream.range(0, 20).parallel().filter(i -> i % 3 == 0).boxed()
                        .map(i -> String.format("%02d", i)).collect(Collectors.joining(","));
        check("00,03,06,09,12,15,18".equals(joined), "streams-format");

        BigInteger f = BigInteger.ONE;
        for (int i = 2; i <= 50; i++) f = f.multiply(BigInteger.valueOf(i));
        // 97 is prime and larger than 50, so it never divides 50!; 65 is the actual residue.
        check(f.toString().length() == 65 && f.mod(BigInteger.valueOf(97)).intValue() == 65, "bigint");

        Path tmp = Files.createTempFile("complex", ".txt");
        Files.writeString(tmp, "line1\nline2\nline3\n", StandardCharsets.UTF_8);
        List<String> lines = Files.readAllLines(tmp);
        Files.delete(tmp);
        check(lines.size() == 3 && lines.get(2).equals("line3") && !Files.exists(tmp), "file-io");

        var method = Complex.class.getDeclaredMethod("square", int.class);
        check(((Integer) method.invoke(null, 9)) == 81, "reflection");

        Map<Boolean, Long> parts = IntStream.rangeClosed(1, 100).boxed()
                        .collect(Collectors.partitioningBy(i -> i % 2 == 0, Collectors.counting()));
        check(parts.get(true) == 50 && parts.get(false) == 50, "collectors");

        if (failures == 0) {
            System.out.println("COMPLEX OK");
        } else {
            System.out.println("COMPLEX FAILED " + failures);
            System.exit(1);
        }
    }
}
