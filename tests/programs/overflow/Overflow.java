/**
 * The `stack-overflow` check, split out of `stress`: unbounded recursion must raise a
 * StackOverflowError, the error must be catchable, and the thread must still be able to run
 * and to unwind a Java exception afterwards. It is its own program because on linux-amd64 the
 * LLVM backend kills the process with SIGSEGV here (run
 * https://github.com/Throwaway68/gha-graal/actions/runs/35324820994), which inside `stress`
 * would hide every check after it.
 */
public class Overflow {
    static final class Boom extends Exception {
        final int depth;
        Boom(int depth) { super("boom at " + depth); this.depth = depth; }
    }

    static volatile int sink;          // defeats constant folding; always 0
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

    static int recurse(int n) {
        return recurse(n + 1) + 1;
    }

    static void stackOverflow() {
        boolean caught = false;
        try {
            sink = recurse(0);
        } catch (StackOverflowError e) {
            caught = true;
        }
        boolean after = false;
        try {
            deep(10);
        } catch (Boom b) {
            after = b.depth == 0;
        }
        check(caught && after, "stack-overflow");
    }

    public static void main(String[] args) {
        System.out.println("Overflow on " + System.getProperty("os.name"));
        stackOverflow();
        if (failures == 0) {
            System.out.println("OVERFLOW OK");
        } else {
            System.out.println("OVERFLOW FAILED " + failures);
            System.exit(1);
        }
    }
}
