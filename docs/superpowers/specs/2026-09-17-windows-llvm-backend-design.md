# Windows LLVM Backend for Native Image: Design

Date: 2026-09-17. Status: approved by the user in chat.

## Goal

Make `native-image --tool:llvm-backend` produce working executables on windows-x86_64, built from a branch of the user's graal fork through the CI in this repository. Work proceeds in four rounds, each ending in a distributable build:

1. Hello world built with the LLVM backend runs and exits 0 on Windows.
2. A program that throws and catches exceptions across frames, allocates enough to trigger GC, and runs several threads works.
3. The substratevm LLVM test gate passes on Windows.
4. A complex program runs, including JNI in both directions: the image calls into a DLL built by the bundled clang, and native code calls back into the image.

This spec covers the architecture for all rounds and the concrete scope of round 1. Rounds 2 to 4 get their own plan documents after the previous round closes, because their content depends on what the earlier round finds.

## Constraints and decisions already made

- Base: graal tag `graal-25.3.4.1`, LLVM release `llvm-22.1.8-graal.1` from this repository (LLVM 22.1.8 plus graal's four patches).
- The Windows images may depend on anything that yields a standard Win64 PE executable. The bundled `lld-link` may be the linker, and the GraalVM distribution may ship its own unwinder and support objects. MSVC-built JNI DLLs must still load and call fine, which the Win64 ABI guarantees.
- The GRAAL calling convention is verified empirically in round 1, not assumed to be a blocker; AArch64 and RISC-V work without a variant.
- Git identity for commits in the user's repos: `Throwaway68 <carpettohd@gmail.com>`, configured locally in each checkout. Never anything else, never chosen by Claude.
- The GitHub token is only ever exported as `GH_TOKEN` in shell commands, never written to a file, workflow or log.
- Test bed: GitHub-hosted windows-2022 runners. No local Windows VM (the host is Apple Silicon).

## Facts from the 25.3.4.1 source

- `LLVMExceptionUnwind` raises exceptions with `_Unwind_RaiseException` and runs a Java personality function that parses the Itanium LSDA via `GCCExceptionTable`. It expects libunwind's two-phase protocol and the `_Unwind_*` context accessors.
- `LLVMToolchainUtils.nativeLink` merges per-batch objects with `<lld> -r`; `llvmCleanupStackMaps` removes the stack-map section with `llvm-objcopy`; `llvmAddTextSectionSymbols` adds code-section start and end symbols with `llvm-objcopy --add-symbol`, which only works on ELF.
- `LLVMObjectFile.getLld` already maps PECOFF to `lld-link`.
- `LLVMFeature` is annotated `@Platforms({LINUX, DARWIN})`; `mx_substratevm.py` excludes Windows via `llvm_supported`; the suite has no windows-x86_64 entries in `LLVM_PLATFORM_SPECIFIC_SHADOWED` and `JAVACPP_PLATFORM_SPECIFIC_SHADOWED`, and its darwin-aarch64 entries lack `moduleName` (GR-34811), which is what blocked the macOS backend earlier.

## 1. Where the work lives

- graal fork branch `graal/25.3.4.1-win-llvm`, based on the pristine tag. All backend, runtime and mx changes go there.
- llvm fork branch `graal/22.1.8-win`, only if LLVM itself needs a change. The LLVM workflow gains a Windows libunwind build either way and publishes it as release `llvm-22.1.8-graal.2`.
- This repository: the journal, a `jars.yml` workflow, a `graalvm-dev.yml` workflow, and test programs under `tests/programs/`.
- Journal at `docs/journal/windows-llvm-backend.md` with four fixed sections: Milestones, Findings, Decisions, Dead ends. Each entry is dated and names the commit or workflow run it came from. Every task's definition of done includes its journal entry.

## 2. Exception handling

Approach chosen: reuse libunwind's SEH mode.

- LLVM's libunwind has a Windows x86_64 backend (`Unwind-seh.cpp`, enabled by `__SEH__`) that drives `RtlVirtualUnwind` and `RtlUnwindEx` and exposes the ordinary `_Unwind_RaiseException` API, the `_Unwind_Get*`/`_Unwind_Set*` accessors, and `_GCC_specific_handler`, the adapter that lets an Itanium personality run under Windows structured exception handling.
- The LLVM workflow builds libunwind for Windows with the just-built clang against the runner's mingw-w64 headers (MSYS2 is preinstalled on windows-2022) and ships `libunwind.a` plus its headers inside the Windows toolchain bundle under `lib/clang-runtimes/` or an equivalent documented path.
- On Windows the backend registers as the personality of each LLVM function a small C shim, compiled into the image's support objects, that calls `_GCC_specific_handler` with the existing Java personality as the inner handler. The Java unwinder and `GCCExceptionTable` stay as they are.
- Codegen targets the `x86_64-pc-windows-msvc` triple if LLVM emits the Itanium LSDA for non-MSVC personalities there; otherwise `x86_64-w64-windows-gnu`. The round-1 spike settles this and the journal records the reason. If the gnu triple is chosen, compiler-rt builtins for Windows are added to the bundle for `___chkstk_ms` and friends.
- Fallback trigger: if after two review cycles libunwind still cannot be linked into an MSVC-built image or cannot walk through MSVC-compiled frames, the reviewer flags it and the work switches to an own SEH unwinder in the SVM runtime (a port of the two-phase logic in `Unwind-seh.cpp` on top of the Windows unwind APIs). That decision goes into the journal's Decisions section.

## 3. Object pipeline on Windows

- No partial link: `nativeLink` is skipped on Windows and the per-batch objects are handed to the final image link as a list.
- Code-section bounds via COFF grouped sections: LLVM functions are placed in `.text$svm`; two marker objects define the start symbol in `.text$svm0` and the end symbol in `.text$svmz`. COFF linkers sort `.text$*` contributions by suffix, so the markers bracket the code. Verification: at runtime read both symbols and check that every compiled method's address lies between them.
- Stack-map removal stays with `llvm-objcopy --remove-section`, which supports COFF. If the existing stack-map reader cannot parse COFF objects, it gets a COFF path.
- The GRAAL calling convention is checked in round 1 by calling between LLVM-compiled Java methods and the MSVC-compiled runtime in both directions.

## 4. Build plumbing

- On the branch: `LLVMFeature` gains `Platform.WINDOWS`, `mx_substratevm.py` no longer excludes Windows, and the suite gets windows-x86_64 entries for both shadowed jar libraries with `moduleName` set.
- New workflow `jars.yml` in this repository: downloads the JavaCPP LLVM and JavaCPP artifacts for windows-x86_64 and darwin-aarch64 from Maven Central at the version graal's shadowed jars are built from, relocates packages the way graal's shadowed jars do, adds module descriptors with the same module names as the Linux jars, and publishes them as release `jars-<version>` with a sha512 manifest. The Linux jars from graal's LLVM release are the reference for package and module names.
- The graalvm workflows extend their URL rewrites to cover the jars release, using the existing `release_tools.py` mechanism.
- Side effect, not a goal: the modular darwin-aarch64 jars remove the GR-34811 blocker for the macOS backend.

## 5. Testing and iteration

- New workflow `graalvm-dev.yml`: inputs graal ref, llvm release, jars release, platform, and test program. It checks out the graal ref, restores cached mx build outputs and the labs JDK keyed by ref and platform, builds incrementally with mx, builds the chosen test program with `--tool:llvm-backend` straight from the build tree (`mx native-image`), runs it, and uploads logs and failing artifacts. Target: under 15 minutes per warm Windows iteration.
- Test programs under `tests/programs/`, one per round: `hello` (round 1); `runtime` with exceptions across frames, allocation pressure and threads (round 2); the substratevm LLVM gate via mx (round 3); `complex` with JNI in both directions using a DLL built by the bundled clang (round 4).
- Each round ends with a green dev run on Windows and a full release build from `graalvm.yml` tagged with the round name, so every milestone has a distributable.

## 6. Process

- Subagent-driven development. Implementer subagents run on Opus 5; reviewer subagents, for spec review and code review, run on Fable 5.1. A review blocks the next task.
- Every task is small, has a stated verification (a dev-workflow run or a local test), and ends with a commit and a journal entry. A task that hits a dead end records it in the journal and stops instead of thrashing.
- Subagents receive the journal and this spec as context.

## Round 1 scope

Exit criterion: `hello` built with the LLVM backend runs and exits 0 on a windows-2022 runner, from a release build.

Contents, in dependency order:

1. Journal and test program scaffolding in this repository.
2. Spike: does LLVM 22 emit the Itanium LSDA with the msvc triple for an unknown personality, and does libunwind's SEH mode build with clang on the runner. Output: triple decision and libunwind build recipe, both in the journal.
3. LLVM workflow: Windows libunwind (and compiler-rt builtins if needed) in the bundle; release `llvm-22.1.8-graal.2`.
4. `jars.yml` and the windows-x86_64 and darwin-aarch64 modular jars; release.
5. graal branch: feature and mx gate, suite entries, Windows object pipeline (no partial link, grouped-section markers, COFF stack maps), personality shim and libunwind linking.
6. `graalvm-dev.yml` with caching; first green hello world on Windows.
7. Release build tagged for round 1.

## Out of scope for round 1

Exceptions, GC, threads, the test gate, JNI, and the macOS backend. Anything discovered about them goes into the journal's Findings section for the next round's plan.
