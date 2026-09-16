# gha-graal

GitHub Actions builds of a GraalVM-patched LLVM 22.1.8 toolchain and GraalVM CE 25.3.4.1
(LLVM.org toolchain, Sulong LLVM runtime, Native Image LLVM backend) for
linux-amd64, windows-amd64 and darwin-aarch64. Design: `docs/superpowers/specs/2026-09-16-graal-llvm-ci-design.md`.

## Inputs

| Repo | Branch | What |
|------|--------|------|
| `Throwaway68/llvm-project` | `graal/22.1.8` | llvmorg-22.1.8 + the four patches from graal's `sdk/llvm-patches` |
| `Throwaway68/graal` | `graal/25.3.4.1-ci` | graal-25.3.4.1 + LLVM backend registered on darwin-aarch64 |

## Workflows

**LLVM toolchain** (`llvm.yml`): `gh workflow run llvm.yml -f llvm_ref=graal/22.1.8 -f version=22.1.8-graal.1`.
Publishes release `llvm-<version>` with `llvm-<version>-<platform>.tar.gz`,
`compiler-rt-<version>-linux-amd64.tar.gz`, `llvm-src-<version>.tar.gz`,
`llvm-lldonly-<version>-darwin-aarch64.tar.gz` and `manifest.json` (sha512).

**GraalVM** (`graalvm.yml`): `gh workflow run graalvm.yml -f graal_ref=graal/25.3.4.1-ci -f llvm_release=llvm-22.1.8-graal.1`.
Builds any graal ref against the LLVM release: graal's downloads from
`lafo.ssw.uni-linz.ac.at/pub/llvm` are redirected with `MX_URLREWRITES`
(pattern + digest override), so no suite file is edited. Publishes release
`graalvm-<label>` with a `.tar.gz` per Unix platform, a `.zip` for Windows,
and `manifest.json`.

## Building your own branches

1. Push a branch to `Throwaway68/graal` (any base). Run `graalvm.yml` with `graal_ref=<branch>`.
2. To change LLVM, push a branch to `Throwaway68/llvm-project`, run `llvm.yml` with
   `llvm_ref=<branch>` and a new `version`, then pass that `llvm_release` to `graalvm.yml`.
3. The Native Image LLVM backend is registered by `substratevm/mx.substratevm/mx_substratevm.py`
   (`llvm_supported`, GR-34811). Windows has no backend code path yet; when a branch adds it,
   drop the Windows exclusion there and the smoke test picks the backend up automatically
   (it checks for `lib/svm/tools/llvm-backend`).

## Local checks

    python3 -m pytest tests -q
    bash tests/test_package_llvm.sh && bash tests/test_package_graalvm.sh
