# Windows LLVM Backend, Round 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `native-image --tool:llvm-backend` builds a hello world that runs and exits 0 on a windows-2022 GitHub runner, from a release build.

**Architecture:** graal fork branch `graal/25.3.4.1-win-llvm` opens the backend for Windows and replaces the ELF-only object pipeline (ld -r, objcopy symbols) with a single-object build plus COFF grouped-section markers. Exceptions keep the Itanium personality written in Java; a tiny IR shim adapts it to Windows SEH through libunwind's SEH mode, which the LLVM workflow now builds into the Windows toolchain bundle. This repository gains a shadowed-jar workflow (windows-x86_64 JavaCPP bindings), a fast dev workflow with build caching, and a journal.

**Tech Stack:** GitHub Actions (windows-2022, ubuntu-22.04, macos-14), mx 7.85.1, LabsJDK ce-25.0.4.1+1-jvmci-25.3-b22, LLVM 22.1.8 (graal patches), libunwind SEH mode, JavaCPP 1.5.7 / LLVM presets 13.0.1-1.5.7, Python 3.11, bash.

**Spec:** `docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md`

## Global Constraints

- Git identity in every checkout under the Throwaway68 account: `Throwaway68 <carpettohd@gmail.com>`. Set it with `git config user.name Throwaway68 && git config user.email carpettohd@gmail.com` before the first commit in any new clone or worktree. Never any other identity, never decide one yourself.
- The GitHub token is passed to you in the task prompt. Use it only as `export GH_TOKEN=...` inside shell commands and as the git credential helper shown in Task 1. Never write it into a file, a workflow, a commit, a log, the journal, or a report.
- Base revisions: graal tag `graal-25.3.4.1` (commit 7b025988a9), LLVM branch `graal/22.1.8` in `Throwaway68/llvm-project`, LLVM release `llvm-22.1.8-graal.1` in `Throwaway68/gha-graal`.
- Target triple for LLVM codegen on Windows: `x86_64-pc-windows-msvc` (so LLVM emits `__chkstk`, the MSVC CRT symbol). libunwind is compiled for `x86_64-w64-windows-gnu` (that is what enables its SEH mode) but linked into the MSVC-built image as a plain COFF archive.
- Every task ends with a commit and a journal entry in `docs/journal/windows-llvm-backend.md` (Task 1 creates it). A task that hits a dead end records it under "Dead ends" and stops.
- Action versions: `actions/checkout@v7.0.1`, `actions/upload-artifact@v7.0.1`, `actions/download-artifact@v8.0.1`, `actions/setup-python@v7.0.0`, `actions/cache@v4`, `ilammy/msvc-dev-cmd@v1.13.0`, `mozilla-actions/sccache-action@v0.0.11`.
- Windows runner facts: MSYS2 at `C:\msys64` (not on PATH, pacman available), Visual Studio 2022 17.14, CMake 3.31, Ninja 1.13, Python 3.12 default.
- Test bed is GitHub Actions only. No local Windows VM.
- Update `.sync-manifest` in gha-graal with every file you create or meaningfully modify (one relative path per line, no duplicates, no deletions).

## Reference facts (verified against the sources; do not re-derive)

