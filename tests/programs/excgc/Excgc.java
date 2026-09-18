import java.util.concurrent.atomic.AtomicInteger;

/**
 * Reduced, single-threaded reproducer for the second linux-amd64 LLVM backend crash (run
 * https://github.com/Throwaway68/gha-graal/actions/runs/35325689605), where `stress`'s
 * `threads-basic` died with the lambda's captured objects held at addresses a collection had
 * already emptied, in the code after `catch (Boom)`. Same shape without the threads: two
 * references live across an invoke whose exception edge is taken, in a loop that allocates enough
 * to keep the GC running. Its own program so that `stress` can stay the green baseline.
 *
 * Not yet confirmed to reproduce the crash on the backend - no LLVM-backend run has been spent on
 * it.
 */
public class Excgc {
    static final class Boom extends Exception {
        final int depth;
        Boom(int depth) { super("boom at " + depth); this.depth = depth; }
    }

    static final int ROUNDS = 20_000;
    static final int JUNK = 4096;

    static int finallyCount;
    static int failures;

    static void check(boolean ok, String name) {
        System.out.println((ok ? "OK " : "FAIL ") + name);
        if (!ok) failures++;
    }

    static int deep(int n) throws Boom {
        if (n == 0) throw new Boom(n);
        try {
            return deep(n - 1) + 1;
        } finally {
            finallyCount++;
        }
    }

    /** `counter` and `box` are live across the throwing call, in a loop that keeps the GC busy. */
    static void churn(AtomicInteger counter, int[] box) {
        for (int i = 0; i < ROUNDS; i++) {
            int[] junk = new int[JUNK];
            junk[i % JUNK] = i;
            try {
                deep(5);
            } catch (Boom b) {
                counter.incrementAndGet();
            }
            box[0] += junk.length;
        }
    }

    public static void main(String[] args) {
        System.out.println("Excgc on " + System.getProperty("os.name"));
        AtomicInteger counter = new AtomicInteger();
        int[] box = new int[1];
        churn(counter, box);
        check(counter.get() == ROUNDS && box[0] == ROUNDS * JUNK, "exception-gc");
        if (failures == 0) {
            System.out.println("EXCGC OK");
        } else {
            System.out.println("EXCGC FAILED " + failures);
            System.exit(1);
        }
    }
}
