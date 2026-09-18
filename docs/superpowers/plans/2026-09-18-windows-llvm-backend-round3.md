# Windows LLVM Backend, Round 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The substratevm gate tasks that Oracle's CI runs under the LLVM backend (the `use_llvm` mixin: the `basics` tags with `--extra-image-builder-arguments="-H:+UnlockExperimentalVMOptions --tool:llvm-backend -H:-UnlockExperimentalVMOptions"`) pass on windows-amd64 from `Throwaway68/graal@graal/25.3.4.1-win-llvm`, with linux-amd64 as the reference.

**Architecture:** A new workflow `graalvm-gate.yml` in this repository checks out graal at a ref, points mx at our LLVM release, and runs `mx gate` inside `substratevm/` with a `tags` input and the LLVM extra-argument, on one platform; it reuses the mx download cache and the ssh mechanisms of `graalvm-dev.yml` (tmate on linux/macOS, OpenSSH + cloudflared on Windows). Failures are fixed on the graal branch through the ssh session, one root cause per commit, journaled. The round ends with the gate green on Windows for every tag that is meaningful there, and a release tagged `graalvm-round3-win-llvm`.

**Tech Stack:** as rounds 1-2. mx gate (`substratevm/mx.substratevm/mx_substratevm.py` `svm_gate_body`), `mx native-unittest`.

**Spec:** `docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md` (Goal item 3).

## Global Constraints

- Git identity in every checkout under the Throwaway68 account: `Throwaway68 <carpettohd@gmail.com>`, set locally per clone/worktree. Never any other, never decided by you.
- The GitHub token is passed in the task prompt; only `export GH_TOKEN=...` in shell commands and the credential helper `git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push ...`. Never in a file, workflow, commit, log, journal, report, or ssh session.
- gha-graal work on a branch per task (`round3-<task>`), the controller merges to `main`. graal work on `graal/25.3.4.1-win-llvm` in the worktree named in the task prompt, pushed to the `fork` remote (`origin` is oracle/graal and refuses pushes). The darwin-aarch64 port is being worked on the same graal branch concurrently by another task: rebase before pushing, never force-push.
- Every task ends with commits and journal entries in `docs/journal/windows-llvm-backend.md` (dated 2026-09-18 or later, naming run or commit; Findings per root cause, Dead ends per abandoned hypothesis, Milestones for green runs; hypotheses labelled).
- `graalvm-dev.yml`/`graalvm-gate.yml` dispatch: `gh workflow run <file> --repo Throwaway68/gha-graal --ref <branch> -f ...`. No sleep-polling loops with short intervals; background `gh run watch --exit-status`.
- `.sync-manifest` updated with every created/modified file (relative paths, no duplicates, no deletions). `python3 -m pytest tests -q` and `bash tests/test_dev_run.sh` stay green.

## Reference facts (verified 2026-09-18; do not re-derive)

- There is no `llvm` gate tag. `substratevm/ci/ci_common/svm-gate.libsonnet:117-119` defines `use_llvm` as `mxgate_config+::["llvm"]` plus `mxgate_extra_args+: ["--extra-image-builder-arguments=-H:+UnlockExperimentalVMOptions --tool:llvm-backend -H:-UnlockExperimentalVMOptions"]`; no job in `substratevm/ci/ci.jsonnet` composes it (Oracle runs it from an internal overlay). The `basics` job (`ci.jsonnet:137`) is `mxgate("build,helloworld,all_native_unittests,check_svm_invariants,truffle_unittests,debuginfotest,hellomodule,java_agent,condconfig,java_desktop_integration")`, run as `cd substratevm && mx --kill-with-sigquit --strict-compliance gate --strict-mode --tags <tags> <extra args>` (`svm-gate.libsonnet:15-47`), time limits 40 min linux / 60 min windows with `partial(2)`.
- `svm_gate_body` (`mx_substratevm.py:504-686`) threads `args.extra_image_builder_arguments` into: hellomodule (:507-510), image demos/helloworld (:515-516), debuginfotest (:527, skipped on Windows :523), layereddebuginfotest (:538, skipped on Windows and darwin-arm64), debughelpertest (:546, skipped on Windows), native unittests (:561), generic field type (:566), runtime classpath resource (:571), java.desktop integration (:598), truffle unittests (:608, :621), java agent (:686). Standalone pointsto unittests are skipped on Windows (:552).
- `mx native-unittest` (`mx_substratevm.py:3614-3629`, `_native_unittest` ~:1315) defaults to `com.oracle.svm.test` and `com.oracle.svm.configure.test`, groups classes by `@NativeImageBuildArgs`, builds one image per group; `--blacklist <file>` / `--whitelist <file>` take fnmatch patterns, one per line, `#` comments. No LLVM-specific blacklist exists anywhere. `all_native_unittests` runs the custom groups in batches `1/2`, `2/2` (:576-586, `NATIVE_UNITTEST_CUSTOM_BATCHES` :281).
- `llvm_supported = True` on the branch (`mx_substratevm.py:2201-2206`); the `svml` component is registered from the substratevm suite itself, so a gate run from `substratevm/` builds the LLVM backend tool into its GraalVM home as long as the LLVM.org toolchain distribution resolves (the `MX_URLREWRITES` file from `graalvm-dev.yml` handles that). Whether `mx gate` from `substratevm/` picks up `svml` without an `--env` is to be verified in Task 1; if not, `--env ce-llvm-dev` with `MX_ENV_PATH` or `DYNAMIC_IMPORTS` set explicitly.
- Known LLVM-backend bugs that the gate may hit on every platform: catching a `StackOverflowError` crashes (`tests/programs/overflow`); an unreproduced crash after a caught exception in an allocating multi-thread loop (run 35325689605). Journal has both.
- Windows runner: `graalvm-dev.yml` shows the build steps (msvc-dev-cmd, mx download cache, LabsJDK fetch, URL rewrites, env file). A lean build is ~8 min; the gate's own `build` tag builds substratevm (+ its GraalVM home) itself.