**graal 25.3.4.1, LLVM backend** (`substratevm/src/com.oracle.svm.core.graal.llvm/src/com/oracle/svm/core/graal/llvm/`):
- `LLVMFeature.java:91` `@Platforms({Platform.LINUX.class, Platform.DARWIN.class})`.
- `util/LLVMTargetSpecific.java:187-195` default `getTargetTriple()` returns `-unknown-darwin` or `-unknown-linux-gnu`, else throws; AMD64 prepends `x86_64` (`:318-321`).
- `LLVMNativeImageCodeCache.java`: `layoutMethods` (:131) → `writeBitcode` (per-method `f<id>.bc`) → `createBitcodeBatches` (:165, `batchSize = LLVMMaxFunctionsPerBatch` clamped to `ceil(methods/threads)`, `0` means one batch; batches are `llvm-link`ed into `b<id>.bc`) → `compileBitcodeBatches` (:191, `opt` then `llc` to `b<id>.o`, then `objectFileReader.parseStackMap` per batch) → `linkCompiledBatches` (:203: `nativeLink` = `<lld> -r -o llvm.o b*.o`; `parseCode(llvm.o)` gives per-symbol offsets in the first section whose name starts with `.text`; `llvmCleanupStackMaps` = `llvm-objcopy --remove-section=.llvm_stackmaps`; `llvmAddTextSectionSymbols` = `llvm-objcopy --add-symbol=__svm_code_section=.text:0,global --add-symbol=__svm_text_end=.text:<size>,global`; `setCodeAreaSize`). `getCCInputFiles` (:388) appends `llvm.o` to the image object list.
- `LLVMToolchainUtils.java`: `llvmCompile` (:73) runs `llc -relocation-model=pic --trap-unreachable -march=x86-64 <getLLCAdditionalOptions()> -O<n> -filetype=obj`. `nativeLink` (:122). `llvmAddTextSectionSymbols` (:174).
- `LLVMGenerator.java:293-306` `addMainFunction`: sets triple, attributes, GC `compressed-pointers`, calling convention `GraalCallingConvention` (LLVM cc 107), personality `getFunction(LLVMExceptionUnwind.getPersonalityStub(getMetaAccess()), true)` (a C-ABI declaration of the CEntryPoint stub whose symbol is the stub's `getUniqueShortName()`).
- `util/LLVMIRBuilder.java`: `LLVMIRBuilder(String name)` creates a context+module; `addFunction(name, type)`, `getFunction(name, type)` (declares external if missing), `static setSection(global, section)`, `setTarget(triple)`, `functionType(ret, args...)`, `intType()`, `rawPointerType()`, `appendBasicBlock(func, name)`, `positionAtEnd(block)`, `buildCall(callee, args...)`, `buildRet(v)`, `static getParam(func, i)`, `getBitcode()` (verifies + serializes, then `close()`), `setFunctionCallingConvention(func, cc)`. The bindings expose `LLVM.LLVMSetModuleInlineAsm2(LLVMModuleRef, String, long)`; `LLVMIRBuilder` has a private `module` field.
- `util/LLVMHelperFunctions.java`: helper functions are `LinkOnce`, `AlwaysInline`, created with `builder.addFunction`.
- `util/LLVMObjectFileReader.java:82-127` `readSection` picks the first section whose name starts with `SectionName.X.getFormatDependentName(format)` (PECOFF prefix is `.`), reads the object through the LLVM C API (COFF supported). `parseCode` (:140) uses `SectionName.TEXT`; `parseStackMap` (:156) uses `SectionName.LLVM_STACKMAPS` (`.llvm_stackmaps` on COFF; LLVM emits that section on COFF).
- `runtime/LLVMExceptionUnwind.java:91-127` personality is `@CEntryPoint(include = IncludeForLLVMOnly.class, publishAs = NotPublished)` with `InitializeReservedRegistersPrologue`; `_Unwind_Exception` is a `@CStruct(addStructKeyword = true)` with fields `exception_class`, `exception_cleanup` (:203-216); `_Unwind_Context` is an incomplete `@CStruct` (:218-220); `raiseException` = `_Unwind_RaiseException`; `getIP/getIPInfo/setIP/getRegionStart/getLanguageSpecificData` are `@CFunction`s (:222-238); `customUnwindException` (:165-171) stack-allocates the struct with `UnsafeStackValue.get(_Unwind_Exception.class)` and sets `exception_class` to the current IsolateThread.
- `util/LLVMDirectives.java`: headers `<unwind.h>`, libraries `m`.
- No unwinder link option exists on Linux/macOS; `_Unwind_*` comes from libgcc_s / libSystem implicitly.
- `hosted/image/LLVMToolchain.java:94-107` `getLLVMBinDir()` = system property `llvm.bin.dir` (set by the SVM_LLVM distribution to `<graalvm>/lib/llvm/bin/`), else `<home>/lib/llvm/bin`. `runLLVMCommand` never appends `.exe` (Windows `CreateProcess` appends it for extension-less absolute paths; the spike confirms).
- `hosted/image/CCLinkerInvocation.java:553-707` `WindowsCCLinkerInvocation.getCommand()`: `cl.exe <opts> /Fe<out> <input files...> /MD <static libs> /link /INCREMENTAL:NO /NODEFAULTLIB:LIBCMT ... /LIBPATH:... <libs>.lib advapi32.lib ... <native linker options>`. The C compiler invoker on Windows stays `WindowsCCompilerInvoker` (`cl`); `LLVMCCompilerInvoker` (clang) is only installed when `-H:+UseLLVMDataSection`.
- `hosted/FeatureImpl.java:1187` `BeforeImageWriteAccessImpl.registerLinkerInvocationTransformer(Function<LinkerInvocation, LinkerInvocation>)`; `LinkerInvocation` has `addInputFile(Path)`, `addNativeLinkerOption(String)`, `getTempDirectory()`.
- `hosted/image/NativeImage.java:444-454` symbol names `__svm_code_section` (non-layered) and `__svm_text_end`; `:499-501` the image object declares both undefined when `definesTextSectionBoundarySymbols()` is false (it is, for LLVM).
- `hosted/image/NativeImageHeap.java:125` `public final HostedMetaAccess hMetaAccess`; `NativeImageCodeCache.getImageHeap()`.
- `substratevm/mx.substratevm/mx_substratevm.py:2179-2204`: `ce_llvm_backend = mx_sdk_vm.GraalVmSvmTool(... short_name='svml', dir_name='llvm-backend', dependencies=['SubstrateVM', 'LLVM.org toolchain'], builder_jar_distributions=[SVM_LLVM, LLVM_WRAPPER_SHADOWED, JAVACPP_SHADOWED, LLVM_PLATFORM_SPECIFIC_SHADOWED, JAVACPP_PLATFORM_SPECIFIC_SHADOWED], support_distributions=['substratevm:SVM_LLVM_GRAALVM_SUPPORT'] ...)`, then `llvm_supported = not (mx.is_windows() or (mx.is_darwin() and mx.get_arch() == "aarch64"))` (:2202) and `if llvm_supported: mx_sdk_vm.register_graalvm_component(ce_llvm_backend)`.
- `substratevm/mx.substratevm/suite.py:98-179`: `LLVM_PLATFORM_SPECIFIC_SHADOWED` and `JAVACPP_PLATFORM_SPECIFIC_SHADOWED`, `urlbase = https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/native-image`; entries for linux amd64/aarch64/riscv64 and darwin amd64 have `moduleName`; darwin/aarch64 (`:127-130` and `:168-171`) has `urls` + `digest` but **no** `moduleName`; `<others>/<others>` is `{"optional": True}` (that is what Windows resolves to today). Module names follow `com.oracle.svm.shadowed.org.bytedeco.llvm.<os>.<arch>` and `com.oracle.svm.shadowed.org.bytedeco.javacpp.<os>.<arch>` with `os` in {linux, macosx, windows} and `arch` in {x86_64, arm64, riscv64}.
- `sdk/mx.sdk/suite.py:1446-1584` `LLVM_TOOLCHAIN` copies `*` from `LLVM_ORG` excluding some `bin/*` tools and `lib/*.lib`. The Windows GraalVM therefore has the whole bundle under `<graalvm>/lib/llvm/`.
- `substratevm/mx.substratevm/tool-llvm.properties` line 3: `Args=-H:CompilerBackend=llvm` (experimental option; needs `-H:+UnlockExperimentalVMOptions` and `NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL` unset).
- graal `common.json`: `mx_version` 7.85.1, `labsjdk-ce-latest` = `ce-25.0.4.1+1-jvmci-25.3-b22`.

**Oracle's shadowed jars** (inspected): relocation is `org/bytedeco/...` → `com/oracle/svm/shadowed/org/bytedeco/...` for every entry; `META-INF/native-image/**` and the original `META-INF/maven/**` are dropped (Oracle re-adds a `META-INF/maven/com.oracle.svm.shadowed.org.bytedeco/<artifact>/pom.*`, which we skip); the manifest has `Multi-Release: true`; `META-INF/versions/9/module-info.class` declares `open module <moduleName> { requires transitive <base module>; requires java.base; }` where the base module is `com.oracle.svm.shadowed.org.bytedeco.javacpp` for javacpp platform jars and `com.oracle.svm.shadowed.org.bytedeco.llvm` for llvm platform jars (verify with `javap` in Task 4). Oracle's darwin-aarch64 jars already contain a correct module-info; only the suite entries lack `moduleName`.
- Maven Central sources (all exist): `https://repo1.maven.org/maven2/org/bytedeco/llvm/13.0.1-1.5.7/llvm-13.0.1-1.5.7-windows-x86_64.jar` (62 MB), `.../javacpp/1.5.7/javacpp-1.5.7-windows-x86_64.jar` (1.3 MB); base jars for the module path: `https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/native-image/llvm-shadowed-13.0.1-1.5.7.jar` and `.../javacpp-shadowed-1.5.7.jar`; Oracle's reference platform jars `.../llvm-shadowed-13.0.1-1.5.7_1-linux-x86_64.jar` and `.../javacpp-shadowed-1.5.7_1-linux-x86_64.jar`.

**LLVM 22.1.8** (verified in `WinException.cpp`, `MCObjectFileInfo.cpp`, `X86MCAsmInfo.cpp`, `libunwind/src/*`):
- On x86_64 COFF (both msvc and gnu triples) a function with an unrecognized personality gets `.xdata` with `UNW_FLAG_EHANDLER|UNW_FLAG_UHANDLER`, the personality symbol as handler, and the **Itanium LSDA emitted right after the handler RVA inside `.xdata`** (there is no `.gcc_except_table` on Win64). Stack maps go to `.llvm_stackmaps`.
- `x86_64-w64-windows-gnu` emits `___chkstk_ms` (missing in the MSVC CRT); `x86_64-pc-windows-msvc` emits `__chkstk`. Hence the msvc triple for Java code.
- libunwind SEH mode: enabled by the compiler predefine `__SEH__` (mingw targets) via `config.h` → `_LIBUNWIND_SUPPORT_SEH_UNWIND`; `Unwind-seh.cpp` implements `_Unwind_RaiseException` (as `RaiseException(0x20474343, ...)`), `_Unwind_GetLanguageSpecificData` (returns `DISPATCHER_CONTEXT.HandlerData`, i.e. the LSDA in `.xdata`), `_Unwind_GetRegionStart`, `_GCC_specific_handler(EXCEPTION_RECORD*, void* frame, CONTEXT*, DISPATCHER_CONTEXT*, _Unwind_Personality_Fn)` which calls the Itanium personality with `version=1` and the right `_UA_*` actions. `_Unwind_GetIP/GetIPInfo/SetIP/SetGR/GetCFA` are available. Windows APIs used: `RaiseException`, `RtlUnwindEx`, `RtlVirtualUnwind`, `RtlLookupFunctionEntry`, `RtlCaptureContext` (kernel32/ntdll); CRT: `memset`, `memcpy`, `abort`, `fprintf`, `fflush`. In SEH mode `struct _Unwind_Exception` is `{ uint64 exception_class; void (*exception_cleanup)(...); uintptr_t private_[6]; }` = 64 bytes, aligned 16.
- libunwind CMake refuses `MSVC` (the cl driver) but accepts clang with `--target=x86_64-w64-windows-gnu`. Relevant options: `LIBUNWIND_ENABLE_SHARED=OFF LIBUNWIND_ENABLE_STATIC=ON LIBUNWIND_USE_COMPILER_RT=ON LIBUNWIND_ENABLE_CROSS_UNWINDING=OFF LIBUNWIND_HIDE_SYMBOLS=ON (default on Windows; keeps symbols external but not dllexport)`. `Unwind-seh.cpp` includes `<windef.h> <excpt.h> <winnt.h> <ntstatus.h>`; `unwind.h` includes `<windows.h> <ntverp.h>` under `__SEH__`, all from mingw-w64 headers.
- `CallingConv::GRAAL` (107) on x86: only reserves R14/R15 (`X86RegisterInfo.cpp`); argument lowering falls through `CC_X86_64` to `CC_X86_Win64_C` on Win64 targets, and `isCallingConvWin64(GRAAL)` is false so no 32-byte shadow area is allocated on either side of a Java-to-Java call. Self-consistent; C-ABI calls (`ccc`) use the full Win64 convention.

## File structure

gha-graal (this repo):
- `docs/journal/windows-llvm-backend.md` — the journal (Milestones, Findings, Decisions, Dead ends).
- `tests/programs/hello/Hello.java`, `tests/programs/hello/expected.txt` — round 1 program.
- `scripts/graalvm/dev-run.sh` — builds one test program with `--tool:llvm-backend` from a GraalVM home and checks its output.
- `scripts/llvm/build-unwind-win.sh` — builds libunwind (SEH mode) with the bundled clang; used by the spike and by `build.sh`.
- `scripts/llvm/build.sh`, `.github/workflows/llvm.yml` — Windows libunwind step, release `llvm-22.1.8-graal.2`.
- `.github/workflows/spike-win-eh.yml` — the round 1 spike (kept as a diagnostic).
- `scripts/jars/shadow.py`, `tests/test_shadow.py`, `.github/workflows/jars.yml` — shadowed JavaCPP jars.
- `mx-env/ce-llvm-dev`, `.github/workflows/graalvm-dev.yml` — fast iteration loop.
- `README.md` — new workflows and platform table.

graal fork, branch `graal/25.3.4.1-win-llvm` (all paths under `substratevm/`):
- `mx.substratevm/mx_substratevm.py` — `llvm_supported`.
- `mx.substratevm/suite.py` — windows-amd64 jar entries, darwin-aarch64 `moduleName`.
- `src/com.oracle.svm.core.graal.llvm/src/com/oracle/svm/core/graal/llvm/LLVMFeature.java` — platforms, Windows linker inputs.
- `.../util/LLVMTargetSpecific.java` — Windows triple.
- `.../util/LLVMDirectives.java` — no `<unwind.h>`/`m` on Windows.
- `.../runtime/LLVMExceptionUnwind.java` — `_Unwind_Exception` as a raw structure sized for SEH.
- `.../LLVMNativeImageCodeCache.java`, `.../LLVMToolchainUtils.java` — Windows object pipeline.
- `.../LLVMGenerator.java`, `.../util/LLVMHelperFunctions.java`, `.../util/LLVMIRBuilder.java` — code section placement, Windows personality shim.
- new `.../LLVMWindowsSupport.java` — everything Windows-specific in one hosted class (section names, marker/shim module generation, libunwind path).

Local checkouts (scratchpad `/private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad`, referred to as `$S` below):
- `$S/graal-upstream` — clone of oracle/graal with remote `fork` = `https://github.com/Throwaway68/graal.git`; identity already configured. Task 1 adds the worktree `$S/graal-win` on the new branch.
- `$S/graal-tag` — read-only worktree at `graal-25.3.4.1` for reference.
- `$S/llvm-sparse` — partial LLVM clone; read files with `git show llvmorg-22.1.8:<path>`.
- `/Users/aislave/Projects/gha-graal` — this repo, `main`.

Pushing with the token (works for both repos; `$GH_TOKEN` must be exported in the same command):
```bash
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push <remote> <ref>
```

---

### Task 1: Journal, test program, branches

**Files:**
- Create: `docs/journal/windows-llvm-backend.md`
- Create: `tests/programs/hello/Hello.java`, `tests/programs/hello/expected.txt`
- Create: `scripts/graalvm/dev-run.sh`
- Create: `tests/test_dev_run.sh`
- Modify: `.sync-manifest`
- graal fork: new branch `graal/25.3.4.1-win-llvm` at tag `graal-25.3.4.1` (no code change yet)

**Interfaces:**
- Produces: `dev-run.sh <graalvm-home> <program-dir> <work-dir> [extra native-image args...]` — compiles `<program-dir>/*.java`, builds `<work-dir>/app` with `--tool:llvm-backend`, runs it, diffs stdout against `<program-dir>/expected.txt`, prints `DEV-RUN OK` and exits 0 on success. Used by Task 5's workflow.
- Produces: the journal file that every later task appends to.

- [ ] **Step 1: Create the journal**

Write `docs/journal/windows-llvm-backend.md`:

```markdown
# Windows LLVM backend journal

Working notes for porting the Native Image LLVM backend to windows-x86_64.
Spec: docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md.
Every entry is dated (YYYY-MM-DD) and names the commit or workflow run it comes from.

## Milestones

- (none yet)

## Findings

- 2026-09-17 (research, no run): On x86_64 COFF, LLVM emits the Itanium LSDA into `.xdata` right after the
  personality RVA for any unrecognized personality (WinException.cpp `endFunction` → `emitExceptionTable`).
  libunwind's SEH mode returns exactly that pointer from `_Unwind_GetLanguageSpecificData`. The Java
  personality and `GCCExceptionTable` therefore need no change.
- 2026-09-17 (research): Windows images are linked by `cl.exe ... /link ...` (`WindowsCCLinkerInvocation`),
  not by lld-link. `LLVMCCompilerInvoker` (clang) is only used with `-H:+UseLLVMDataSection`.
- 2026-09-17 (research): `CallingConv::GRAAL` (107) on Win64 lowers arguments with `CC_X86_Win64_C`
  and allocates no 32-byte shadow area (`isCallingConvWin64` is false for it). Consistent on both sides
  of Java-to-Java calls; C-ABI calls use the normal Win64 convention. Verified empirically in Task 8.
- 2026-09-17 (research): `x86_64-w64-windows-gnu` emits `___chkstk_ms`; `x86_64-pc-windows-msvc` emits
  `__chkstk`. Java code targets the msvc triple; libunwind is compiled for the gnu triple (needed for
  `__SEH__`) and linked as a COFF archive.
- 2026-09-17 (research): In SEH mode `struct _Unwind_Exception` has `uintptr_t private_[6]` (64 bytes),
  not `private_1/private_2` (32 bytes). The Java-side struct must be at least 64 bytes on Windows.
- 2026-09-17 (research): Oracle's darwin-aarch64 shadowed jars already contain
  `open module com.oracle.svm.shadowed.org.bytedeco.{llvm,javacpp}.macosx.arm64`; only `moduleName`
  is missing from suite.py. That is the whole GR-34811 blocker for the macOS backend.

## Decisions

- 2026-09-17: Exception handling via libunwind SEH mode + IR shim (spec section 2). Fallback: own SEH
  unwinder, triggered by the reviewer after two failed review cycles on Task 8.
- 2026-09-17: Windows uses a single LLVM batch (one object) instead of `ld -r`; code bounds come from
  COFF grouped sections `.text$svm0` / `.text$svm1` / `.text$svm2` (spec section 3).
- 2026-09-17: The windows-x86_64 shadowed jars are referenced from suite.py by their GitHub release URL
  and sha512 directly (no lafo URL to rewrite). darwin-aarch64 only gets `moduleName` lines.

## Dead ends

- (none yet)
```

- [ ] **Step 2: Create the hello program**

`tests/programs/hello/Hello.java`:
```java
public class Hello {
    public static void main(String[] args) {
        System.out.println("Hello from the LLVM backend on " + System.getProperty("os.name"));
        System.out.println("args=" + args.length);
    }
}
```
`tests/programs/hello/expected.txt` (one line, exact):
```
args=0
```
The first line varies by OS, so `dev-run.sh` only checks that every line of `expected.txt` appears in the output.

- [ ] **Step 3: Write the failing test for dev-run.sh**

`tests/test_dev_run.sh`:
```bash
#!/usr/bin/env bash
# Exercises scripts/graalvm/dev-run.sh against a fake GraalVM home whose
# javac/native-image are shell stubs. Checks argument plumbing and output matching.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
H=$T/home; mkdir -p "$H/bin"
cat > "$H/bin/javac" <<'EOF'
#!/usr/bin/env bash
echo "javac $*" >> "$JAVAC_LOG"; touch "${@: -1}"; exit 0
EOF
cat > "$H/bin/native-image" <<'EOF'
#!/usr/bin/env bash
echo "native-image $*" >> "$NI_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '#!/usr/bin/env bash\necho "Hello from the LLVM backend on Fake"\necho "args=0"\n' > "$out"; chmod +x "$out"
EOF
chmod +x "$H/bin/javac" "$H/bin/native-image"
export JAVAC_LOG=$T/javac.log NI_LOG=$T/ni.log
out=$(bash scripts/graalvm/dev-run.sh "$H" tests/programs/hello "$T/work" -H:Extra=1 2>&1)
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: no DEV-RUN OK"; exit 1; }
grep -q -- '--tool:llvm-backend' "$NI_LOG" || { echo "FAIL: --tool:llvm-backend not passed"; exit 1; }
grep -q -- '-H:Extra=1' "$NI_LOG" || { echo "FAIL: extra args not passed"; exit 1; }
grep -q 'Hello.java' "$JAVAC_LOG" || { echo "FAIL: javac not called on the program"; exit 1; }
# Output mismatch must fail
printf 'args=7\n' > "$T/expected.txt"; mkdir -p "$T/prog"; cp tests/programs/hello/Hello.java "$T/prog/"; cp "$T/expected.txt" "$T/prog/expected.txt"
if bash scripts/graalvm/dev-run.sh "$H" "$T/prog" "$T/work2" >/dev/null 2>&1; then echo "FAIL: mismatch not detected"; exit 1; fi
echo PASS
```

- [ ] **Step 4: Run the test, expect failure**

Run: `bash tests/test_dev_run.sh`
Expected: fails because `scripts/graalvm/dev-run.sh` does not exist.

- [ ] **Step 5: Write dev-run.sh**

`scripts/graalvm/dev-run.sh`:
```bash
#!/usr/bin/env bash
# Build one test program with the Native Image LLVM backend and check its output.
#
#   dev-run.sh <graalvm-home> <program-dir> <work-dir> [extra native-image args...]
#
# <program-dir> holds *.java (main class = directory name capitalised, e.g. hello -> Hello)
# and expected.txt; every line of expected.txt must appear in the program's stdout.
set -euo pipefail
export MSYS_NO_PATHCONV=1
H=${1:?graalvm home}; P=${2:?program dir}; W=${3:?work dir}; shift 3
P=$(cd "$P" && pwd); mkdir -p "$W"; W=$(cd "$W" && pwd)

exe() { local d=$1 n=$2 c; for c in "$n" "$n.exe" "$n.cmd"; do [ -e "$d/$c" ] && { echo "$d/$c"; return 0; }; done; echo "missing $n in $d" >&2; ls "$d" >&2; return 1; }
JAVAC=$(exe "$H/bin" javac); NI=$(exe "$H/bin" native-image)

name=$(basename "$P"); main="$(tr '[:lower:]' '[:upper:]' <<<"${name:0:1}")${name:1}"
mkdir -p "$W/classes" "$W/tmp"
echo "== javac"; "$JAVAC" -d "$W/classes" "$P"/*.java
echo "== native-image (LLVM backend)"
unset NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL
"$NI" -H:+UnlockExperimentalVMOptions --tool:llvm-backend \
  -H:TempDirectory="$W/tmp" -H:+ReportExceptionStackTraces \
  "$@" -cp "$W/classes" "$main" -o "$W/app"
echo "== run"
app="$W/app"; [ -e "$app" ] || app="$W/app.exe"
"$app" > "$W/stdout.txt" 2> "$W/stderr.txt" || { echo "program exited with $?"; cat "$W/stdout.txt" "$W/stderr.txt"; exit 1; }
cat "$W/stdout.txt"
while IFS= read -r line; do
  [ -z "$line" ] && continue
  grep -qF -- "$line" "$W/stdout.txt" || { echo "missing expected line: $line" >&2; exit 1; }
done < "$P/expected.txt"
echo "DEV-RUN OK"
```

- [ ] **Step 6: Run the test, expect PASS**

Run: `bash tests/test_dev_run.sh`
Expected: `PASS`.

- [ ] **Step 7: Create the graal branch**

```bash
S=/private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad
cd $S/graal-upstream && git worktree add $S/graal-win -b graal/25.3.4.1-win-llvm graal-25.3.4.1
cd $S/graal-win && git sparse-checkout disable && git config user.name && git config user.email   # must print Throwaway68 / carpettohd@gmail.com
export GH_TOKEN=<token from your prompt>
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push fork graal/25.3.4.1-win-llvm
```
Expected: branch visible at `https://github.com/Throwaway68/graal/tree/graal/25.3.4.1-win-llvm`, tip 7b025988a9.

- [ ] **Step 8: Commit (gha-graal)**

Add the four new paths to `.sync-manifest`, then:
```bash
cd /Users/aislave/Projects/gha-graal
git add docs/journal/windows-llvm-backend.md tests/programs/hello scripts/graalvm/dev-run.sh tests/test_dev_run.sh .sync-manifest
git commit -m "Add Windows LLVM backend journal, hello program and dev-run script

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push origin main
```

---

### Task 2: Spike: libunwind SEH build and Win64 LSDA emission

**Files:**
- Create: `scripts/llvm/build-unwind-win.sh`
- Create: `.github/workflows/spike-win-eh.yml`
- Create: `tests/spike/win-eh/lsda.ll`, `tests/spike/win-eh/unwindtest.c`
- Modify: `docs/journal/windows-llvm-backend.md`, `.sync-manifest`

**Interfaces:**
- Produces: `build-unwind-win.sh <llvm-src-dir> <clang-install-dir> <out-dir>` — installs `lib/x86_64-w64-windows-gnu/libunwind.a` and `include/{unwind.h,unwind_itanium.h,libunwind.h,__libunwind_config.h}` under `<out-dir>`. Task 3 calls it from `build.sh`.
- Produces: journal entries answering: (a) is the LSDA emitted with the msvc triple, (b) libunwind's unresolved symbols, (c) can an MSVC-linked program call `_Unwind_Backtrace` through cl-compiled frames and catch `_Unwind_RaiseException` with `__try/__except`.

- [ ] **Step 1: Write the build script**

`scripts/llvm/build-unwind-win.sh`:
```bash
#!/usr/bin/env bash
# Build LLVM's libunwind in SEH mode for x86_64 Windows with the bundled clang.
#
#   build-unwind-win.sh <llvm-src-dir> <clang-install-dir> <out-dir>
#
# The library is compiled for x86_64-w64-windows-gnu (that target predefines __SEH__,
# which selects Unwind-seh.cpp) against the mingw-w64 UCRT headers from MSYS2,
# and installed as <out-dir>/lib/x86_64-w64-windows-gnu/libunwind.a plus headers.
# Native Image links it into MSVC-built images as a plain COFF archive.
set -euo pipefail
SRC=$(cygpath -m "${1:?llvm source dir}"); CLANG=$(cygpath -m "${2:?clang install dir}"); OUT=$(cygpath -m "${3:?out dir}")
MSYS=${MSYS2_ROOT:-C:/msys64}
SYSROOT=$MSYS/ucrt64

echo "== mingw-w64 UCRT headers"
"$MSYS/usr/bin/bash.exe" -lc "pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-headers-git mingw-w64-ucrt-x86_64-crt-git" 
ls "$SYSROOT/include/windows.h" "$SYSROOT/include/ntverp.h" "$SYSROOT/include/excpt.h"

TRIPLE=x86_64-w64-windows-gnu
FLAGS="-mno-stack-arg-probe -D__USE_MINGW_ANSI_STDIO=0 -D_UCRT"
rm -rf build-unwind
cmake -S "$SRC/runtimes" -B build-unwind -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OUT" \
  -DLLVM_ENABLE_RUNTIMES=libunwind \
  -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON \
  -DCMAKE_C_COMPILER="$CLANG/bin/clang.exe" -DCMAKE_CXX_COMPILER="$CLANG/bin/clang++.exe" -DCMAKE_ASM_COMPILER="$CLANG/bin/clang.exe" \
  -DCMAKE_C_COMPILER_TARGET=$TRIPLE -DCMAKE_CXX_COMPILER_TARGET=$TRIPLE -DCMAKE_ASM_COMPILER_TARGET=$TRIPLE \
  -DLLVM_DEFAULT_TARGET_TRIPLE=$TRIPLE -DLLVM_RUNTIMES_TARGET=$TRIPLE \
  -DCMAKE_SYSROOT="$SYSROOT" \
  -DCMAKE_AR="$CLANG/bin/llvm-ar.exe" -DCMAKE_RANLIB="$CLANG/bin/llvm-ranlib.exe" \
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
  -DCMAKE_C_FLAGS="$FLAGS" -DCMAKE_CXX_FLAGS="$FLAGS" \
  -DLIBUNWIND_ENABLE_SHARED=OFF -DLIBUNWIND_ENABLE_STATIC=ON \
  -DLIBUNWIND_USE_COMPILER_RT=ON -DLIBUNWIND_ENABLE_CROSS_UNWINDING=OFF \
  -DLIBUNWIND_INCLUDE_TESTS=OFF -DLIBUNWIND_INSTALL_LIBRARY=ON -DLIBUNWIND_INSTALL_HEADERS=ON
cmake --build build-unwind --target install
LIB=$(find "$OUT" -name libunwind.a | head -1)
[ -n "$LIB" ] || { echo "libunwind.a not produced" >&2; find "$OUT" -type f | head -50; exit 1; }
mkdir -p "$OUT/lib/$TRIPLE"; [ "$LIB" = "$OUT/lib/$TRIPLE/libunwind.a" ] || cp "$LIB" "$OUT/lib/$TRIPLE/libunwind.a"
echo "== defined symbols of interest"
"$CLANG/bin/llvm-nm.exe" "$OUT/lib/$TRIPLE/libunwind.a" | grep -E ' T (_Unwind_RaiseException|_GCC_specific_handler|_Unwind_GetLanguageSpecificData|_Unwind_GetRegionStart|_Unwind_GetIPInfo|_Unwind_SetIP|_Unwind_Backtrace)$'
echo "== undefined symbols (must all resolve against kernel32/ntdll/ucrt)"
"$CLANG/bin/llvm-nm.exe" --undefined-only "$OUT/lib/$TRIPLE/libunwind.a" | awk '{print $NF}' | sort -u | tee "$OUT/libunwind-undefined.txt"
```
If `-DLIBUNWIND_INSTALL_HEADERS` is not a known option in this LLVM version, drop it; headers then come from `-DLIBUNWIND_INSTALL_LIBRARY`'s default install, or copy `$SRC/libunwind/include/*.h` into `$OUT/include` manually (do that in the script as a fallback with `cp` after the build).

- [ ] **Step 2: Write the LSDA probe IR**

`tests/spike/win-eh/lsda.ll` (a function with an invoke/landingpad and a custom personality):
```llvm
target triple = "x86_64-pc-windows-msvc"

declare i32 @__svm_seh_personality(ptr, ptr, ptr, ptr)
declare void @may_throw()
declare void @handler_called()

define i32 @probe() personality ptr @__svm_seh_personality {
entry:
  invoke void @may_throw() to label %ok unwind label %lp
ok:
  ret i32 0
lp:
  %lpad = landingpad { ptr, i32 } catch ptr null
  call void @handler_called()
  ret i32 1
}
```

- [ ] **Step 3: Write the runtime probe**

`tests/spike/win-eh/unwindtest.c` (compiled with cl, linked with libunwind.a):
```c
#include <stdio.h>
#include <stdint.h>
#include <windows.h>

typedef int _Unwind_Reason_Code;
struct _Unwind_Context;
struct _Unwind_Exception { uint64_t exception_class; void (*exception_cleanup)(int, struct _Unwind_Exception*); uintptr_t private_[6]; };
typedef _Unwind_Reason_Code (*_Unwind_Trace_Fn)(struct _Unwind_Context*, void*);
_Unwind_Reason_Code _Unwind_Backtrace(_Unwind_Trace_Fn, void*);
_Unwind_Reason_Code _Unwind_RaiseException(struct _Unwind_Exception*);
uintptr_t _Unwind_GetIP(struct _Unwind_Context*);

static int frames;
static _Unwind_Reason_Code trace(struct _Unwind_Context* ctx, void* arg) {
    (void)arg; frames++; printf("  frame %d ip=%p\n", frames, (void*)_Unwind_GetIP(ctx)); return frames > 40 ? 5 /*_URC_END_OF_STACK*/ : 0; }
__declspec(noinline) static int nested(int depth) {
    if (depth == 0) { frames = 0; _Unwind_Backtrace(trace, NULL); return frames; }
    return nested(depth - 1) + 1; }
int main(void) {
    int n = nested(5);
    printf("backtrace frames=%d\n", n);
    if (n < 6) { printf("FAIL: expected at least 6 frames\n"); return 2; }
    struct _Unwind_Exception exc = {0};
    exc.exception_class = 0x4A41564100000000ull;
    __try { _Unwind_RaiseException(&exc); printf("FAIL: returned\n"); return 3; }
    __except (GetExceptionCode() == 0x20474343 ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) {
        printf("caught STATUS_GCC_THROW\n"); }
    printf("SPIKE OK\n");
    return 0;
}
```

- [ ] **Step 4: Write the spike workflow**

`.github/workflows/spike-win-eh.yml`:
```yaml
name: Spike Windows EH

on:
  workflow_dispatch:
    inputs:
      llvm_release:
        description: 'LLVM release providing the Windows bundle and the source tarball'
        default: 'llvm-22.1.8-graal.1'
        type: string

jobs:
  spike:
    runs-on: windows-2022
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v7.0.1
        with:
          path: ci
      - uses: ilammy/msvc-dev-cmd@v1.13.0
        with:
          arch: x64
      - name: Fetch LLVM bundle and source
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release download "${{ inputs.llvm_release }}" --repo "${{ github.repository }}" --pattern 'llvm-*-windows-amd64.tar.gz' --pattern 'llvm-src-*.tar.gz' --dir dl
          mkdir -p llvm llvm-src
          tar -xzf dl/llvm-*-windows-amd64.tar.gz -C llvm
          tar -xzf dl/llvm-src-*.tar.gz -C llvm-src
          ls llvm/bin | head; ls llvm-src | head
      - name: 1. LSDA emission with the msvc triple
        shell: bash
        run: |
          cd ci/tests/spike/win-eh
          ../../../../llvm/bin/llc -O2 -filetype=obj -o lsda.obj lsda.ll
          ../../../../llvm/bin/llvm-readobj --unwind lsda.obj | tee unwind.txt
          ../../../../llvm/bin/llvm-objdump -s -j .xdata lsda.obj | tee xdata.txt
          ../../../../llvm/bin/llvm-readobj --sections lsda.obj | grep -E 'Name:' | sort | uniq -c
          grep -q '__svm_seh_personality' unwind.txt && echo "personality recorded in xdata: yes"
          # UNW_FLAG_EHANDLER|UHANDLER = 3 -> Flags: 0x3
          grep -E 'Flags: 0x3|Flags: 3|ExceptionHandler|UHANDLER|EHANDLER' unwind.txt | head -3
      - name: 2. Build libunwind (SEH)
        shell: bash
        run: bash ci/scripts/llvm/build-unwind-win.sh "$GITHUB_WORKSPACE/llvm-src" "$GITHUB_WORKSPACE/llvm" "$GITHUB_WORKSPACE/unwind-out"
      - name: 3. Link and run against the MSVC CRT
        shell: cmd
        run: |
          cd ci\tests\spike\win-eh
          cl /nologo /MD /O2 unwindtest.c /Fe:unwindtest.exe /link /INCREMENTAL:NO /NODEFAULTLIB:LIBCMT %GITHUB_WORKSPACE%\unwind-out\lib\x86_64-w64-windows-gnu\libunwind.a kernel32.lib ntdll.lib
          unwindtest.exe
      - name: 4. Toolchain launch without .exe suffix
        shell: bash
        run: |
          # Java's ProcessBuilder resolves extension-less absolute paths through CreateProcess; emulate with python.
          python - <<'EOF'
          import subprocess, os
          p = os.path.join(os.environ['GITHUB_WORKSPACE'], 'llvm', 'bin', 'llc')
          print(subprocess.run([p, '--version'], capture_output=True, text=True).stdout.splitlines()[0:3])
          EOF
      - uses: actions/upload-artifact@v7.0.1
        if: always()
        with:
          name: spike-win-eh
          path: |
            ci/tests/spike/win-eh/*.txt
            ci/tests/spike/win-eh/*.obj
            unwind-out/**
```

- [ ] **Step 5: Commit and run**

```bash
cd /Users/aislave/Projects/gha-graal
git add scripts/llvm/build-unwind-win.sh .github/workflows/spike-win-eh.yml tests/spike/win-eh .sync-manifest
git commit -m "Add Windows exception-handling spike (libunwind SEH build, LSDA probe)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push origin main
gh workflow run spike-win-eh.yml -R Throwaway68/gha-graal
sleep 60; gh run list -R Throwaway68/gha-graal -w spike-win-eh.yml -L 1
gh run watch -R Throwaway68/gha-graal <run-id> --exit-status; gh run view -R Throwaway68/gha-graal <run-id> --log | grep -E '^spike' | sed 's/^[^\t]*\t[^\t]*\t//' > /tmp/spike.log
```
Iterate on the script until steps 1 to 4 pass (typical fixes: a cmake option not accepted in this LLVM version, a missing mingw header package, an unresolved symbol such as `__mingw_fprintf` or `___chkstk_ms`, which you fix by compile flags or by adding a small `compat.c` to the archive with `llvm-ar`). Each failed attempt goes into the journal as a finding, not a dead end, unless it blocks the approach.

- [ ] **Step 6: Record findings**

Append to the journal under Findings, dated, with the run URL:
- whether `.xdata` carries the personality and an LSDA for the msvc triple (quote the relevant `llvm-readobj` lines),
- the exact list of undefined symbols of `libunwind.a` (from `libunwind-undefined.txt`) and which library provides each,
- the output of `unwindtest.exe` (frame count, `caught STATUS_GCC_THROW`),
- whether `llc` launches without the `.exe` suffix.
Under Decisions: "Triple for Java code: x86_64-pc-windows-msvc (LSDA confirmed in run <url>)". Commit and push.

---

### Task 3: LLVM workflow: ship libunwind in the Windows bundle, release llvm-22.1.8-graal.2

**Files:**
- Modify: `scripts/llvm/build.sh` (windows-amd64 branch)
- Modify: `.github/workflows/llvm.yml` (default version, notes)
- Modify: `tests/test_package_llvm.sh` only if it asserts bundle contents that change (read it first)
- Modify: `README.md` (LLVM release contents), journal, `.sync-manifest`

**Interfaces:**
- Consumes: `scripts/llvm/build-unwind-win.sh` from Task 2.
- Produces: release `llvm-22.1.8-graal.2` whose Windows bundle contains `lib/x86_64-w64-windows-gnu/libunwind.a` and `include/unwind.h`. Tasks 5 to 9 use this release tag.

- [ ] **Step 1: Call the libunwind build from build.sh**

In `scripts/llvm/build.sh`, after the `if [ "$PLATFORM" = linux-amd64 ]; then ... fi` block, add:
```bash
if [ "$PLATFORM" = windows-amd64 ]; then
  echo "== libunwind (SEH mode) for the Native Image LLVM backend"
  bash "$(dirname "$0")/build-unwind-win.sh" "$SRC" "$INSTALL" "$INSTALL"
  ls -la "$INSTALL/lib/x86_64-w64-windows-gnu/" "$INSTALL/include/unwind.h"
fi
```
(`$SRC` is already the cygpath form of the llvm-project checkout; `$INSTALL` is the install prefix. Installing into `$INSTALL` puts the archive into the main Windows bundle, which `package.sh` tars unchanged.)

- [ ] **Step 2: Bump the version default and notes**

In `.github/workflows/llvm.yml`: `version` default `'22.1.8-graal.2'`; in the notes add the line `Windows: libunwind (SEH mode) under lib/x86_64-w64-windows-gnu/ for the Native Image LLVM backend.`

- [ ] **Step 3: Local check**

Run: `bash tests/test_package_llvm.sh` — Expected: `PASS` (packaging is unchanged). Run `bash -n scripts/llvm/build.sh`.

- [ ] **Step 4: Commit, push, run all three platforms**

```bash
git add scripts/llvm/build.sh .github/workflows/llvm.yml README.md docs/journal/windows-llvm-backend.md .sync-manifest
git commit -m "Ship libunwind (SEH mode) in the Windows LLVM bundle; release 22.1.8-graal.2

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push origin main
gh workflow run llvm.yml -R Throwaway68/gha-graal -f version=22.1.8-graal.2 -f publish=true
```
Wait for the run (sccache is warm: 10 to 20 min per platform; cold Windows is up to 3 h). Verify:
```bash
gh release view llvm-22.1.8-graal.2 -R Throwaway68/gha-graal --json assets -q '.assets[].name'
gh release download llvm-22.1.8-graal.2 -R Throwaway68/gha-graal --pattern 'llvm-22.1.8-graal.2-windows-amd64.tar.gz' --dir /tmp/l2 && tar -tzf /tmp/l2/llvm-22.1.8-graal.2-windows-amd64.tar.gz | grep -E 'libunwind.a|include/unwind.h'
```
Expected: 7 assets (same set as graal.1) and both paths listed. Journal milestone: "LLVM release llvm-22.1.8-graal.2 with Windows libunwind (run <url>)". Commit and push the journal.

---

### Task 4: Shadowed JavaCPP jars for windows-x86_64

**Files:**
- Create: `scripts/jars/shadow.py`
- Create: `tests/test_shadow.py`
- Create: `.github/workflows/jars.yml`
- Modify: `README.md`, journal, `.sync-manifest`

**Interfaces:**
- Produces: `shadow.py <input.jar> <output.jar> --module <name> --requires <module>` — relocates `org/bytedeco/` to `com/oracle/svm/shadowed/org/bytedeco/`, drops `META-INF/native-image/**`, `META-INF/maven/**`, `META-INF/versions/9/module-info.class`, writes a manifest with `Multi-Release: true`, and adds a freshly compiled `META-INF/versions/9/module-info.class` for `open module <name> { requires transitive <requires>; }`.
- Produces: release `jars-1.5.7-graal.1` with `llvm-shadowed-13.0.1-1.5.7-graal.1-windows-x86_64.jar`, `javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar`, `manifest.json` (sha512). Task 6 pastes the URLs and digests into suite.py.

- [ ] **Step 1: Write the failing test**

`tests/test_shadow.py`:
```python
import json, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "jars"))
import shadow  # noqa: E402


def make_input(tmp_path):
    src = tmp_path / "in.jar"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMulti-Release: true\n")
        z.writestr("META-INF/versions/9/module-info.class", b"old")
        z.writestr("META-INF/native-image/windows-x86_64/jnijavacpp/jni-config.json", "[]")
        z.writestr("META-INF/maven/org.bytedeco/javacpp/pom.xml", "<project/>")
        z.writestr("org/bytedeco/javacpp/windows-x86_64/jnijavacpp.dll", b"MZ")
    return src


def test_relocates_and_adds_module_info(tmp_path):
    src = make_input(tmp_path)
    out = tmp_path / "out.jar"
    shadow.shadow(src, out, module="com.oracle.svm.shadowed.org.bytedeco.javacpp.windows.x86_64",
                  requires=[], base_jars=[])
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "com/oracle/svm/shadowed/org/bytedeco/javacpp/windows-x86_64/jnijavacpp.dll" in names
        assert not any(n.startswith("org/bytedeco/") for n in names)
        assert not any(n.startswith("META-INF/native-image/") for n in names)
        assert not any(n.startswith("META-INF/maven/") for n in names)
        assert "META-INF/versions/9/module-info.class" in names
        assert b"Multi-Release: true" in z.read("META-INF/MANIFEST.MF")
    desc = subprocess.run(["jar", "--describe-module", "--file", str(out)], capture_output=True, text=True, check=True).stdout
    assert "com.oracle.svm.shadowed.org.bytedeco.javacpp.windows.x86_64" in desc
    assert "open" in desc.split("\n")[0] or "open " in desc


def test_manifest_json(tmp_path):
    src = make_input(tmp_path)
    m = shadow.sha512_of(src)
    assert m.startswith("sha512:") and len(m) == 7 + 128
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m pytest tests/test_shadow.py -v` — Expected: import error (module `shadow` missing).

- [ ] **Step 3: Write shadow.py**

`scripts/jars/shadow.py`:
```python
#!/usr/bin/env python3
"""Turn a JavaCPP platform jar from Maven Central into a graal "shadowed" jar.

  shadow.py <input.jar> <output.jar> --module <name> [--requires <module>]... [--base-jar <jar>]...

Relocates org/bytedeco/** to com/oracle/svm/shadowed/org/bytedeco/**, drops
META-INF/native-image, META-INF/maven and the old module-info, and adds a
module descriptor `open module <name> { requires transitive <m>; ... }` compiled
with javac against --base-jar entries on the module path.
"""
import argparse, hashlib, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

OLD = "org/bytedeco/"
NEW = "com/oracle/svm/shadowed/org/bytedeco/"
DROP = ("META-INF/native-image/", "META-INF/maven/", "META-INF/versions/9/module-info.class", "META-INF/MANIFEST.MF")
MANIFEST = "Manifest-Version: 1.0\nMulti-Release: true\nCreated-By: gha-graal shadow.py\n"


def sha512_of(path: Path) -> str:
    h = hashlib.sha512()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return "sha512:" + h.hexdigest()


def compile_module_info(module: str, requires: list, base_jars: list, workdir: Path) -> bytes:
    src = workdir / "module-info.java"
    body = "".join(f"    requires transitive {m};\n" for m in requires)
    src.write_text(f"open module {module} {{\n{body}}}\n")
    out = workdir / "classes"
    cmd = ["javac", "--release", "9", "-d", str(out)]
    if base_jars:
        cmd += ["--module-path", ":".join(str(Path(j).resolve()) for j in base_jars)]
    cmd.append(str(src))
    subprocess.run(cmd, check=True)
    return (out / "module-info.class").read_bytes()


def shadow(src: Path, dst: Path, module: str, requires: list, base_jars: list) -> None:
    with tempfile.TemporaryDirectory() as td:
        module_info = compile_module_info(module, requires, base_jars, Path(td))
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("META-INF/MANIFEST.MF", MANIFEST)
        zout.writestr("META-INF/versions/9/module-info.class", module_info)
        for info in zin.infolist():
            name = info.filename
            if name.endswith("/") or name.startswith(DROP):
                continue
            if name.startswith(OLD):
                name = NEW + name[len(OLD):]
            zout.writestr(name, zin.read(info))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path); ap.add_argument("output", type=Path)
    ap.add_argument("--module", required=True)
    ap.add_argument("--requires", action="append", default=[])
    ap.add_argument("--base-jar", action="append", default=[])
    a = ap.parse_args(argv)
    shadow(a.input, a.output, a.module, a.requires, a.base_jar)
    print(f"{a.output.name} {sha512_of(a.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, expect PASS**

Run: `python3 -m pytest tests/test_shadow.py -v` — Expected: 2 passed (needs a JDK with `javac`/`jar` on PATH; if none locally, use `JAVA_HOME` from any installed JDK 21+, for example under `/Users/aislave/Library/Java/JavaVirtualMachines` or `brew --prefix openjdk`).

- [ ] **Step 5: Confirm Oracle's module descriptors, then write jars.yml**

Read the reference descriptors so the new ones match:
```bash
cd /private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad/jars
for j in llvm-shadowed-13.0.1-1.5.7_1-linux-x86_64 javacpp-shadowed-1.5.7_1-linux-x86_64; do rm -rf mi; mkdir mi; unzip -qo $j.jar META-INF/versions/9/module-info.class -d mi; javap mi/META-INF/versions/9/module-info.class; done
```
Use the printed `requires` lines (expected: `requires transitive com.oracle.svm.shadowed.org.bytedeco.llvm` / `...javacpp`, plus `java.base`) as the `--requires` arguments below.

`.github/workflows/jars.yml`:
```yaml
name: Shadowed jars

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Release label; the release tag is jars-<version>'
        default: '1.5.7-graal.1'
        required: true
        type: string
      publish:
        default: true
        type: boolean

permissions:
  contents: write

env:
  MAVEN: https://repo1.maven.org/maven2/org/bytedeco
  LAFO: https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/native-image
  LLVM_VER: 13.0.1-1.5.7
  JAVACPP_VER: 1.5.7

jobs:
  jars:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v7.0.1
        with:
          path: ci
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: '21'
      - name: Download inputs
        run: |
          mkdir -p in base out
          curl -fsSL -o in/llvm-windows-x86_64.jar    "$MAVEN/llvm/$LLVM_VER/llvm-$LLVM_VER-windows-x86_64.jar"
          curl -fsSL -o in/javacpp-windows-x86_64.jar "$MAVEN/javacpp/$JAVACPP_VER/javacpp-$JAVACPP_VER-windows-x86_64.jar"
          curl -fsSL -o base/llvm-shadowed.jar    "$LAFO/llvm-shadowed-$LLVM_VER.jar"
          curl -fsSL -o base/javacpp-shadowed.jar "$LAFO/javacpp-shadowed-$JAVACPP_VER.jar"
          ls -la in base
      - name: Shadow
        run: |
          python3 ci/scripts/jars/shadow.py in/javacpp-windows-x86_64.jar "out/javacpp-shadowed-${{ inputs.version }}-windows-x86_64.jar" \
            --module com.oracle.svm.shadowed.org.bytedeco.javacpp.windows.x86_64 \
            --requires com.oracle.svm.shadowed.org.bytedeco.javacpp --base-jar base/javacpp-shadowed.jar
          python3 ci/scripts/jars/shadow.py in/llvm-windows-x86_64.jar "out/llvm-shadowed-13.0.1-${{ inputs.version }}-windows-x86_64.jar" \
            --module com.oracle.svm.shadowed.org.bytedeco.llvm.windows.x86_64 \
            --requires com.oracle.svm.shadowed.org.bytedeco.llvm --base-jar base/llvm-shadowed.jar --base-jar base/javacpp-shadowed.jar
          for j in out/*.jar; do jar --describe-module --file "$j" | head -3; done
          python3 ci/scripts/release_tools.py manifest out --version "${{ inputs.version }}" > manifest.json && mv manifest.json out/ && cat out/manifest.json
      - uses: actions/upload-artifact@v7.0.1
        with:
          name: jars
          path: out/*
      - name: Release
        if: ${{ inputs.publish }}
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "jars-${{ inputs.version }}" out/* --repo "${{ github.repository }}" \
            --title "Shadowed JavaCPP jars ${{ inputs.version }}" \
            --notes "JavaCPP ${JAVACPP_VER} / LLVM presets ${LLVM_VER} platform jars from Maven Central, relocated to com.oracle.svm.shadowed.org.bytedeco with module descriptors, for graal's LLVM_PLATFORM_SPECIFIC_SHADOWED and JAVACPP_PLATFORM_SPECIFIC_SHADOWED on windows-amd64. Run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
```
(Use the newest `actions/setup-java` major that exists; check with `gh api repos/actions/setup-java/releases/latest -q .tag_name` and pin that exact tag.)

- [ ] **Step 6: Commit, push, run, verify**

```bash
git add scripts/jars/shadow.py tests/test_shadow.py .github/workflows/jars.yml README.md .sync-manifest
git commit -m "Add shadowed JavaCPP jar builder and workflow for windows-x86_64

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git -c 'credential.helper=!f(){ echo "username=Throwaway68"; echo "password=$GH_TOKEN"; }; f' push origin main
gh workflow run jars.yml -R Throwaway68/gha-graal
```
After the run: `gh release view jars-1.5.7-graal.1 -R Throwaway68/gha-graal --json assets -q '.assets[].name'` shows the two jars and `manifest.json`. Download the manifest and record in the journal (Findings) the two asset URLs and sha512 digests, since Task 6 needs them verbatim. Journal milestone: "Shadowed jars release jars-1.5.7-graal.1 (run <url>)". Commit, push.

---

### Task 5: Dev workflow with build caching (validated on the pristine tag)

**Files:**
- Create: `mx-env/ce-llvm-dev`
- Create: `.github/workflows/graalvm-dev.yml`
- Modify: `README.md`, journal, `.sync-manifest`

**Interfaces:**
- Consumes: `scripts/graalvm/dev-run.sh` (Task 1), `tests/programs/<name>`, `scripts/release_tools.py urlrewrites` (existing), LLVM release from Task 3.
- Produces: `gh workflow run graalvm-dev.yml -f graal_ref=<ref> -f llvm_release=<tag> -f platform=<p> -f program=<name> -f ni_args='<args>'`; job output includes the `dev-run` step and an artifact `dev-<platform>` with `work/**` (native-image reports, `tmp/**/llvm/*.o`, `*.bc` for the failing case). Tasks 6 to 8 iterate with it.

- [ ] **Step 1: Env file**

`mx-env/ce-llvm-dev` (lean: compiler, SubstrateVM, native-image driver, LLVM backend tool, LLVM.org toolchain; only the `native-image` launcher is built natively):
```
DYNAMIC_IMPORTS=/sdk,/truffle,/compiler,/substratevm
COMPONENTS=cmp,svm,ni,nil,sdkni,svml,llp
NATIVE_IMAGES=native-image
NON_REBUILDABLE_IMAGES=
```
If `mx graalvm-show` complains about a missing component dependency, add its short name (the error names it); record the final list in the journal.

- [ ] **Step 2: Workflow**

`.github/workflows/graalvm-dev.yml`:
```yaml
name: GraalVM dev

on:
  workflow_dispatch:
    inputs:
      graal_ref:
        description: 'Ref in Throwaway68/graal'
        default: 'graal/25.3.4.1-win-llvm'
        required: true
        type: string
      llvm_release:
        description: 'LLVM release tag in this repo'
        default: 'llvm-22.1.8-graal.2'
        required: true
        type: string
      platform:
        description: 'One platform'
        default: 'windows-amd64'
        type: choice
        options: [windows-amd64, linux-amd64, darwin-aarch64]
      program:
        description: 'Directory under tests/programs'
        default: 'hello'
        type: string
      ni_args:
        description: 'Extra native-image arguments'
        default: ''
        type: string

env:
  LANG: en_US.UTF-8
  MX_GIT_CACHE: refcache
  PYTHONIOENCODING: utf-8

jobs:
  dev:
    name: ${{ inputs.platform }} / ${{ inputs.program }}
    runs-on: ${{ inputs.platform == 'windows-amd64' && 'windows-2022' || inputs.platform == 'darwin-aarch64' && 'macos-14' || 'ubuntu-22.04' }}
    timeout-minutes: 240
    steps:
      - uses: actions/checkout@v7.0.1
        with:
          path: ci
      - uses: actions/checkout@v7.0.1
        with:
          repository: Throwaway68/graal
          ref: ${{ inputs.graal_ref }}
          path: graal
          fetch-depth: 1
      - name: Derive paths
        shell: bash
        run: |
          echo "MX_PATH=$GITHUB_WORKSPACE/mx" >> "$GITHUB_ENV"
          echo "JAVA_HOME=$GITHUB_WORKSPACE/jdk" >> "$GITHUB_ENV"
          echo "MX_VERSION=$(jq -r '.mx_version' graal/common.json)" >> "$GITHUB_ENV"
          echo "JDK_ID=$(jq -r '.jdks["labsjdk-ce-latest"].version' graal/common.json)" >> "$GITHUB_ENV"
          echo "GRAAL_SHA=$(git -C graal rev-parse HEAD)" >> "$GITHUB_ENV"
          if [ "$RUNNER_OS" = Windows ]; then echo "MX_PYTHON=python" >> "$GITHUB_ENV"; else echo "MX_PYTHON=python3" >> "$GITHUB_ENV"; fi
      - uses: actions/checkout@v7.0.1
        with:
          repository: graalvm/mx
          ref: ${{ env.MX_VERSION }}
          path: mx
      - uses: actions/setup-python@v7.0.0
        with:
          python-version: '3.11'
      - name: Linux dependencies
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y build-essential cmake ninja-build zlib1g-dev
      - name: Windows MSVC environment
        if: runner.os == 'Windows'
        uses: ilammy/msvc-dev-cmd@v1.13.0
        with:
          arch: x64
      - name: Restore build cache
        uses: actions/cache@v4
        with:
          path: |
            graal/*/mxbuild
            jdk-dl
          key: dev-${{ inputs.platform }}-${{ env.JDK_ID }}-${{ env.GRAAL_SHA }}
          restore-keys: |
            dev-${{ inputs.platform }}-${{ env.JDK_ID }}-
      - name: Fetch LabsJDK
        shell: bash
        run: |
          mkdir -p "$GITHUB_WORKSPACE/jdk-dl"; cd graal
          "$MX_PATH/mx" --java-home= fetch-jdk --jdk-id labsjdk-ce-latest --to "$GITHUB_WORKSPACE/jdk-dl" --alias "$JAVA_HOME"
          if [ -d "$JAVA_HOME/Contents/Home" ]; then echo "JAVA_HOME=$JAVA_HOME/Contents/Home" >> "$GITHUB_ENV"; fi
      - name: Point graal at the LLVM release
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release download "${{ inputs.llvm_release }}" --repo "${{ github.repository }}" --pattern manifest.json --dir llvm-release --clobber
          python3 ci/scripts/release_tools.py urlrewrites llvm-release/manifest.json "${{ github.server_url }}/${{ github.repository }}/releases/download/${{ inputs.llvm_release }}" > urlrewrites.json
          echo "MX_URLREWRITES=$GITHUB_WORKSPACE/urlrewrites.json" >> "$GITHUB_ENV"
      - name: Install env file
        shell: bash
        run: cp ci/mx-env/ce-llvm-dev graal/vm/mx.vm/ce-llvm-dev
      - name: Build (Linux/macOS)
        if: runner.os != 'Windows'
        shell: bash
        run: |
          cd graal/vm
          "$MX_PATH/mx" --env ce-llvm-dev graalvm-show
          "$MX_PATH/mx" --env ce-llvm-dev build
          echo "GRAALVM_HOME=$("$MX_PATH/mx" --env ce-llvm-dev graalvm-home)" >> "$GITHUB_ENV"
      - name: Build (Windows)
        if: runner.os == 'Windows'
        shell: cmd
        run: |
          cd graal\vm
          call %MX_PATH%\mx.cmd --env ce-llvm-dev graalvm-show
          call %MX_PATH%\mx.cmd --env ce-llvm-dev build
          call %MX_PATH%\mx.cmd --env ce-llvm-dev graalvm-home > graalvm-home.txt
          set /p GRAALVM_HOME=<graalvm-home.txt
          echo GRAALVM_HOME=%GRAALVM_HOME%>>%GITHUB_ENV%
      - name: dev-run
        shell: bash
        run: bash ci/scripts/graalvm/dev-run.sh "$GRAALVM_HOME" "ci/tests/programs/${{ inputs.program }}" "$GITHUB_WORKSPACE/work" ${{ inputs.ni_args }}
      - uses: actions/upload-artifact@v7.0.1
        if: always()
        with:
          name: dev-${{ inputs.platform }}-${{ inputs.program }}
          path: |
            work/stdout.txt
            work/stderr.txt
            work/tmp/**/llvm/*.o
            work/tmp/**/llvm/*.obj
            work/tmp/**/llvm/win*.bc
            work/tmp/**/reports/**
          if-no-files-found: ignore
```

- [ ] **Step 3: Commit, push, validate on the pristine tag**

Commit (`Add GraalVM dev workflow with build caching`), push, then:
```bash
gh workflow run graalvm-dev.yml -R Throwaway68/gha-graal -f graal_ref=graal-25.3.4.1 -f llvm_release=llvm-22.1.8-graal.2 -f platform=linux-amd64
gh workflow run graalvm-dev.yml -R Throwaway68/gha-graal -f graal_ref=graal-25.3.4.1 -f llvm_release=llvm-22.1.8-graal.2 -f platform=windows-amd64
```
Expected: Linux run green with `DEV-RUN OK` (the LLVM backend already works there). Windows run fails at `dev-run` with the message about `org.graalvm.nativeimage.llvm` not being available (the tag does not register `svml` on Windows); everything before it, including the cache save, must succeed. Run the Windows job a second time and confirm "Cache restored" and a shorter build. Record both durations and run URLs in the journal.

---

### Task 6: graal branch, part A: open the backend for Windows

**Files (all in `$S/graal-win`, branch `graal/25.3.4.1-win-llvm`):**
- Modify: `substratevm/mx.substratevm/mx_substratevm.py:2201-2204`
- Modify: `substratevm/mx.substratevm/suite.py:98-179`
- Modify: `substratevm/src/com.oracle.svm.core.graal.llvm/src/com/oracle/svm/core/graal/llvm/LLVMFeature.java:91`
- Modify: `.../util/LLVMTargetSpecific.java:187-195`
- Modify: `.../util/LLVMDirectives.java`
- Modify: `.../runtime/LLVMExceptionUnwind.java:203-216`
- Modify: journal (gha-graal)

**Interfaces:**
- Consumes: jar URLs and digests from Task 4's journal entry.
- Produces: a build where `--tool:llvm-backend` on Windows enters the LLVM pipeline. Expected failure point after this task: `nativeLink` (`lld-link -r` rejected) or `llvm-objcopy --add-symbol`; Task 7 fixes those.

- [ ] **Step 1: mx gate**

Replace lines 2201-2204 of `mx_substratevm.py` with:
```python
# GR-34811: upstream excludes windows and darwin-aarch64. This branch enables both:
# darwin-aarch64 only needed moduleName entries in suite.py; windows is ported.
llvm_supported = True
if llvm_supported:
    mx_sdk_vm.register_graalvm_component(ce_llvm_backend)
```

- [ ] **Step 2: suite.py entries**

In `LLVM_PLATFORM_SPECIFIC_SHADOWED`, replace the darwin/aarch64 entry with:
```python
                    "aarch64": {
                        "urls": ["{urlbase}/llvm-shadowed-13.0.1-1.5.7-macosx-arm64.jar"],
                        "digest": "<keep the existing digest line unchanged>",
                        "moduleName": "com.oracle.svm.shadowed.org.bytedeco.llvm.macosx.arm64",
                    },
```
and add, before the final `"<others>"` block:
```python
                "windows": {
                    "amd64": {
                        "urls": ["https://github.com/Throwaway68/gha-graal/releases/download/jars-1.5.7-graal.1/llvm-shadowed-13.0.1-1.5.7-graal.1-windows-x86_64.jar"],
                        "digest": "<sha512 from the jars release manifest>",
                        "moduleName": "com.oracle.svm.shadowed.org.bytedeco.llvm.windows.x86_64",
                    },
                    "<others>": {"optional": True},
                },
```
Do the same in `JAVACPP_PLATFORM_SPECIFIC_SHADOWED` with `javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar`, module names `...javacpp.macosx.arm64` and `...javacpp.windows.x86_64`. Keep every other line byte-identical. Check with `python3 -c "import ast,sys; ast.parse(open('substratevm/mx.substratevm/suite.py').read())"`.

- [ ] **Step 3: Feature platforms and triple**

`LLVMFeature.java:91` → `@Platforms({Platform.LINUX.class, Platform.DARWIN.class, Platform.WINDOWS.class})`.

`LLVMTargetSpecific.java` default `getTargetTriple()`:
```java
    default String getTargetTriple() {
        if (Platform.includedIn(Platform.DARWIN.class)) {
            return "-unknown-darwin";
        } else if (Platform.includedIn(Platform.LINUX.class)) {
            return "-unknown-linux-gnu";
        } else if (Platform.includedIn(Platform.WINDOWS.class)) {
            /* msvc, not gnu: LLVM then emits __chkstk (MSVC CRT) instead of ___chkstk_ms. */
            return "-pc-windows-msvc";
        } else {
            throw shouldNotReachHere("Unexpected target for LLVM backend: " + ImageSingletons.lookup(Platform.class).toString());
        }
    }
