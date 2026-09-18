# Windows LLVM Backend, Round 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A complex program built with `native-image --tool:llvm-backend` runs on windows-amd64 (and darwin-aarch64, linux-amd64): it loads a shared library built from C by the bundled clang, calls into it through JNI, the library calls back into the image through JNI upcalls and through a `@CEntryPoint` function pointer, exceptions cross the JNI boundary in both directions, and the rest of the program exercises ordinary library code (collections, streams, records, regex, formatting, reflection on itself, file IO, threads).

**Architecture:** `dev-run.sh` learns two optional program-directory features: C sources compiled into a shared library by the bundled clang (`<graalvm>/lib/llvm/bin/clang`), and a `META-INF/native-image/` directory copied next to the classes so JNI/reflection configuration travels with the program. The program `tests/programs/complex` is verified on HotSpot locally (this Mac has a C compiler and a JDK), then on linux-amd64 as the reference, then darwin-aarch64 and windows-amd64; whatever breaks on Windows is fixed on the graal branch through the ssh session. Round ends with release `graalvm-round4-win-llvm` whose smoke test runs `stress` and `complex` on every platform.

**Tech Stack:** as rounds 1-3. JNI (`jni.h` from `<graalvm>/include`, `jni_md.h` from `<graalvm>/include/{win32,linux,darwin}`), `org.graalvm.nativeimage` API (`@CEntryPoint`, `CEntryPointLiteral`, `CurrentIsolate`) which the GraalVM JDK exposes as a module.

**Spec:** `docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md` (Goal item 4).

## Global Constraints

- Git identity in every checkout under the Throwaway68 account: `Throwaway68 <carpettohd@gmail.com>`, set locally; never any other, never decided by you.
- The GitHub token is passed in the task prompt; only `export GH_TOKEN=...` in shell commands and the credential helper `git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push ...`. Never in a file, workflow, commit, log, journal, report, or ssh session.
- gha-graal work on a branch per task (`round4-<task>`), the controller merges to `main`. graal work on `graal/25.3.4.1-win-llvm` in the worktree named in the prompt, pushed to the `fork` remote; round 3 works on the same branch concurrently: `git pull --rebase fork graal/25.3.4.1-win-llvm` before pushing, never force-push.
- Every task ends with commits and journal entries in `docs/journal/windows-llvm-backend.md` (dated, naming run or commit; Findings per root cause, Dead ends per abandoned hypothesis, Milestones for green runs; hypotheses labelled).
- Dispatch: `gh workflow run graalvm-dev.yml --repo Throwaway68/gha-graal --ref <branch> -f platform=... -f program=complex [-f debug_ssh=true]`. No short sleep-polling loops.
- `.sync-manifest` updated; `python3 -m pytest tests -q` and `bash tests/test_dev_run.sh` stay green.

## Reference facts (verified 2026-09-18; do not re-derive)

