import java.lang.ref.ReferenceQueue;
import java.lang.ref.WeakReference;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.IntSupplier;

/**
 * Round 2 program for the Windows LLVM backend: exceptions across frames, GC with live
 * references in compiled frames, threads. One "OK <check>" line per check; expected.txt
 * lists them all. A failing check prints "FAIL <check>" and the process exits 1.
 *
 * The StackOverflowError check lives in its own program, tests/programs/overflow, because the
 * LLVM backend segfaults on it (see that program's comment): here it would hide the checks
 * after it.
 */
public class Stress {
    static final class Boom extends Exception {
        final int depth;
        Boom(int depth) { super("boom at " + depth); this.depth = depth; }
    }
    static final class Wrapped extends RuntimeException {
        Wrapped(Throwable cause) { super("wrapped", cause); }
    }

    static volatile int sink;          // defeats constant folding; always 0
    static int finallyCount;
    static int failures;
    static final StringBuilder order = new StringBuilder();

    static void check(boolean ok, String name) {
        System.out.println((ok ? "OK " : "FAIL ") + name);
        if (!ok) failures++;
    }

    static int countFrames(Throwable t, String method) {
        int n = 0;
        for (StackTraceElement e : t.getStackTrace()) if (method.equals(e.getMethodName())) n++;
        return n;
    }

    // ---- exceptions ----------------------------------------------------------------

    static int deep(int n) throws Boom {
        if (n == 0) throw new Boom(n);
        try {
            return deep(n - 1) + 1;
        } finally {
            finallyCount++;
        }
    }

    static void throwCatchDeep() {
        finallyCount = 0;
        int frames = -1;
        boolean caught = false;
        try {
            deep(60);
        } catch (Boom b) {
            caught = b.depth == 0;
            frames = countFrames(b, "deep");
        }
        System.out.println("deep frames in trace: " + frames);
        check(caught && finallyCount == 60 && frames >= 60, "throw-catch-deep");
    }

    static void implicitExceptions() {
        int hits = 0;
        try { Object o = sink == 1 ? "x" : null; o.hashCode(); } catch (NullPointerException e) { hits++; }
        try { int[] a = new int[3]; a[sink + 5] = 1; } catch (ArrayIndexOutOfBoundsException e) { hits++; }
        try { int x = 10 / sink; sink = x; } catch (ArithmeticException e) { hits++; }
        try { Object o = sink == 0 ? "s" : Integer.valueOf(1); Integer i = (Integer) o; sink = i; } catch (ClassCastException e) { hits++; }
        try { Object[] a = sink == 0 ? new String[1] : new Object[1]; a[0] = Integer.valueOf(1); } catch (ArrayStoreException e) { hits++; }
        try { int[] a = new int[sink - 1]; sink = a.length; } catch (NegativeArraySizeException e) { hits++; }
        check(hits == 6, "implicit-exceptions");
    }

    static void rethrowWrap() {
        IntSupplier s = () -> {
            try {
                return deep(3);
            } catch (Boom b) {
                throw new Wrapped(b);
            }
        };
        boolean ok = false;
        try {
            sink = s.getAsInt();
        } catch (Wrapped w) {
            ok = w.getCause() instanceof Boom && ((Boom) w.getCause()).depth == 0;
        }
        check(ok, "rethrow-wrap");
    }

    static void f3() throws Boom { try { deep(1); } finally { order.append("f3,"); } }
    static void f2() throws Boom { try { f3(); } finally { order.append("f2,"); } }
    static void f1() throws Boom { try { f2(); } finally { order.append("f1,"); } }

    static void finallyOrder() {
        order.setLength(0);
        try {
            f1();
        } catch (Boom b) {
            order.append("catch");
        }
        check("f3,f2,f1,catch".contentEquals(order), "finally-order");
    }

    // ---- GC ------------------------------------------------------------------------