```

- [ ] **Step 4: Directives**

`LLVMDirectives.java`: no `<unwind.h>` and no `m` on Windows (the MSVC compiler used for header parsing cannot see the toolchain headers, and the Java side no longer needs them after Step 5):
```java
    @Override
    public List<String> getHeaderFiles() {
        return Platform.includedIn(Platform.WINDOWS.class) ? Collections.emptyList() : Collections.singletonList("<unwind.h>");
    }

    @Override
    public List<String> getLibraries() {
        return Platform.includedIn(Platform.WINDOWS.class) ? Collections.emptyList() : Collections.singletonList("m");
    }
```
Add `import org.graalvm.nativeimage.Platform;`.

- [ ] **Step 5: `_Unwind_Exception` and `_Unwind_Context` without a header**

In `LLVMExceptionUnwind.java` replace the two struct interfaces (lines 203-220) with raw structures; the two `@CConstant`s (`_UA_SEARCH_PHASE` etc.) and `_URC_*` constants also come from the header, so replace them with the fixed Itanium values as well:
```java
    /* _Unwind_Reason_Code */
    private static int _URC_CONTINUE_UNWIND() { return 8; }
    private static int _URC_HANDLER_FOUND() { return 6; }
    private static int _URC_INSTALL_CONTEXT() { return 7; }
    private static int _URC_FATAL_PHASE1_ERROR() { return 3; }
    /* _Unwind_Action */
    private static int _UA_SEARCH_PHASE() { return 1; }
    private static int _UA_CLEANUP_PHASE() { return 2; }

    /**
     * Layout of libunwind's struct _Unwind_Exception. Declared as a raw structure so that no
     * header is needed at build time. private_ has six words on Windows (SEH mode) and two
     * elsewhere; six is a safe superset. Alignment: libunwind only reads fields through the
     * pointer, so the 16-byte C alignment is not required.
     */
    @RawStructure
    private interface _Unwind_Exception extends PointerBase {
        @RawField
        PointerBase exception_class();

        @RawField
        void set_exception_class(PointerBase value);

        @RawField
        PointerBase exception_cleanup();

        @RawField
        void set_exception_cleanup(PointerBase value);

        @RawField
        long private0();

        @RawField
        long private1();

        @RawField
        long private2();

        @RawField
        long private3();

        @RawField
        long private4();

        @RawField
        long private5();
    }

    private interface _Unwind_Context extends PointerBase {
    }