## File structure

- `.github/workflows/graalvm-gate.yml` (new): inputs `graal_ref`, `llvm_release`, `platform`, `tags` (default `build,helloworld,hellomodule`), `extra_image_builder_args` (default the `use_llvm` string), `unittest_args` (default empty, passed through to `--extra-unittest-arguments`? verify the gate exposes such a thing; otherwise omit), `debug_ssh`. Steps mirror `graalvm-dev.yml` up to the build, then `cd graal/substratevm && mx --strict-compliance gate --strict-mode --tags <tags> --extra-image-builder-arguments="<extra>"` (cmd on Windows via `mx.cmd`), then the ssh block copied from `graalvm-dev.yml` (both platforms), then upload of `graal/substratevm/mxbuild/**/svmbuild/**/reports/**`, `**/*.log` that the gate leaves behind (find out what it leaves; keep the artifact small).
- `scripts/graalvm/gate-summary.py` (new, optional): parses the gate log for the `Gate task` lines and prints a table of task → status/time, so a run's result is one artifact file (`gate-summary.txt`). Tested with `tests/test_gate_summary.py` on a saved log excerpt.
- graal branch: fixes under `substratevm/src/com.oracle.svm.core.graal.llvm/` unless proven otherwise; a `substratevm/mx.substratevm/llvm-unittest-blacklist` file listing tests that cannot pass under the backend for a documented reason (e.g. the StackOverflowError bug), each with a `#` comment naming the journal entry, if needed.
- `docs/journal/windows-llvm-backend.md`, `README.md`, `.sync-manifest`.

---

### Task 1: `graalvm-gate.yml`, and the gate's `build,helloworld,hellomodule` green on linux-amd64 and windows-amd64

**Files:**
- Create: `.github/workflows/graalvm-gate.yml`, `scripts/graalvm/gate-summary.py`, `tests/test_gate_summary.py`
- Modify: `README.md` (workflow section), `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

**Interfaces:**
- Consumes: `graalvm-dev.yml` build steps and ssh blocks (copy, do not refactor the dev workflow), `mx-env/ce-llvm-dev`, `scripts/graalvm/win-ssh.ps1`.
- Produces: a workflow that Task 2 dispatches with any `tags`; artifact `gate-<platform>-<run>` with `gate-summary.txt` and the logs; the journal entry stating exactly how the gate is invoked on each platform and how long `build,helloworld,hellomodule` takes.

- [ ] **Step 1: Workflow skeleton on branch `round3-gate`**, copied from `graalvm-dev.yml` (checkouts, paths, mx cache, LabsJDK, URL rewrites, env file, MSVC). Replace the build + dev-run steps by one `Gate` step:

```yaml
      - name: Gate (Linux/macOS)
        if: runner.os != 'Windows'
        shell: bash
        run: |
          cd graal/substratevm
          "$MX_PATH/mx" --strict-compliance gate --strict-mode --tags "${{ inputs.tags }}" --extra-image-builder-arguments="${{ inputs.extra_image_builder_args }}" 2>&1 | tee "$GITHUB_WORKSPACE/gate.log"
          exit "${PIPESTATUS[0]}"
      - name: Gate (Windows)
        if: runner.os == 'Windows'
        shell: cmd
        run: |
          cd graal\substratevm
          call %MX_PATH%\mx.cmd --strict-compliance gate --strict-mode --tags "${{ inputs.tags }}" --extra-image-builder-arguments="${{ inputs.extra_image_builder_args }}" > %GITHUB_WORKSPACE%\gate.log 2>&1
          set rc=%ERRORLEVEL%
          type %GITHUB_WORKSPACE%\gate.log
          exit /b %rc%