    static long gcStorm() {
        long sum = 0;
        for (int i = 0; i < 512; i++) {
            byte[] garbage = new byte[1 << 20];
            garbage[i] = (byte) i;
            sum += garbage[i];
        }
        System.gc();
        return sum;
    }

    /** Holds a reference live across a call that runs the GC, at every recursion level. */
    static long holdAndGc(int n) {
        byte[] mine = new byte[1024];
        for (int i = 0; i < mine.length; i++) mine[i] = (byte) (n + i);
        long below = n == 0 ? gcStorm() : holdAndGc(n - 1);
        for (int i = 0; i < mine.length; i++) {
            if (mine[i] != (byte) (n + i)) throw new IllegalStateException("corrupted level " + n + " at " + i);
        }
        return below + mine[7] - (byte) (n + 7);
    }

    static void gcLiveFrames() {
        boolean ok = false;
        try {
            long r = holdAndGc(40);
            ok = r == gcStormSum();
        } catch (IllegalStateException e) {
            System.out.println(e.getMessage());
        }
        check(ok, "gc-live-frames");
    }

    static long gcStormSum() {
        long sum = 0;
        for (int i = 0; i < 512; i++) sum += (byte) i;
        return sum;
    }

    static void gcWeakRef() {
        ReferenceQueue<Object> q = new ReferenceQueue<>();
        WeakReference<Object> w = new WeakReference<>(new byte[1 << 20], q);
        boolean cleared = false;
        for (int i = 0; i < 20 && !cleared; i++) {
            gcStorm();
            cleared = w.get() == null;
        }
        boolean enqueued = false;
        try {
            enqueued = q.remove(10_000) == w;
        } catch (InterruptedException e) {
            // fall through
        }
        check(cleared && enqueued, "gc-weakref");
    }

    static void gcPressure() {
        List<byte[]> window = new ArrayList<>();
        List<int[]> survivors = new ArrayList<>();
        long checksum = 0;
        for (int i = 0; i < 1024; i++) {
            byte[] b = new byte[1 << 20];
            b[0] = (byte) i;
            window.add(b);
            if (window.size() > 32) window.remove(0);
            if (i % 4 == 0) survivors.add(new int[] {i, i + 1, i + 2, i + 3});
        }
        for (byte[] b : window) checksum += b[0];
        long survivorSum = 0;
        for (int[] s : survivors) survivorSum += s[0] + s[1] + s[2] + s[3];
        long expectedWindow = 0;
        for (int i = 1024 - 32; i < 1024; i++) expectedWindow += (byte) i;
        long expectedSurvivors = 0;
        for (int i = 0; i < 1024; i += 4) expectedSurvivors += 4L * i + 6;
        check(checksum == expectedWindow && survivorSum == expectedSurvivors && survivors.size() == 256, "gc-pressure");
    }

    // ---- threads -------------------------------------------------------------------

    static void threadsBasic() throws InterruptedException {
        final int threads = 8, rounds = 2000;
        final Object lock = new Object();
        final int[] counter = {0};
        final AtomicLong atomic = new AtomicLong();
        final AtomicInteger caught = new AtomicInteger();
        final CountDownLatch start = new CountDownLatch(1);
        Thread[] ts = new Thread[threads];
        for (int t = 0; t < threads; t++) {
            ts[t] = new Thread(() -> {
                try {
                    start.await();
                } catch (InterruptedException e) {
                    return;
                }
                for (int i = 0; i < rounds; i++) {
                    int[] junk = new int[256];
                    junk[i % 256] = i;
                    try {
                        deep(5);
                    } catch (Boom b) {
                        if (b.depth == 0) caught.incrementAndGet();
                    }
                    atomic.addAndGet(junk[i % 256]);
                    synchronized (lock) {
                        counter[0]++;
                    }
                }
            }, "worker-" + t);
            ts[t].start();
        }
        start.countDown();
        for (Thread t : ts) t.join();
        long expectedAtomic = (long) threads * (rounds - 1) * rounds / 2;
        check(counter[0] == threads * rounds && atomic.get() == expectedAtomic && caught.get() == threads * rounds, "threads-basic");
    }