```
First read lines 183-200 to see exactly which `@CConstant` methods exist and replace all of them (the existing code has `_URC_CONTINUE_UNWIND`, `_URC_HANDLER_FOUND`, `_URC_INSTALL_CONTEXT`, `_URC_FATAL_PHASE1_ERROR`, `_UA_SEARCH_PHASE`, `_UA_CLEANUP_PHASE`; the values above are the Itanium ABI values used by both libgcc and libunwind on all three platforms). Add imports `org.graalvm.nativeimage.c.struct.RawStructure` and `org.graalvm.nativeimage.c.struct.RawField`; remove now-unused `CStruct`, `CField`, `CConstant` imports. `UnsafeStackValue.get(_Unwind_Exception.class)` works with raw structures.

- [ ] **Step 6: Compile check and dev runs**

Push the branch and run the dev workflow on Linux and Windows:
```bash
cd $S/graal-win && git add -A substratevm && git commit -m "LLVM backend: enable on Windows and darwin-aarch64, header-free unwind declarations" && git -c '<credential helper>' push fork graal/25.3.4.1-win-llvm
gh workflow run graalvm-dev.yml -R Throwaway68/gha-graal -f platform=linux-amd64
gh workflow run graalvm-dev.yml -R Throwaway68/gha-graal -f platform=windows-amd64
```
Expected: Linux `DEV-RUN OK` (proves the raw-structure and constant change is neutral). Windows: build succeeds (the windows jars download and the module gate passes), `native-image` starts the LLVM pipeline and fails inside `linkCompiledBatches` (lld-link rejects `-r`) or in `llvm-objcopy --add-symbol`. Anything earlier (a `mx build` failure, module resolution error, `llc` not found) is fixed in this task. Journal: findings with the run URLs and the exact first error line on Windows.

---

### Task 7: graal branch, part B: Windows object pipeline

**Files:**
- Create: `.../llvm/LLVMWindowsSupport.java`
- Modify: `.../LLVMNativeImageCodeCache.java` (`createBitcodeBatches`, `linkCompiledBatches`, `getCCInputFiles`)
- Modify: `.../LLVMToolchainUtils.java` (`nativeLink` guard is not needed; only callers change)
- Modify: `.../LLVMGenerator.java:293-306` (function section on Windows)
- Modify: `.../util/LLVMHelperFunctions.java` (section on helpers)
- Modify: `.../util/LLVMIRBuilder.java` (module inline asm accessor)
- Modify: `.../util/LLVMObjectFileReader.java` (exact-name section lookup)

**Interfaces:**
- Produces: `LLVMWindowsSupport` with
  - `static boolean isWindows()`,
  - `static final String CODE_SECTION = ".text$svm1"`, `START_SECTION = ".text$svm0"`, `END_SECTION = ".text$svm2"`,
  - `static byte[] buildSupportModule(String startSymbol, String endSymbol, String personalityStubName)` → bitcode for the markers and (Task 8) the SEH shim; in this task the shim part is omitted and `personalityStubName` may be null,
  - `static Path libunwindArchive()` (Task 8).
- Expected failure point after this task: link errors for `__svm_seh_personality`, `_GCC_specific_handler` and `_Unwind_*` symbols.

- [ ] **Step 1: IR builder access to module asm**

`LLVMIRBuilder.java`, next to `setTarget`:
```java
    public void setModuleInlineAsm(String asm) {
        LLVM.LLVMSetModuleInlineAsm2(module, asm, asm.length());
    }
