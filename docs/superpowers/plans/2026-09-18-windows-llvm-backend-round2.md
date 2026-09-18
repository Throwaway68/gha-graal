# Windows LLVM Backend, Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A program that throws and catches exceptions across frames (including implicit exceptions and `StackOverflowError`), allocates enough to run the GC with live references in LLVM-compiled frames, and runs several threads, built with `native-image --tool:llvm-backend`, runs and exits 0 on a windows-2022 runner, from a release build tagged `graalvm-round2-win-llvm`.

**Architecture:** Round 1 (`docs/superpowers/plans/2026-09-17-windows-llvm-backend-round1.md`, journal `docs/journal/windows-llvm-backend.md`) made `hello` run. Round 2 adds no new mechanism up front: it adds one purpose-built test program, first proves it on linux-amd64 (the known-good LLVM backend) and then on windows-amd64, and fixes whatever breaks on the graal branch. Iteration happens over an ssh session on the Windows runner (Windows OpenSSH server plus a cloudflared quick tunnel, because tmate does not work on windows-2022), not by workflow round trips.

**Tech Stack:** as round 1. GraalVM branch `Throwaway68/graal@graal/25.3.4.1-win-llvm`, LLVM release `llvm-22.1.8-graal.3`, workflows `graalvm-dev.yml` and `graalvm.yml` in `Throwaway68/gha-graal`, cloudflared (runner and local Mac, `brew install cloudflared` already done locally), Windows OpenSSH server.

**Spec:** `docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md` (round 2 = item 2 of the Goal, Section 5 for the test program and iteration loop).

## Global Constraints

- Git identity in every checkout under the Throwaway68 account: `Throwaway68 <carpettohd@gmail.com>`, set locally with `git config user.name Throwaway68 && git config user.email carpettohd@gmail.com` in any new clone or worktree before the first commit. Never any other identity, never decide one yourself.
- The GitHub token is passed to you in the task prompt. Use it only as `export GH_TOKEN=...` inside shell commands (for `gh`) and as the git credential helper `git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push ...`. Never write it into a file, a workflow, a commit, a log, the journal, or a report. Never paste it into an ssh session's command line either.
- gha-graal work happens on a branch per task (`round2-<task>`), pushed to `Throwaway68/gha-graal`; the controller merges to `main`. graal work happens on `graal/25.3.4.1-win-llvm` in the worktree named in the task prompt and is pushed directly to that branch.
- Every task ends with commits and a journal entry in `docs/journal/windows-llvm-backend.md` (dated `2026-09-18`, naming the commit or workflow run). Findings go under Findings, dead ends under Dead ends, rulings under Decisions. A task that hits a dead end records it and stops.
- The test bed is GitHub Actions. `graalvm-dev.yml` is dispatched with `gh workflow run graalvm-dev.yml --repo Throwaway68/gha-graal --ref <branch> -f platform=... -f program=... [-f debug_ssh=true]`. Never poll with `sleep` loops shorter than 60 s; use `gh run watch --exit-status <id>` with a timeout, or one bounded `sleep 300` per check.
- Update `.sync-manifest` in gha-graal with every file you create or meaningfully modify (one relative path per line, no duplicates, no deletions).
- Tests in this repo: `python3 -m pytest tests -q` and `bash tests/test_dev_run.sh` must stay green.

## Reference facts (verified; do not re-derive)

