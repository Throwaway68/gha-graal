import java.util.concurrent.atomic.AtomicInteger;

/**
 * Reduced, single-threaded reproducer for the second linux-amd64 LLVM backend crash (run
 * https://github.com/Throwaway68/gha-graal/actions/runs/35325689605), where `stress`'s
 * `threads-basic` died with the lambda's captured objects at addresses above every mapped heap
 * chunk, in the code after `catch (Boom)`.
 *
 * The precondition is a collection that runs *while the throwing call is on the stack*, so that the
 * unwind edge is taken across it: `deep(0)` therefore allocates and, every GC_EVERY-th round, calls
 * System.gc() from the deepest frame before throwing. Three references are live across that invoke
 * and used after the catch - `counter`, `box` and the caller's `junk` - so a collection that fails
 * to relocate any of them is caught by the checked sums. Its own program so that `stress` can stay
 * the green baseline.
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
    static final int GC_EVERY = 64;     // 313 collections taken with deep(5) on the stack

    // `deep` is kept identical to stress's, finally block included, so this reproduces the shape
    // that crashed there rather than a simplified one; finallyCount is only what keeps it so.
    static int finallyCount;
    static int failures;
    static int round;
    static int[] gcSink;                // keeps the garbage below from being optimised away

    static void check(boolean ok, String name) {
        System.out.println((ok ? "OK " : "FAIL ") + name);
        if (!ok) failures++;
    }

    static int deep(int n) throws Boom {
        if (n == 0) {
            gcSink = new int[JUNK];
            if (round % GC_EVERY == 0) {
                System.gc();
            }
            throw new Boom(n);
        }
        try {
            return deep(n - 1) + 1;
        } finally {
            finallyCount++;
        }
    }

    /** `counter`, `box` and `junk` are all live across the throwing call and used after the catch. */
    static void churn(AtomicInteger counter, int[] box) {
        for (int i = 0; i < ROUNDS; i++) {
            round = i;
            int[] junk = new int[JUNK];
            junk[i % JUNK] = i;
            try {
                deep(5);
            } catch (Boom b) {
                counter.incrementAndGet();
            }
            box[0] += junk[i % JUNK];
        }
    }

    public static void main(String[] args) {
        System.out.println("Excgc on " + System.getProperty("os.name"));
        AtomicInteger counter = new AtomicInteger();
        int[] box = new int[1];
        churn(counter, box);
        check(counter.get() == ROUNDS && box[0] == ROUNDS * (ROUNDS - 1) / 2, "exception-gc");
        if (failures == 0) {
            System.out.println("EXCGC OK");
        } else {
            System.out.println("EXCGC FAILED " + failures);
            System.exit(1);
        }
    }
}