- The LLVM backend has no JNI-specific code paths beyond the transition wrapper `__llvm_jni_wrapper_*` (`LLVMGenerator.createJNIWrapper`, ~:1376-1443: stores the caller's return address into the frame anchor, flips the thread status, saves/restores the reserved registers around the native call) and the JNI trampoline (`createJNITrampoline`, ~:1474-1496). JNI upcall targets (`JNIFunctions`, `@CEntryPoint`) compile like any entry point.
- Continuations are disabled under the LLVM backend (`ContinuationsFeature.java:89`), so virtual threads run on platform threads; not a test target.
- `@CEntryPoint` symbols: on Linux/macOS exports go through a linker symbol list built from `getImageSymbols(true)` (works with the backend; `cinterfacetutorial` is green on linux under the backend, round 3 run 35351646189). On Windows exports need the *defining* object to carry a `/EXPORT:` directive and the LLVM backend emits none (`LLVMNativeImageCodeCache.defineMethodSymbol` only creates undefined symbols in the image object; nothing sets dllexport in the IR). Consequence for this round: native code calls back into the image through a **function pointer** (`CEntryPointLiteral`) and through JNI upcalls, which need no export; a `@CEntryPoint(name=..)` resolved by `GetProcAddress` is a stretch check, expected to fail on Windows until the export path exists (round 3 may hit the same through `cinterfacetutorial --shared` on Windows).
- `jni.h`: `<graalvm>/include/jni.h`; `jni_md.h`: `<graalvm>/include/win32/jni_md.h` (Windows), `include/linux/jni_md.h`, `include/darwin/jni_md.h`. `JNIEXPORT` expands to `__declspec(dllexport)` on Windows.
- Bundle `lib/llvm/bin` has `clang`, `clang-cl`, `clang++`, `lld`, `lld-link`, `ld64.lld` on all three platforms. In CI the Windows job runs under `ilammy/msvc-dev-cmd`, so `INCLUDE`/`LIB` are set and `clang --target=x86_64-pc-windows-msvc` finds the MSVC/UCRT headers and libraries; `-fuse-ld=lld` makes it link with the bundled `lld-link`. Unknown until tried: whether clang's default Windows CRT choice matches `/MD` (it does by default: clang targets the dynamic UCRT unless `-static`), and whether `lld-link` needs `-Wl,/DEF` for JNI exports (it should not: `JNIEXPORT` marks them).
- JNI access from native to Java (`FindClass`, `GetStaticMethodID`, `CallStaticIntMethod`, `ThrowNew`, `NewStringUTF`) requires the classes/methods/fields to be registered for JNI: a `jni-config.json` under `META-INF/native-image/<group>/<artifact>/` on the classpath is picked up automatically by native-image. Native methods declared in Java (`static native`) need no configuration; they are linked lazily by symbol name (`Java_<class>_<method>`) from libraries loaded with `System.load`.
- `dev-run.sh` today: `javac -d $W/classes $P/*.java`, main class = capitalised directory name, `expected.txt` lines must appear in stdout, `DEV-RUN OK`. Diagnostics in `win_diag`.
- Known LLVM-backend bugs (all platforms): catching `StackOverflowError` crashes; the unreproduced threads+catch crash; `hellomodule`'s `-H:+RuntimeClassLoading` variant needs multi-value returns the backend lacks (round 3). Avoid those in `complex`.
- Local Mac: `cc` (Apple clang) and GraalVM CE 25 JDK (`java`, `javac`, `<java.home>/include/{jni.h,darwin/jni_md.h}`) are available, so the whole program including its C library can be verified on HotSpot locally before any CI run.

## File structure

- `scripts/graalvm/dev-run.sh` (modify): after `javac`, if `$P/META-INF` exists copy it into `$W/classes/`; if `$P/*.c` exist, build `$W/<name>.{dll,so,dylib}` with the bundled clang and pass `-D<name>.lib=<abs path>` to the program (runtime system property); a `javac.flags` file in `$P` (one line) is appended to the javac command.
- `tests/test_dev_run.sh` (modify): a case with a fake program dir holding a `.c` file, checking the clang command line is built per platform (the test stubs `clang` with a script that records its arguments, as the existing test stubs `javac`/`native-image`).
- `tests/programs/complex/Complex.java`, `complex.c`, `expected.txt`, `javac.flags`, `META-INF/native-image/gha-graal/complex/jni-config.json` (new).
- `scripts/graalvm/smoke-stress.sh` (modify, Task 3): also runs `complex`.
- graal branch: fixes; `docs/journal/windows-llvm-backend.md`, `README.md`, `.sync-manifest`.

---

### Task 1: `dev-run.sh` native-library support and the `complex` program, green on HotSpot and on linux-amd64

**Files:**
- Modify: `scripts/graalvm/dev-run.sh`, `tests/test_dev_run.sh`
- Create: `tests/programs/complex/{Complex.java,complex.c,expected.txt,javac.flags,META-INF/native-image/gha-graal/complex/jni-config.json}`
- Modify: `docs/journal/windows-llvm-backend.md`, `.sync-manifest`, `README.md` (dev-run contract paragraph)

**Interfaces:**
- Produces: `dev-run.sh` contract extension: `<program-dir>/*.c` → shared library `$W/<name>.<ext>` built with `$H/lib/llvm/bin/clang`; program receives `-D<name>.lib=<path>`; `<program-dir>/META-INF` copied to the classpath; `<program-dir>/javac.flags` appended to javac. `complex` for Tasks 2 and 3.

- [ ] **Step 1: dev-run.sh.** After the `javac` line:

```bash
[ -f "$P/javac.flags" ] && JFLAGS=$(cat "$P/javac.flags") || JFLAGS=""
echo "== javac"; "$JAVAC" $JFLAGS -d "$W/classes" "$P"/*.java
[ -d "$P/META-INF" ] && cp -R "$P/META-INF" "$W/classes/"
# Native library: every *.c in the program dir compiled by the bundled clang into one shared
# library named after the program; the program finds it through -D<name>.lib=<path>.
libprop=()
if ls "$P"/*.c >/dev/null 2>&1; then
  echo "== clang (bundled)"
  CLANG=$(exe "$H/lib/llvm/bin" clang)
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) lib="$W/$name.dll";   cflags=(--target=x86_64-pc-windows-msvc -fuse-ld=lld -shared "-I$H/include" "-I$H/include/win32");;
    Darwin)               lib="$W/lib$name.dylib"; cflags=(-dynamiclib "-I$H/include" "-I$H/include/darwin");;
    *)                    lib="$W/lib$name.so";  cflags=(-shared -fPIC "-I$H/include" "-I$H/include/linux");;
  esac
  "$CLANG" -O1 "${cflags[@]}" "$P"/*.c -o "$lib"
  libprop=("-D$name.lib=$lib")
fi
```

and run the program as `"$app" "${libprop[@]}" > "$W/stdout.txt" 2> "$W/stderr.txt"`. Note `javac.flags` is word-split on purpose (`$JFLAGS` unquoted). Keep `set -u` happy with the empty-array idiom (`${libprop[@]+"${libprop[@]}"}` if the runner's bash is older than 4.4; check `bash --version` on the Windows runner is 5.x - it is Git bash 5.2 - and macOS's is 3.2! macOS `/bin/bash` is 3.2, where `"${arr[@]}"` on an empty array fails under `set -u`; use the `+` idiom everywhere).

- [ ] **Step 2: tests/test_dev_run.sh** gains a case: program dir with `X.java`, `x.c`, `expected.txt`; the stub `clang` script records `$@` to a file; assert the recorded line contains `-shared` or `-dynamiclib` and `-I<home>/include`, and that the recorded `native-image`/program run received `-Dx.lib=`. Run: `bash tests/test_dev_run.sh` → PASS.

- [ ] **Step 3: the program.**

`tests/programs/complex/javac.flags`:
```
--add-modules org.graalvm.nativeimage
```

`tests/programs/complex/META-INF/native-image/gha-graal/complex/jni-config.json`:
```json
[
  { "name": "Complex",
    "methods": [
      { "name": "square", "parameterTypes": ["int"] },
      { "name": "throwing", "parameterTypes": ["java.lang.String"] },
      { "name": "describe", "parameterTypes": ["java.lang.String"] }
    ] },
  { "name": "java.lang.IllegalStateException", "methods": [ { "name": "<init>", "parameterTypes": ["java.lang.String"] } ] },
  { "name": "java.lang.RuntimeException" }
]
```

`tests/programs/complex/complex.c`:
```c
#include <jni.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>

/* Java -> native: arithmetic, strings, arrays. */
JNIEXPORT jint JNICALL Java_Complex_add(JNIEnv *env, jclass cls, jint a, jint b) {
    (void) env; (void) cls;
    return a + b;
}

JNIEXPORT jstring JNICALL Java_Complex_greet(JNIEnv *env, jclass cls, jstring name) {
    (void) cls;
    const char *n = (*env)->GetStringUTFChars(env, name, NULL);
    char buf[128];
    snprintf(buf, sizeof buf, "hello, %s, from C", n);
    (*env)->ReleaseStringUTFChars(env, name, n);
    return (*env)->NewStringUTF(env, buf);
}

JNIEXPORT jlong JNICALL Java_Complex_sumArray(JNIEnv *env, jclass cls, jintArray arr) {
    (void) cls;
    jsize len = (*env)->GetArrayLength(env, arr);
    jint *e = (*env)->GetIntArrayElements(env, arr, NULL);
    jlong s = 0;
    for (jsize i = 0; i < len; i++) s += e[i];
    (*env)->ReleaseIntArrayElements(env, arr, e, JNI_ABORT);
    return s;
}

/* native -> Java: an upcall to a static method, six arguments deep on the C side so that the
   Win64 home space matters. */
JNIEXPORT jint JNICALL Java_Complex_upcallSquare(JNIEnv *env, jclass cls, jint n) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "square", "(I)I");
    if (m == NULL) return -1;
    return (*env)->CallStaticIntMethod(env, cls, m, n);
}

/* native -> Java where the Java side throws: the exception must be pending when the upcall
   returns, and the native code must be able to see and clear it, then rethrow a different one. */
JNIEXPORT jint JNICALL Java_Complex_upcallThrowing(JNIEnv *env, jclass cls, jstring msg) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "throwing", "(Ljava/lang/String;)V");
    if (m == NULL) return -1;
    (*env)->CallStaticVoidMethod(env, cls, m, msg);
    if (!(*env)->ExceptionCheck(env)) return -2;
    jthrowable t = (*env)->ExceptionOccurred(env);
    (*env)->ExceptionClear(env);
    jclass ise = (*env)->FindClass(env, "java/lang/IllegalStateException");
    if (ise == NULL || !(*env)->IsInstanceOf(env, t, ise)) return -3;
    return 1;
}

/* native throws: ThrowNew and return; Java must catch it after the call. */
JNIEXPORT void JNICALL Java_Complex_nativeThrow(JNIEnv *env, jclass cls, jstring msg) {
    (void) cls;
    const char *m = (*env)->GetStringUTFChars(env, msg, NULL);
    jclass rte = (*env)->FindClass(env, "java/lang/RuntimeException");
    (*env)->ThrowNew(env, rte, m);
    (*env)->ReleaseStringUTFChars(env, msg, m);
}

/* native -> Java through an upcall that returns a string built by Java. */
JNIEXPORT jstring JNICALL Java_Complex_upcallDescribe(JNIEnv *env, jclass cls, jstring in) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "describe", "(Ljava/lang/String;)Ljava/lang/String;");
    if (m == NULL) return NULL;
    return (jstring) (*env)->CallStaticObjectMethod(env, cls, m, in);
}

/* native -> image through a @CEntryPoint function pointer: no JNI, no symbol export needed. */
typedef int64_t (*entry_fn)(void *isolate_thread, int64_t a, int64_t b, int64_t c, int64_t d, int64_t e);
JNIEXPORT jlong JNICALL Java_Complex_callEntryPoint(JNIEnv *env, jclass cls, jlong fn, jlong thread) {
    (void) env; (void) cls;
    entry_fn f = (entry_fn) (intptr_t) fn;
    return f((void *) (intptr_t) thread, 1, 2, 3, 4, 5);
}
```

`tests/programs/complex/Complex.java`:
```java
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
    static final CFunctionPointer ENTRY = CEntryPointLiteral.create(Complex.class, "entry",
                    IsolateThread.class, long.class, long.class, long.class, long.class, long.class).getFunctionPointer();

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
            long r = callEntryPoint(ENTRY.rawValue(), CurrentIsolate.getCurrentThread().rawValue());
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
        check(f.toString().length() == 65 && f.mod(BigInteger.valueOf(97)).intValue() == 0, "bigint");

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
```

`tests/programs/complex/expected.txt`:
```
OK jni-add
OK jni-string
OK jni-array
OK jni-upcall
OK jni-upcall-string
OK jni-upcall-throw
OK jni-native-throw
OK centrypoint-pointer
OK jni-threads
OK records-sealed-switch
OK regex
OK streams-format
OK bigint
OK file-io
OK reflection
OK collectors
COMPLEX OK
```

Notes for the implementer: `Complex.class.getDeclaredMethod("square", int.class)` with constant arguments is folded by the analysis and needs no reflect-config; if the image build reports it missing, add a `reflect-config.json` next to the jni-config. The `entry` method takes six arguments on purpose (the Win64 home-space bug of round 1 showed with five or more). The jni-config `IllegalStateException` entry with `<init>` is needed so `IsInstanceOf`/`FindClass` work for it; `RuntimeException` for `ThrowNew`.

- [ ] **Step 4: HotSpot run on the Mac.** Build the library with the system compiler (`cc -dynamiclib -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/darwin" complex.c -o libcomplex.dylib`), compile with `javac --add-modules org.graalvm.nativeimage -d classes Complex.java` (the local JDK is GraalVM CE 25, which has the module; if not, `-cp <graalvm>/lib/svm/builder/svm.jar` is not the answer - find the `nativeimage` jar under the local JDK's `lib/` and report), run `java -Dcomplex.lib=$PWD/libcomplex.dylib -cp classes Complex`. Expected: all 17 lines, exit 0. Fix the program until it holds.

- [ ] **Step 5: linux-amd64 reference run** on branch `round4-program`: `gh workflow run graalvm-dev.yml --ref round4-program -f platform=linux-amd64 -f program=complex`. Expected `DEV-RUN OK`. If the image build fails on configuration (JNI/reflection), fix the config files; if a check fails at run time on the Linux backend, that is a backend finding: journal it, and only if it is clearly the program's fault fix the program. Then dispatch darwin-aarch64 with the same program (the darwin backend is green for `stress`); report its outcome (fix only program/config problems; a darwin backend failure is journaled for Task 2).

- [ ] **Step 6: journal, README, manifest, commit, push.** Journal Findings: the linux run URL, what `complex` covers, any config needed; Decisions: function-pointer callback instead of an exported symbol on Windows, with the reason (the export gap). README: the dev-run contract additions.

---

### Task 2: `complex` green on windows-amd64 (and darwin-aarch64)

**Files:**
- Modify: graal branch (fixes), `docs/journal/windows-llvm-backend.md`, `.sync-manifest`; `scripts/graalvm/dev-run.sh` only if the Windows clang invocation needs adjusting (e.g. `clang-cl` or `-Wl,` flags).

**Interfaces:**
- Consumes: Task 1's program and dev-run extension (merged to main by the controller).
- Produces: green windows-amd64 and darwin-aarch64 runs of `complex` from `main` at the new graal head; linux-amd64 re-run as the no-regression check.

- [ ] **Step 1:** dispatch windows-amd64 `program=complex debug_ssh=true`; first failure is probably the clang/lld-link DLL build (headers, CRT, exports) - fix in dev-run.sh through the session; then the image build (JNI config, entry point literal); then runtime. Iterate as in round 2 Task 3 (incremental `mx build`, rerun dev-run). One journal Findings entry per root cause, Dead ends per abandoned hypothesis.
- [ ] **Step 2:** stretch, only after green: a `@CEntryPoint(name = "complex_exported")` resolved by `GetProcAddress`/`dlsym` from the C side - one extra native `callExported()` and a check `OK centrypoint-export` - to record whether Windows exports work under the backend; if not, journal the finding (the export gap) and keep the check out of `expected.txt` on Windows... no: keep the program identical on all platforms, so put the exported-symbol check in a separate program `tests/programs/export` (main `Export`) with its own expected.txt, and record its per-platform status in the journal.
- [ ] **Step 3:** clean runs from `main` at the final graal head: windows-amd64, darwin-aarch64, linux-amd64 with `program=complex`. Journal Milestones with the three URLs; manifest; commit on `round4-win`, push. Stop conditions: green on Windows; or three ssh sessions without green → DONE_WITH_CONCERNS.

---

### Task 3: release `graalvm-round4-win-llvm`, smoke runs `stress` and `complex`

**Files:**
- Modify: `scripts/graalvm/smoke-stress.sh` (also runs `complex`; rename is not needed), `README.md`, `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

- [ ] **Step 1:** `smoke-stress.sh` runs `dev-run.sh` for `stress` and then for `complex` (work dirs `$2/stress`, `$2/complex`). The release workflow's smoke step calls it already.
- [ ] **Step 2:** dispatch `gh workflow run graalvm.yml --ref round4-release -f label=round4-win-llvm -f platforms=linux-amd64,windows-amd64,darwin-aarch64`; verify assets and that all three smoke logs show `STRESS OK`, `COMPLEX OK`, `SMOKE OK`. One re-dispatch allowed on an upload failure.
- [ ] **Step 3:** README (round 4 release, what `complex` covers, the export gap if still open), journal Milestones + open items (round 3 gate status from its own plan, the backend bugs list), manifest, commit, push.