- `graalvm-dev.yml` builds a lean GraalVM from `graal_ref` (default `graal/25.3.4.1-win-llvm`) in about 8 minutes on windows-2022, runs `scripts/graalvm/dev-run.sh <graalvm-home> ci/tests/programs/<program> work [ni_args]`, uploads `work/stdout.txt`, `work/stderr.txt`, `work/tmp/**/llvm/*.obj` etc. as artifact `dev-<platform>-<program>`. Its `debug_ssh` input runs `mxschmitt/action-tmate` on Linux/macOS only; on Windows it only prints a warning (journal entry "debug_ssh is linux/macOS only", run 35262580562).
- `dev-run.sh` derives the main class from the program directory name with the first letter upper-cased (`hello` -> `Hello`) and requires every non-empty line of `expected.txt` to occur in stdout (CRLF-tolerant). It prints `DEV-RUN OK` at the end. Its `win_diag` prints `llvm-nm` matches for the marker symbols on Windows.
- Windows runner facts: user `runneradmin` (member of Administrators), MSYS2 at `C:\msys64`, Git for Windows at `C:\Program Files\Git` (`bin\bash.exe`), PowerShell 7 and 5.1, `ilammy/msvc-dev-cmd@v1.13.0` puts `cl.exe`/`link.exe` on the step PATH via `GITHUB_ENV`. Job logs are not readable through the API while the job runs; artifacts are downloadable as soon as they are uploaded (`gh run download <id> -n <name>`).
- The dispatching account's public keys are at `https://github.com/<actor>.keys`; the controller's key (`ssh-ed25519 ...JnB5`) is registered on Throwaway68, private key at `<scratchpad>/ssh/id_ed25519` (path given in the task prompt).
- Local Mac: `cloudflared` installed via Homebrew; `java` is GraalVM CE 25.0.3 (HotSpot), fine for running the test program on the JVM.
- Round 1's open verification list (journal, "what round 2 should verify"): throw/catch across an MSVC JNI frame (deferred to round 4, JNI), `StackOverflowError` through the yellow zone, a large frame so `__chkstk` is emitted, JNI wrappers in plain `.text`, the unread "2 warnings" from the Windows native-image build, and the darwin x27/x28 `llc` rejection (out of scope: round 2 is Windows).
- SVM implementation notes relevant to the checks: implicit exceptions (`NullPointerException`, `ArrayIndexOutOfBoundsException`, `ArithmeticException`, `ClassCastException`, `ArrayStoreException`, `NegativeArraySizeException`) are thrown from Java-level slow paths and unwind like explicit throws; `StackOverflowError` comes from the explicit stack-overflow check at method entry (`StackOverflowCheck`), not from a guard-page fault; GC roots in compiled frames come from the LLVM stack maps parsed at build time; safepoints in other threads are polls in compiled code.

## File structure

- `tests/programs/stress/Stress.java` (new), `tests/programs/stress/expected.txt` (new): the round 2 program. The directory is `stress`, not `runtime`, because `Runtime` as a main-class name shadows `java.lang.Runtime` (controller ruling, recorded in the journal by Task 2).
- `.github/workflows/graalvm-dev.yml` (modify): the Windows ssh block replacing the "Say why there is no ssh session on Windows" step.
- `scripts/graalvm/win-ssh.ps1` (new): PowerShell that installs and configures Windows OpenSSH server, starts the cloudflared quick tunnel, writes `address.txt`. Kept out of the workflow so it can be read and tested on its own.
- `scripts/graalvm/dev-run.sh` (modify, Task 2): `win_diag` also greps `chkstk` symbols.
- `.github/workflows/graalvm.yml` (modify, Task 4): the smoke step also runs `stress` through `dev-run.sh` when the llvm-backend tool exists.
- graal branch: whatever Task 3 finds; expected area `substratevm/src/com.oracle.svm.core.graal.llvm/`.
- `docs/journal/windows-llvm-backend.md`, `README.md`, `.sync-manifest`.

---

### Task 1: ssh into the Windows runner from graalvm-dev.yml

**Files:**
- Create: `scripts/graalvm/win-ssh.ps1`
- Modify: `.github/workflows/graalvm-dev.yml` (the Windows branch of the `debug_ssh` block)
- Modify: `docs/journal/windows-llvm-backend.md`, `.sync-manifest`, `README.md` (one paragraph under the dev-loop section: how to connect)