```

- [ ] **Step 2: LLVMWindowsSupport (markers only)**

```java
package com.oracle.svm.core.graal.llvm;

import org.graalvm.nativeimage.Platform;

import com.oracle.svm.core.graal.llvm.util.LLVMIRBuilder;
import com.oracle.svm.core.graal.llvm.util.LLVMTargetSpecific;

/**
 * Windows (PE/COFF) specifics of the LLVM backend. There is no partial link on Windows, so all
 * Java code is compiled into one object whose functions live in the grouped section
 * {@code .text$svm1}. COFF linkers sort {@code .text$*} contributions by suffix, so two empty
 * marker sections define the code-section start and end symbols that the image object declares
 * as undefined (see NativeImage.getTextSectionStartSymbol/EndSymbol).
 */
public final class LLVMWindowsSupport {
    public static final String START_SECTION = ".text$svm0";
    public static final String CODE_SECTION = ".text$svm1";
    public static final String END_SECTION = ".text$svm2";

    private LLVMWindowsSupport() {
    }

    public static boolean isWindows() {
        return Platform.includedIn(Platform.WINDOWS.class);
    }

    /** Bitcode of a module holding the two marker sections (and, later, the SEH personality shim). */
    public static byte[] buildSupportModule(String startSymbol, String endSymbol) {
        LLVMIRBuilder builder = new LLVMIRBuilder("svm-windows-support");
        builder.setTarget(LLVMTargetSpecific.get().getTargetTriple());
        String asm = String.join("\n",
                        ".section " + START_SECTION + ",\"xr\"",
                        ".p2align 4",
                        ".globl " + startSymbol,
                        startSymbol + ":",
                        ".section " + END_SECTION + ",\"xr\"",
                        ".p2align 4",
                        ".globl " + endSymbol,
                        endSymbol + ":",
                        "");
        builder.setModuleInlineAsm(asm);
        return builder.getBitcode();
    }
}
```

- [ ] **Step 3: Place functions in the code section**

`LLVMGenerator.addMainFunction`, right after `builder.setFunctionLinkage(LinkageType.External);`:
```java
        if (LLVMWindowsSupport.isWindows()) {
            builder.setSection(LLVMWindowsSupport.CODE_SECTION);
        }