    static void threadsGc() throws InterruptedException {
        final int threads = 4;
        final AtomicInteger bad = new AtomicInteger();
        final CountDownLatch done = new CountDownLatch(threads);
        for (int t = 0; t < threads; t++) {
            new Thread(() -> {
                try {
                    for (int i = 0; i < 3; i++) {
                        if (holdAndGc(20) != gcStormSum()) bad.incrementAndGet();
                    }
                } catch (Throwable e) {
                    bad.incrementAndGet();
                    System.out.println("threads-gc worker failed: " + e);
                } finally {
                    done.countDown();
                }
            }, "gc-worker-" + t).start();
        }
        for (int i = 0; i < 5; i++) {
            System.gc();
            Thread.sleep(20);
        }
        done.await();
        check(bad.get() == 0, "threads-gc");
    }

    static void threadsWaitNotify() throws InterruptedException {
        final ArrayDeque<Integer> queue = new ArrayDeque<>();
        final int items = 1000;
        final long[] consumed = {0};
        Thread producer = new Thread(() -> {
            for (int i = 1; i <= items; i++) {
                synchronized (queue) {
                    while (queue.size() >= 8) {
                        try { queue.wait(); } catch (InterruptedException e) { return; }
                    }
                    queue.add(i);
                    queue.notifyAll();
                }
            }
        }, "producer");
        Thread consumer = new Thread(() -> {
            for (int i = 1; i <= items; i++) {
                synchronized (queue) {
                    while (queue.isEmpty()) {
                        try { queue.wait(); } catch (InterruptedException e) { return; }
                    }
                    consumed[0] += queue.poll();
                    queue.notifyAll();
                }
            }
        }, "consumer");
        producer.start();
        consumer.start();
        producer.join();
        consumer.join();
        check(consumed[0] == (long) items * (items + 1) / 2, "threads-wait-notify");
    }

    static void threadExceptions() throws InterruptedException {
        final int[] framesInThread = {-1};
        final Throwable[] uncaught = {null};
        Thread deepThrower = new Thread(() -> {
            try {
                deep(40);
            } catch (Boom b) {
                framesInThread[0] = countFrames(b, "deep");
            }
        }, "deep-thrower");
        Thread uncaughtThrower = new Thread(() -> { throw new IllegalStateException("uncaught on purpose"); }, "uncaught-thrower");
        uncaughtThrower.setUncaughtExceptionHandler((t, e) -> uncaught[0] = e);
        deepThrower.start();
        uncaughtThrower.start();
        deepThrower.join();
        uncaughtThrower.join();
        Thread sleeper = new Thread(() -> {
            try {
                Thread.sleep(60_000);
                framesInThread[0] = -2;
            } catch (InterruptedException e) {
                // expected
            }
        }, "sleeper");
        sleeper.start();
        Thread.sleep(50);
        sleeper.interrupt();
        sleeper.join(10_000);
        check(framesInThread[0] >= 40 && uncaught[0] instanceof IllegalStateException && !sleeper.isAlive(), "thread-exceptions");
    }

    public static void main(String[] args) throws InterruptedException {
        System.out.println("Stress on " + System.getProperty("os.name") + ", " + Runtime.getRuntime().availableProcessors() + " cpus");
        throwCatchDeep();
        implicitExceptions();
        rethrowWrap();
        finallyOrder();
        gcLiveFrames();
        gcWeakRef();
        gcPressure();
        threadsBasic();
        threadsGc();
        threadsWaitNotify();
        threadExceptions();
        if (failures == 0) {
            System.out.println("STRESS OK");
        } else {
            System.out.println("STRESS FAILED " + failures);
            System.exit(1);
        }
    }
}