**Interfaces:**
- Consumes: `inputs.debug_ssh`, `github.actor`, the `GRAALVM_HOME`/`JAVA_HOME`/`MX_PATH`/`MX_URLREWRITES` variables and the MSVC PATH of the step environment.
- Produces: artifact `ssh-windows-amd64` containing `address.txt` with three lines: the trycloudflare hostname, the exact local `ssh` command, and the path of the hold file to delete to end the session. An interactive ssh shell (Git bash) where `cl`, `link`, `native-image --version`, `$GRAALVM_HOME`, `$MX_PATH/mx`, `$JAVA_HOME` all work. Task 3 relies on exactly this.

Mechanism (primary): Windows OpenSSH server + cloudflared quick tunnel, the way `valeriangalliat/action-sshd-cloudflared` does it. Fallback if `Add-WindowsCapability` cannot install `OpenSSH.Server` on the runner within 3 minutes: MSYS2's `openssh` package (`C:\msys64\usr\bin\pacman -S --noconfirm openssh`, `ssh-keygen -A`, run `sshd -D -p 22` in the background as the runner user with `StrictModes no` and `PasswordAuthentication no`). Record which one worked, and why, in the journal.

- [ ] **Step 1: Spike the mechanism on a throwaway workflow**

Create branch `round2-ssh` from `main`. Add `.github/workflows/win-ssh-spike.yml` (throwaway, deleted in Step 4) with a single windows-2022 job that runs `ilammy/msvc-dev-cmd@v1.13.0`, then `scripts/graalvm/win-ssh.ps1`, uploads `address.txt` as artifact `ssh-windows-amd64`, and holds for up to 60 minutes on `$RUNNER_TEMP/gha-hold`. No GraalVM build, so an iteration costs 2 to 4 minutes.

`scripts/graalvm/win-ssh.ps1` (first version; adapt as the spike shows):

```powershell
# Open an ssh session to this Windows runner: Windows OpenSSH server, key auth only for the
# public keys of the GitHub account that dispatched the run, reached through a cloudflared quick
# tunnel. Writes <out-dir>\address.txt (hostname, ssh command, hold file). Usage:
#   pwsh scripts/graalvm/win-ssh.ps1 -Actor <github actor> -OutDir <dir> -HoldFile <path>
param([Parameter(Mandatory)][string]$Actor, [Parameter(Mandatory)][string]$OutDir, [Parameter(Mandatory)][string]$HoldFile)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 1. OpenSSH server (Windows capability; ~1 min). Key auth only.
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
$keys = (Invoke-WebRequest -UseBasicParsing "https://github.com/$Actor.keys").Content
if (-not $keys.Trim()) { throw "no public keys on github.com/$Actor; the session would be unusable" }
$ak = 'C:\ProgramData\ssh\administrators_authorized_keys'
New-Item -ItemType Directory -Force 'C:\ProgramData\ssh' | Out-Null
Set-Content -Path $ak -Value $keys -Encoding ascii
icacls $ak /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
$cfg = 'C:\ProgramData\ssh\sshd_config'
Start-Service sshd; Stop-Service sshd   # first start writes the default sshd_config and host keys
(Get-Content $cfg) -replace '^#?PasswordAuthentication .*', 'PasswordAuthentication no' `
                   -replace '^#?PubkeyAuthentication .*', 'PubkeyAuthentication yes' | Set-Content $cfg
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value 'C:\Program Files\Git\bin\bash.exe' -PropertyType String -Force | Out-Null
Start-Service sshd

# 2. The step environment (MSVC PATH, GRAALVM_HOME, ...) for interactive shells: sshd is a
#    service and knows nothing of it.
$envFile = Join-Path $env:USERPROFILE '.gha-env.sh'
$lines = Get-ChildItem env: | Where-Object { $_.Name -notmatch '^(PROMPT|PWD|OLDPWD|SHLVL|_)$' } | ForEach-Object {
  $v = $_.Value -replace "'", "'\''"
  "export $($_.Name)='$v'"
}
Set-Content -Path $envFile -Value $lines -Encoding ascii
Add-Content -Path (Join-Path $env:USERPROFILE '.bash_profile') -Value 'source ~/.gha-env.sh; cd "$GITHUB_WORKSPACE" 2>/dev/null || true'
Add-Content -Path (Join-Path $env:USERPROFILE '.bashrc') -Value 'source ~/.gha-env.sh'