```

(The Windows step buffers the log to a file because `tee` is not available in cmd; if the log is huge, print only its tail and rely on the artifact.) Verify on the first Linux run whether `mx gate` from `substratevm/` builds the LLVM backend tool into the GraalVM home it uses (`--tool:llvm-backend` resolves) - if `helloworld` fails with an unknown tool/macro, add `--env ce-llvm-dev` via `MX_ENV_PATH=$GITHUB_WORKSPACE/graal/vm/mx.vm` or the `--dynamicimports` the `use_llvm` config needs, record the answer in the journal.

- [ ] **Step 2: `gate-summary.py`** reads a gate log and prints one line per `Gate task` (mx prints `Gate task: <name>` / `Gate task ... done` with elapsed time; check `mx/mx_gate.py` in the mx checkout for the exact lines) plus the final status; `tests/test_gate_summary.py` feeds it a 20-line excerpt saved from the first real run and asserts the table. The workflow runs it after the gate (`if: always()`) and uploads `gate-summary.txt` and `gate.log`.

- [ ] **Step 3: Runs.** linux-amd64 with default tags → expected green (this is the reference; if `helloworld` fails on Linux, that is a backend finding, investigate and journal). windows-amd64 with default tags → fix whatever breaks (workflow-side: paths, cmd quoting, tool discovery; backend-side: journal + fix on the graal branch through the ssh session as in round 2). Both runs' URLs and durations go into the journal Milestones ("gate build,helloworld,hellomodule green on windows-amd64").

- [ ] **Step 4: README + journal + manifest + tests**, commit, push `round3-gate`.

---

### Task 2: the remaining gate tags on windows-amd64

**Files:**
- Modify: graal branch (fixes), `docs/journal/windows-llvm-backend.md`, `.sync-manifest`; possibly `substratevm/mx.substratevm/llvm-unittest-blacklist` on the graal branch and a `--blacklist` wiring in the workflow's `extra` inputs if `native-unittest` needs it (find out how the gate task passes unittest args: `native_unittests_task` in `mx_substratevm.py:869-885`; if there is no hook, add `LLVM_UNITTEST_BLACKLIST` env support in `svm_gate_body`'s native unittest task on the branch, guarded so upstream behaviour is unchanged when unset).

**Interfaces:**
- Consumes: Task 1's workflow.
- Produces: for each of `native_unittests` (default group), `all_native_unittests` (batches 1/2, 2/2), `check_svm_invariants`, `truffle_unittests`, `java_agent`, `condconfig`, `java_desktop_integration`: a windows-amd64 run URL, its status, and for every failing test either a fix commit or a blacklist entry with a journal Findings entry. Tags that `svm_gate_body` skips on Windows (`debuginfotest`, standalone pointsto) are recorded as skipped, not attempted.

- [ ] **Step 1:** dispatch windows-amd64 with `tags=build,native_unittests` and `debug_ssh=true`; read the summary; iterate on the runner (`cd graal/substratevm && mx native-unittest --build-args -H:+UnlockExperimentalVMOptions --tool:llvm-backend -- <test class>` reproduces a single class in minutes). One journal Findings entry per root cause; a blacklist entry only for failures whose cause is a known, journaled backend bug that is out of this round's reach (the two known ones), never for unexplained failures.
- [ ] **Step 2:** the same for `all_native_unittests` (both batches), then `truffle_unittests`, `check_svm_invariants`, `java_agent`, `condconfig`, `java_desktop_integration`, one dispatch each (or combined once they pass individually). Run linux-amd64 with the same tags once at the end as the no-regression check against the new graal head.
- [ ] **Step 3:** journal Milestones entry with the full table (tag → windows run URL → status → skipped/blacklisted count), manifest, commit on `round3-gate2`, push. Stop conditions: all tags green or blacklisted with journaled causes; or four ssh sessions without progress on a tag → DONE_WITH_CONCERNS with the table so far.

---

### Task 3: release `graalvm-round3-win-llvm` and documentation

**Files:**
- Modify: `README.md`, `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

- [ ] **Step 1:** `gh workflow run graalvm.yml --repo Throwaway68/gha-graal --ref round3-release -f label=round3-win-llvm -f platforms=linux-amd64,windows-amd64` (add `darwin-aarch64` if the darwin task has made the smoke test green by then; check the journal). Wait; verify assets and the smoke logs (`STRESS OK`, `DEV-RUN OK`, `SMOKE OK`).
- [ ] **Step 2:** README: the round 3 release entry, the gate table, how to dispatch `graalvm-gate.yml`; journal Milestones entry; open items for round 4 (JNI both directions, throw across an MSVC frame) and the still-open backend bugs; manifest; commit on `round3-release`, push.