```
Add to `LLVMIRBuilder`: `public void setSection(String section) { LLVM.LLVMSetSection(function, section); }`.
`LLVMHelperFunctions`: in every `build*Function` right after `builder.addFunction(...)` (search for each `addFunction(` call; there are about seven), add:
```java
        if (LLVMWindowsSupport.isWindows()) {
            LLVMIRBuilder.setSection(func, LLVMWindowsSupport.CODE_SECTION);
        }
```
(import `com.oracle.svm.core.graal.llvm.LLVMWindowsSupport`).

- [ ] **Step 4: Single batch plus support module, no partial link, exact section lookup**

`LLVMNativeImageCodeCache.createBitcodeBatches`: after computing `batchSize` and before `if (batchSize == 0)`, force one batch on Windows:
```java
        if (LLVMWindowsSupport.isWindows()) {
            batchSize = 0; /* one object: there is no relocatable link on PE/COFF */
        }
```
In the same method, where the batch inputs are collected for `llvmLink`, add the support module to batch 0 on Windows:
```java
                List<String> batchInputs = IntStream.range(getBatchStart(batchId), getBatchEnd(batchId)).mapToObj(this::getBitcodeFilename).collect(Collectors.toList());
                if (LLVMWindowsSupport.isWindows() && batchId == 0) {
                    batchInputs.add(writeSupportModule());
                }
```
with
```java
    private String writeSupportModule() {
        String name = "win-support.bc";
        byte[] bitcode = LLVMWindowsSupport.buildSupportModule(NativeImage.getTextSectionStartSymbol(), NativeImage.getTextSectionEndSymbol());
        try (FileOutputStream fos = new FileOutputStream(basePath.resolve(name).toString())) {
            fos.write(bitcode);
        } catch (IOException e) {
            throw new GraalError(e);
        }
        return name;
    }
```
Note the `batchSize > 1` guard around the link loop: with one batch of N methods `batchSize == N > 1` holds for any real program, so the loop runs and the support module is linked in. `getBatchEnd` must cap at `methodIndex.length` (read it; it does today).

`linkCompiledBatches`: replace the first two statements with
```java
        List<String> compiledBatches = IntStream.range(0, numBatches).mapToObj(this::getBatchCompiledFilename).collect(Collectors.toList());
        if (LLVMWindowsSupport.isWindows()) {
            VMError.guarantee(numBatches == 1, "Windows uses a single LLVM batch");
            try {
                Files.copy(getBatchCompiledPath(0), getLinkedPath(), StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException e) {
                throw new GraalError(e);
            }
        } else {
            nativeLink(debug, getLinkedFilename(), compiledBatches, basePath, this::getFunctionName);
        }
```
and at the end replace the objcopy symbol step:
```java
        llvmCleanupStackMaps(debug, getLinkedFilename(), basePath);
        long codeAreaSize = textSectionInfo.getCodeSize();
        assert codeAreaSize <= Integer.MAX_VALUE;
        llvmCleanupRISCVAttributes(debug, getLinkedFilename(), basePath);
        if (!LLVMWindowsSupport.isWindows()) {
            llvmAddTextSectionSymbols(debug, getLinkedFilename(), NativeImage.getTextSectionStartSymbol(), NativeImage.getTextSectionEndSymbol(), codeAreaSize, basePath);
        }
        setCodeAreaSize((int) textSectionInfo.getCodeSize());
```
`getLinkedFilename()` returns `"llvm.o"`; on Windows return `"llvm.obj"` so `cl.exe` treats it as an object:
```java
    private static String getLinkedFilename() {
        return LLVMWindowsSupport.isWindows() ? "llvm.obj" : "llvm.o";
    }
```

`LLVMObjectFileReader.parseCode`: on Windows the code section must be matched exactly (COMDAT helper sections are also named `.text`, and the markers are `.text$svm0/2`). Change `readSection` to take a `String sectionPrefix` instead of a `SectionName`, and pass `LLVMWindowsSupport.isWindows() ? LLVMWindowsSupport.CODE_SECTION : SectionName.TEXT.getFormatDependentName(ObjectFile.getNativeFormat())` from `parseCode`, and `SectionName.LLVM_STACKMAPS.getFormatDependentName(...)` from `parseStackMap`. Keep the `startsWith` test; `.text$svm1` is not a prefix of `.text$svm0` or `.text$svm2`.

- [ ] **Step 5: Push and dev-run**

Commit `LLVM backend: single-object pipeline with COFF grouped-section markers on Windows`, push the branch, run the dev workflow on Windows and Linux. Expected: Linux `DEV-RUN OK` (nothing changed there; verify the diff is guarded). Windows: `llc` produces `b0.o`, `parseCode` succeeds, stack maps are removed, `cl.exe` runs and fails with `LNK2019: unresolved external symbol __svm_seh_personality` / `_Unwind_RaiseException` (or `_GCC_specific_handler`). If instead it fails earlier, fix here. Download the artifact and check the object:
```bash
# from the dev artifact, on the Mac (llvm tools from brew llvm or the darwin bundle):
llvm-readobj --sections llvm.obj | grep -E 'Name: \.text' | sort | uniq -c   # expect .text$svm0, .text$svm1, .text$svm2 (+ possibly COMDAT .text)
llvm-nm llvm.obj | grep -E '__svm_code_section|__svm_text_end'
```
Journal: findings (section listing, first link error).

---

### Task 8: graal branch, part C: SEH personality shim and libunwind link; first green hello world

**Files:**
- Modify: `.../LLVMWindowsSupport.java` (shim in the support module, libunwind path)
- Modify: `.../LLVMNativeImageCodeCache.java` (`writeSupportModule` passes the stub name)
- Modify: `.../LLVMGenerator.java:305` (personality on Windows)
- Modify: `.../LLVMFeature.java` (`beforeImageWrite`: add `unwind.lib` to the link)
- Modify: journal, `README.md` (gha-graal)

**Interfaces:**
- Consumes: `libunwind.a` at `<graalvm>/lib/llvm/lib/x86_64-w64-windows-gnu/libunwind.a` (Task 3); `LLVMToolchain.getLLVMBinDir()`.
- Produces: green `DEV-RUN OK` on windows-amd64 for `hello`.

- [ ] **Step 1: Shim in the support module**

`LLVMWindowsSupport.buildSupportModule(String startSymbol, String endSymbol, String personalityStubName)`: after the inline asm, add the SEH shim. Windows calls an exception handler as `EXCEPTION_DISPOSITION handler(EXCEPTION_RECORD*, void* frame, CONTEXT*, DISPATCHER_CONTEXT*)`; libunwind's `_GCC_specific_handler` takes those four plus the Itanium personality:
```java
    public static final String SEH_PERSONALITY = "__svm_seh_personality";

    public static byte[] buildSupportModule(String startSymbol, String endSymbol, String personalityStubName) {
        LLVMIRBuilder builder = new LLVMIRBuilder("svm-windows-support");
        builder.setTarget(LLVMTargetSpecific.get().getTargetTriple());
        builder.setModuleInlineAsm(markerAsm(startSymbol, endSymbol));

        LLVMTypeRef ptr = builder.rawPointerType();
        LLVMTypeRef i32 = builder.intType();
        /* int personality(int version, int actions, uint64 exceptionClass, _Unwind_Exception*, _Unwind_Context*) */
        LLVMTypeRef personalityType = builder.functionType(i32, i32, i32, builder.longType(), ptr, ptr);
        LLVMValueRef javaPersonality = builder.getFunction(personalityStubName, personalityType);
        /* EXCEPTION_DISPOSITION _GCC_specific_handler(EXCEPTION_RECORD*, void*, CONTEXT*, DISPATCHER_CONTEXT*, _Unwind_Personality_Fn) */
        LLVMValueRef gccHandler = builder.getFunction("_GCC_specific_handler", builder.functionType(i32, ptr, ptr, ptr, ptr, ptr));

        LLVMValueRef shim = builder.addFunction(SEH_PERSONALITY, builder.functionType(i32, ptr, ptr, ptr, ptr));
        LLVMIRBuilder.setLinkage(shim, LLVMIRBuilder.LinkageType.External);
        LLVMIRBuilder.setSection(shim, CODE_SECTION);
        LLVMBasicBlockRef block = builder.appendBasicBlock(shim, "entry");
        builder.positionAtEnd(block);
        LLVMValueRef result = builder.buildCall(gccHandler,
                        LLVMIRBuilder.getParam(shim, 0), LLVMIRBuilder.getParam(shim, 1),
                        LLVMIRBuilder.getParam(shim, 2), LLVMIRBuilder.getParam(shim, 3), javaPersonality);
        builder.buildRet(result);
        return builder.getBitcode();
    }
```
Read `LLVMIRBuilder.buildCall` first: if it sets the Graal calling convention on calls, use the variant that keeps the default C convention (or set `LLVM.LLVMSetInstructionCallConv(call, LLVM.LLVMCCallConv)` explicitly). Both `_GCC_specific_handler` and the Java personality stub are C-ABI functions.

The shim is placed in `.text$svm1` so that it lies inside the image code range; it is never a Java frame, and libunwind never unwinds through it, so this is only about symbol tidiness. If `parseCode`'s "same offset" guarantee (`VMError.guarantee(offset < nextFunctionStartOffset ...)`) trips because the shim's symbol is in the section but not a Java method, filter non-method symbols in `linkCompiledBatches` (it already looks symbols up by method name, so unknown extra symbols are ignored; verify).

- [ ] **Step 2: Wire the stub name**

`LLVMNativeImageCodeCache.writeSupportModule`:
```java
        String stubName = ((HostedMethod) LLVMExceptionUnwind.getPersonalityStub(getImageHeap().hMetaAccess)).getUniqueShortName();
        byte[] bitcode = LLVMWindowsSupport.buildSupportModule(NativeImage.getTextSectionStartSymbol(), NativeImage.getTextSectionEndSymbol(), stubName);
```
(`getPersonalityStub` takes a `MetaAccessProvider`; `HostedMetaAccess` is one, and it returns the `HostedMethod` of the stub.)

- [ ] **Step 3: Personality on Windows**

`LLVMGenerator.addMainFunction`:
```java
        if (LLVMWindowsSupport.isWindows()) {
            builder.setPersonalityFunction(builder.getFunction(LLVMWindowsSupport.SEH_PERSONALITY,
                            builder.functionType(builder.intType(), builder.rawPointerType(), builder.rawPointerType(), builder.rawPointerType(), builder.rawPointerType())));
        } else {
            builder.setPersonalityFunction(getFunction(LLVMExceptionUnwind.getPersonalityStub(getMetaAccess()), true));
        }
```

- [ ] **Step 4: Link libunwind**

`LLVMWindowsSupport`:
```java
    /** libunwind (SEH mode) shipped in the Windows LLVM toolchain bundle. */
    public static Path libunwindArchive() {
        return LLVMToolchain.getLLVMBinDir().getParent().resolve(Path.of("lib", "x86_64-w64-windows-gnu", "libunwind.a"));
    }
```
`LLVMFeature`:
```java
    @Override
    public void beforeImageWrite(BeforeImageWriteAccess access) {
        if (!LLVMWindowsSupport.isWindows()) {
            return;
        }
        Path archive = LLVMWindowsSupport.libunwindArchive();
        if (!Files.isRegularFile(archive)) {
            throw UserError.abort("The LLVM toolchain at %s does not contain libunwind (SEH mode), which the LLVM backend needs on Windows: %s", LLVMToolchain.getLLVMBinDir(), archive);
        }
        ((BeforeImageWriteAccessImpl) access).registerLinkerInvocationTransformer(inv -> {
            /* cl.exe forwards *.lib inputs to link.exe as libraries; keep the .lib name. */
            Path lib = inv.getTempDirectory().resolve("unwind.lib");
            try {
                Files.copy(archive, lib, StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException e) {
                throw UserError.abort(e, "Cannot copy %s", archive);
            }
            inv.addInputFile(lib);
            inv.addNativeLinkerOption("ntdll.lib");
            return inv;
        });
    }
```
(imports: `java.nio.file.*`, `com.oracle.svm.hosted.FeatureImpl.BeforeImageWriteAccessImpl`, `com.oracle.svm.hosted.image.LLVMToolchain`, `com.oracle.svm.core.util.UserError` or the package the file already uses for `UserError`). Add any further `.lib` the spike's undefined-symbol list required (Task 2 journal entry).

- [ ] **Step 5: Push and dev-run until green**

Commit `LLVM backend: SEH personality shim and libunwind link on Windows`, push, run the Windows dev workflow. Expected outcomes and what to do:
- Link succeeds, `app.exe` prints both lines, `DEV-RUN OK`: done.
- Link succeeds, the program crashes at startup (exit code 0xC0000005 or similar): the first Java code runs through `__svm_code_section` bounds and the calling convention. Check with `-H:+PrintImageSymbols`-style diagnostics or `dumpbin /symbols app.exe | findstr __svm_code_section` (add a step to `dev-run.sh` on Windows printing `dumpbin /headers` of `app.exe` and `llvm-nm` of `llvm.obj` when the run fails). Compare the address of `__svm_code_section` with the first Java method symbol: they must be equal; if the linker dropped the empty marker section, give `.text$svm0` a single `int3` plus `.p2align 4` and add 16 to every offset in `parseCode` on Windows (`LLVMWindowsSupport.CODE_OFFSET = 16`).
- Unresolved symbols: add the providing `.lib` to `addNativeLinkerOption` or, for mingw-only symbols, compile a `compat.c` into `unwind.lib` in `build-unwind-win.sh` (Task 2 already lists the exact set).
- Run the Linux dev workflow once more at the end: must stay `DEV-RUN OK`.

Reviewer gate for the fallback decision (spec section 2): if after two review cycles the link still fails inside libunwind or the personality is never reached, the reviewer writes the decision to the journal and the next task becomes "own SEH unwinder".

- [ ] **Step 6: Journal milestone**

Milestone: "Hello world runs on windows-amd64 with the LLVM backend (dev run <url>, graal commit <sha>)". Findings: exact marker/offset outcome, final linker inputs, calling-convention observation (did any Java method with more than four arguments run; hello world exercises many).

---

### Task 9: Round 1 release and docs

**Files:**
- Modify: `.github/workflows/graalvm.yml` (defaults: `graal_ref` → `graal/25.3.4.1-win-llvm`, `llvm_release` → `llvm-22.1.8-graal.2`; notes text)
- Modify: `README.md` (workflows table, platform status table: windows backend "yes, round 1"; darwin "yes if the smoke test passes, else unchanged"), journal, `.sync-manifest`

- [ ] **Step 1: Defaults and notes**

Update the two defaults and change the release notes line to `Native Image LLVM backend: linux-amd64, windows-amd64 (round 1, hello world), darwin-aarch64 (moduleName fix for GR-34811).`

- [ ] **Step 2: Full release build**

```bash
gh workflow run graalvm.yml -R Throwaway68/gha-graal -f graal_ref=graal/25.3.4.1-win-llvm -f llvm_release=llvm-22.1.8-graal.2 -f label=round1-win-llvm -f publish=true
```
The existing `smoke.sh` builds and runs a hello world with `--tool:llvm-backend` on every platform where the tool directory exists, so it now exercises Windows and macOS too. Expected: three green jobs and release `graalvm-round1-win-llvm`. If darwin fails in the LLVM backend step, that is a finding for round 2, not a blocker: rerun with `platforms=linux-amd64,windows-amd64` for the release and journal the macOS error.

- [ ] **Step 3: README and journal**

README: add `graalvm-dev.yml`, `jars.yml`, `spike-win-eh.yml` to the workflows section with one line each; update the platform table; add "Branch plumbing" note that `graal/25.3.4.1-win-llvm` is the Windows backend branch. Journal milestone: "Round 1 release graalvm-round1-win-llvm (run <url>)" with per-platform smoke outcome. Commit, push. Update `.sync-manifest`.

## Self-review notes

- Spec coverage: section 1 (Task 1, 6), section 2 (Tasks 2, 3, 8), section 3 (Task 7), section 4 (Tasks 4, 6), section 5 (Tasks 1, 5, 9), section 6 (process; every task has a verification and a journal step). The spec's "jars via URL rewrites" is replaced by direct release URLs in suite.py, recorded as a decision in Task 1's journal.
- Type consistency: `LLVMWindowsSupport.buildSupportModule` grows from two to three parameters between Task 7 and Task 8; Task 8 Step 2 updates the only caller. `dev-run.sh` signature is identical in Tasks 1 and 5.