# 3. cloudflared quick tunnel to port 22; the hostname appears in its log within seconds.
$cf = Join-Path $OutDir 'cloudflared.exe'
Invoke-WebRequest -UseBasicParsing 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cf
$log = Join-Path $OutDir 'cloudflared.log'
Start-Process -FilePath $cf -ArgumentList 'tunnel','--no-autoupdate','--url','tcp://localhost:22','--logfile',$log -WindowStyle Hidden
$host_ = $null
foreach ($i in 1..60) {
  Start-Sleep 2
  if (Test-Path $log) { $m = Select-String -Path $log -Pattern 'https://([a-z0-9-]+\.trycloudflare\.com)' | Select-Object -First 1
    if ($m) { $host_ = $m.Matches[0].Groups[1].Value; break } }
}
if (-not $host_) { Get-Content $log; throw 'cloudflared did not publish a trycloudflare hostname' }

# 4. Publish. The private key stays with the caller; nothing secret is in this file.
Set-Content -Path $HoldFile -Value 'delete me to end the session'
$cmd = "ssh -o ProxyCommand=""cloudflared access tcp --hostname %h"" -o StrictHostKeyChecking=no runneradmin@$host_"
@($host_, $cmd, $HoldFile) | Set-Content -Path (Join-Path $OutDir 'address.txt') -Encoding ascii
Get-Content (Join-Path $OutDir 'address.txt')
```

Dispatch the spike (`gh workflow run win-ssh-spike.yml --repo Throwaway68/gha-graal --ref round2-ssh`), wait for artifact `ssh-windows-amd64` (`gh run download <id> -n ssh-windows-amd64 -D <scratchpad>/ssh-addr`), then from the Mac:

```bash
ssh -i <scratchpad>/ssh/id_ed25519 -o ProxyCommand="cloudflared access tcp --hostname %h" -o StrictHostKeyChecking=no runneradmin@<host> 'cl 2>&1 | head -1; echo GITHUB_WORKSPACE=$GITHUB_WORKSPACE; uname -a'
```

Expected: the `cl` banner line (`Microsoft (R) C/C++ Optimizing Compiler ...`), the workspace path, and `MINGW64_NT-...`. Then `ssh ... 'rm "<hold file>"'` and confirm the job finishes green within a minute. Iterate on the script until this works; every failed attempt's cause goes into the journal under Dead ends in one line.

- [ ] **Step 2: Integrate into graalvm-dev.yml**

Replace the step `Say why there is no ssh session on Windows` with (keep the Linux/macOS tmate block untouched):

```yaml
      - name: Debug over ssh (Windows OpenSSH + cloudflared)
        if: ${{ !cancelled() && inputs.debug_ssh && runner.os == 'Windows' }}
        timeout-minutes: 10
        shell: pwsh
        run: pwsh ci/scripts/graalvm/win-ssh.ps1 -Actor '${{ github.actor }}' -OutDir "$env:RUNNER_TEMP\ssh" -HoldFile "$env:RUNNER_TEMP\gha-hold"
      - name: Upload the ssh address (Windows)
        if: ${{ !cancelled() && inputs.debug_ssh && runner.os == 'Windows' }}
        timeout-minutes: 10
        uses: actions/upload-artifact@v7.0.1
        with:
          name: ssh-${{ inputs.platform }}
          path: ${{ runner.temp }}/ssh/address.txt
      - name: Hold the runner for the ssh session (Windows)
        if: ${{ !cancelled() && inputs.debug_ssh && runner.os == 'Windows' }}
        timeout-minutes: 180
        shell: bash
        run: |
          hold=$RUNNER_TEMP/gha-hold
          echo "holding the runner; in the ssh session run: rm '$hold'"
          while [ -f "$hold" ]; do sleep 15; done
          echo "hold released"
```

Update the long comment above the tmate step: Windows now has its own mechanism; keep the sentence about why tmate is not used there. Update the `debug_ssh` input description to `Open an interactive ssh session on the runner after dev-run (tmate on linux/macOS, OpenSSH + cloudflared on windows); the address is in artifact ssh-<platform>`.

- [ ] **Step 3: Verify end to end**

Dispatch `graalvm-dev.yml` on `round2-ssh` with `platform=windows-amd64 program=hello debug_ssh=true`. When artifact `ssh-windows-amd64` exists, connect and run:

```bash
cd "$GITHUB_WORKSPACE" && "$GRAALVM_HOME/bin/native-image.cmd" --version && cl 2>&1 | head -1 && ls work && bash ci/scripts/graalvm/dev-run.sh "$GRAALVM_HOME" ci/tests/programs/hello "$GITHUB_WORKSPACE/work2"
```

Expected: the native-image version line, the `cl` banner, the work directory listing, and a second `DEV-RUN OK` from the ssh session. Record the run URL, the time from dispatch to a usable shell, and the two dev-run timings in the journal (Milestones: "interactive ssh on windows-2022 works"). Release the hold; confirm the job ends green and still uploads `dev-windows-amd64-hello`.

- [ ] **Step 4: Clean up, document, commit**

Delete `win-ssh-spike.yml`. README: a paragraph "Interactive session on the Windows runner" with the dispatch command, the artifact name, the ssh command (with `-i <your key>`), and `rm "$RUNNER_TEMP/gha-hold"` to end it. Journal: the milestone above plus a Findings entry on what the runner's OpenSSH setup needed (capability install time, `administrators_authorized_keys`, DefaultShell, environment file). `.sync-manifest`. Commit(s) on `round2-ssh` with identity `Throwaway68 <carpettohd@gmail.com>`, push. Run `python3 -m pytest tests -q && bash tests/test_dev_run.sh`.

---

### Task 2: the `stress` test program, green on linux-amd64

**Files:**
- Create: `tests/programs/stress/Stress.java`, `tests/programs/stress/expected.txt`
- Modify: `scripts/graalvm/dev-run.sh` (`win_diag`: add `chkstk` to the `llvm-nm` grep)
- Modify: `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

**Interfaces:**
- Consumes: `dev-run.sh`'s contract (directory name -> main class `Stress`, `expected.txt` lines must appear in stdout).
- Produces: `tests/programs/stress` for Tasks 3 and 4. Every check prints `OK <name>`; failures print `FAIL <name>` and the process exits 1 with `STRESS FAILED <n>`.

- [ ] **Step 1: Write the program**

`tests/programs/stress/Stress.java`:

```java
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
        stackOverflow();
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
```

`tests/programs/stress/expected.txt`:

```
OK throw-catch-deep
OK implicit-exceptions
OK rethrow-wrap
OK finally-order
OK stack-overflow
OK gc-live-frames
OK gc-weakref
OK gc-pressure
OK threads-basic
OK threads-gc
OK threads-wait-notify
OK thread-exceptions
STRESS OK
```

- [ ] **Step 2: Run it on the JVM**

```bash
mkdir -p <scratchpad>/stress-classes && javac -d <scratchpad>/stress-classes tests/programs/stress/Stress.java && java -cp <scratchpad>/stress-classes Stress
```

Expected: all thirteen lines of `expected.txt`, exit 0, under 30 s. Fix the program until this holds (the checks are the contract; the arithmetic in `gcPressure`/`threadsBasic` must be right on HotSpot before anything runs on SVM).

- [ ] **Step 3: `win_diag` reports `chkstk`**

In `scripts/graalvm/dev-run.sh`, `win_diag`, change the marker grep to `grep -E '__svm_code_section|__svm_text_end|__svm_seh_personality|chkstk'` and its echo line to `-- markers, SEH glue and stack probes in $obj`. Run `bash tests/test_dev_run.sh`; expected: passes unchanged.

- [ ] **Step 4: Baseline on linux-amd64**

Commit on branch `round2-stress` (from `main`), push, dispatch `gh workflow run graalvm-dev.yml --repo Throwaway68/gha-graal --ref round2-stress -f platform=linux-amd64 -f program=stress`, wait with `gh run watch --exit-status`. Expected: `DEV-RUN OK`. If a check fails on the LLVM backend on Linux, that is a finding about the program or about the backend itself, not about Windows: investigate from the artifact (`stdout.txt`, `stderr.txt`), fix the program only if the program is wrong, and record the finding in the journal. If `deep frames in trace` is below 60 on Linux, record the printed number and the reason (inlined frames not reported by the LLVM backend's frame info) in the journal and lower the `frames >= 60` thresholds (both checks) to `frames >= 10`.

- [ ] **Step 5: Journal, manifest, commit**

Journal (Findings): the linux-amd64 baseline run URL, its timings, the `deep frames in trace` number, and the ruling "directory `stress`, not `runtime`: a main class named `Runtime` shadows `java.lang.Runtime`" under Decisions. `.sync-manifest`. Push `round2-stress`.

---

### Task 3: `stress` green on windows-amd64

**Files:**
- Modify: graal branch `graal/25.3.4.1-win-llvm` in the worktree named in the prompt (expected area `substratevm/src/com.oracle.svm.core.graal.llvm/`), pushed to `Throwaway68/graal`.
- Modify: `docs/journal/windows-llvm-backend.md` (every finding, every dead end), `.sync-manifest`; `tests/programs/stress/*` only if the program itself is proven wrong.

**Interfaces:**
- Consumes: Task 1's ssh session (artifact `ssh-<platform>`, hold file), Task 2's program, both merged to `main` by the controller before this task starts.
- Produces: a green `graalvm-dev.yml` run on windows-amd64 with `program=stress` from `main` and the graal branch head, whose URL goes into the journal's Milestones.

- [ ] **Step 1: First Windows run, held open**

Dispatch `gh workflow run graalvm-dev.yml --repo Throwaway68/gha-graal --ref main -f platform=windows-amd64 -f program=stress -f debug_ssh=true`. Download artifact `ssh-windows-amd64` as soon as it exists, connect (Task 1's command). Read `work/stdout.txt`, `work/stderr.txt`; also read and record the native-image build's warnings (the "2 warnings" from round 1 are in `stderr.txt` or the build output above `DEV-RUN`): what they are and whether they matter, in the journal.

- [ ] **Step 2: Iterate on the runner**

For each failure: reproduce in the session (`cd $GITHUB_WORKSPACE && ./work/app.exe`; exit codes `0xC0000005` = access violation, `0xC00000FD` = stack overflow, `0x20474343` = an unhandled libunwind exception), narrow it with a reduced program if needed (write it under `$GITHUB_WORKSPACE/scratch`, build with `bash ci/scripts/graalvm/dev-run.sh "$GRAALVM_HOME" scratch/<dir> "$GITHUB_WORKSPACE/w-<dir>"`), then edit the graal sources in `$GITHUB_WORKSPACE/graal`, rebuild incrementally with `cd graal/vm && "$MX_PATH/mx" --env ce-llvm-dev build` (Java-only changes take 1 to 3 minutes; the `GRAALVM_HOME` path stays valid), and rerun. Useful runtime flags for the image: `-XX:+PrintGC`, `-XX:+VerboseGC`; build flags: keep `-H:TempDirectory` and read `work/tmp/*/llvm/*.bc` with `$GRAALVM_HOME/lib/llvm/bin/llvm-dis`. `$GRAALVM_HOME/lib/llvm/bin/lldb.exe` exists only if the bundle carries it (check; if not, `cdb.exe` under `C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\` may exist on the image). Bring every source change back to the Mac worktree (`git -C $GITHUB_WORKSPACE/graal diff > patch` over ssh, `scp` it, `git apply` locally), commit with the Throwaway68 identity, push to `graal/25.3.4.1-win-llvm`. One journal Findings entry per root cause, one Dead ends entry per abandoned hypothesis, each naming the run and commit.

Stop conditions: the run is green; or three ssh sessions (each up to 180 minutes) have not produced a green run, in which case report `DONE_WITH_CONCERNS` with the remaining failing checks and the best current hypothesis, everything already in the journal.

- [ ] **Step 3: Confirm from a clean run**

With all fixes pushed, dispatch `graalvm-dev.yml` from `main` with `platform=windows-amd64 program=stress` (no ssh). Expected: `DEV-RUN OK`. Then dispatch `platform=linux-amd64 program=stress` against the new graal head. Expected: `DEV-RUN OK` (no regression). Both URLs go into the journal's Milestones entry "stress green on windows-amd64".

- [ ] **Step 4: Journal, manifest, push**

Journal Milestones entry with the run URLs and the graal commit; `.sync-manifest`; commit on `round2-win` (from `main`) and push. `python3 -m pytest tests -q && bash tests/test_dev_run.sh` green.

---

### Task 4: release `graalvm-round2-win-llvm`

**Files:**
- Modify: `.github/workflows/graalvm.yml` (smoke step), `README.md`, `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

**Interfaces:**
- Consumes: Task 3's green graal head; `scripts/graalvm/smoke.sh` and `scripts/graalvm/dev-run.sh` unchanged.
- Produces: release `graalvm-round2-win-llvm` in `Throwaway68/gha-graal` with linux-amd64 and windows-amd64 bundles whose smoke logs show `LLVM backend: tested` and `DEV-RUN OK` for `stress`.

- [ ] **Step 1: The release smoke test runs `stress`**

In `.github/workflows/graalvm.yml`, after the `Smoke test` step's `smoke.sh` call, add to the same `run:` block:

```bash
if [ -d "$GRAALVM_HOME/lib/svm/tools/llvm-backend" ] || [ -d "$GRAALVM_HOME/lib/svm/macros/llvm-backend" ]; then
  bash ci/scripts/graalvm/smoke-stress.sh "$GRAALVM_HOME" "$GITHUB_WORKSPACE/stress"
fi
```

where `scripts/graalvm/smoke-stress.sh` is:

```bash
#!/usr/bin/env bash
# Release smoke test for the LLVM backend beyond hello world: build and run tests/programs/stress
# with dev-run.sh. smoke-stress.sh <graalvm-home> <work-dir>
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
bash "$here/dev-run.sh" "$1" "$here/../../tests/programs/stress" "$2"
```

Verify with the round 1 bundle locally? Not possible (no local LLVM backend bundle for macOS); verification is the release run itself.

- [ ] **Step 2: Dispatch the release**

`gh workflow run graalvm.yml --repo Throwaway68/gha-graal --ref round2-release -f tag=graalvm-round2-win-llvm -f platforms=linux-amd64,windows-amd64` with the other inputs at their defaults (check `gh workflow view graalvm.yml --yaml` for exact input names: `graal_ref`, `llvm_release`, `platforms`, `tag`). Wait with `gh run watch --exit-status`. Expected: release published with both bundles and `manifest.json`; both smoke logs contain `LLVM backend: tested` and `DEV-RUN OK`.

- [ ] **Step 3: Document**

README: the round 2 release under the releases list, what `stress` covers. Journal: Milestones entry with the release URL and run URL; Findings entry summarising what round 2 changed on the graal branch (one line per commit); the still-open items for round 3 (the substratevm LLVM gate) and round 4 (JNI in both directions, throw across an MSVC frame). `.sync-manifest`. Commit on `round2-release`, push.
