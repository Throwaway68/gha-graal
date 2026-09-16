# GraalVM 25.3.4.1 + LLVM 22.1.8 CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Actions workflows in a new repo `Throwaway68/gha-graal` that build a patched LLVM 22.1.8 toolchain and GraalVM CE 25.3.4.1 (with LLVM toolchain, Sulong and the Native Image LLVM backend) for linux-amd64, windows-amd64 and darwin-aarch64, publishing both as GitHub Releases.

**Architecture:** Two `workflow_dispatch` workflows. `llvm.yml` builds the LLVM bundles from a branch of `Throwaway68/llvm-project` and publishes release `llvm-<version>` with a sha512 manifest. `graalvm.yml` builds GraalVM from any ref of `Throwaway68/graal`, redirecting graal's LLVM downloads to that release through mx URL rewrites (`MX_URLREWRITES`, with digest overrides), so no graal suite file is ever edited. Helper scripts live in `scripts/`, the mx env file in `mx-env/`.

**Tech Stack:** GitHub Actions (free-plan hosted runners), bash, Python 3 (pytest for the helper module), CMake + Ninja + sccache for LLVM, mx 7.85.1 + LabsJDK 25 for GraalVM, `gh` CLI for releases.

**Spec:** `docs/superpowers/specs/2026-09-16-graal-llvm-ci-design.md`

## Global Constraints

- GitHub user: `Throwaway68`. Forks: `Throwaway68/llvm-project`, `Throwaway68/graal`. New repo: `Throwaway68/gha-graal` (public), created from this working directory `/Users/aislave/Projects/gha-graal`.
- Authentication for local `gh` and `git push`: `export GH_TOKEN=<the token the user provided in chat>`. The token must never be written into any file, commit, workflow or log.
- LLVM base: tag `llvmorg-22.1.8`. Graal base: tag `graal-25.3.4.1`. mx version: `7.85.1` (read from `graal/common.json`, never hardcode in workflows). JDK: `labsjdk-ce-latest` via `mx fetch-jdk`.
- LLVM branch in fork: `graal/22.1.8`. Graal branch in fork: `graal/25.3.4.1-ci`.
- Platforms and runners: `linux-amd64` on `ubuntu-22.04`, `darwin-aarch64` on `macos-14`, `windows-amd64` on `windows-2022`. Job timeout 360 minutes.
- Asset names must mirror Oracle's: `llvm-<version>-<platform>.tar.gz`, `compiler-rt-<version>-linux-amd64.tar.gz`, `llvm-src-<version>.tar.gz`, `llvm-lldonly-<version>-darwin-aarch64.tar.gz`. Tarballs have no top-level directory. Default `<version>` = `22.1.8-graal.1`.
- LLVM build: projects `clang;lld`, targets `X86;AArch64`, Release, no flang/MLIR, runtimes `compiler-rt;libunwind;libcxxabi;libcxx` on Linux and macOS only, sanitizers off, zlib/zstd/libxml2 off.
- Pinned action versions: `actions/checkout@v7.0.1`, `actions/upload-artifact@v7.0.1`, `actions/download-artifact@v8.0.1`, `actions/setup-python@v7.0.0`, `mozilla-actions/sccache-action@v0.0.11`, `ilammy/msvc-dev-cmd@v1.13.0`.
- Commits in `gha-graal` end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Author for git commits: `Throwaway68 <carpettohd@gmail.com>` via `-c user.name -c user.email` when the global git config is not set.
- After finishing, update `.sync-manifest` in the repo root with every created or modified file, one relative path per line.

---

## File structure

```
gha-graal/
├── .github/workflows/llvm.yml          # builds + releases the LLVM bundles
├── .github/workflows/graalvm.yml       # builds + releases GraalVM
├── scripts/llvm/build.sh               # cmake configure/build/install for one platform
├── scripts/llvm/package.sh             # packs the tarballs Oracle's layout expects
├── scripts/graalvm/smoke.sh            # java/native-image/lli/LLVM-backend smoke tests
├── scripts/graalvm/package.sh          # packs the GraalVM home into tar.gz / zip
├── scripts/release_tools.py            # `manifest` (sha512) and `urlrewrites` (MX_URLREWRITES) subcommands
├── mx-env/ce-llvm-ci                   # mx env file copied into graal/vm/mx.vm at build time
├── tests/test_release_tools.py         # pytest for release_tools.py
├── tests/test_package_llvm.sh          # local test of scripts/llvm/package.sh on a fake tree
├── tests/test_package_graalvm.sh       # local test of scripts/graalvm/package.sh on a fake tree
├── README.md                           # how to run the workflows and plumb new branches
├── docs/superpowers/specs/...          # spec (exists)
└── docs/superpowers/plans/...          # this plan
```

Each script has one responsibility and takes explicit positional arguments so it can be run locally without GitHub Actions.

---

### Task 1: LLVM fork branch `graal/22.1.8`

**Files:**
- Remote only: branch `graal/22.1.8` in `Throwaway68/llvm-project`.
- Uses the scratchpad sparse clone `/private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad/llvm-sparse` (a `--depth 1 --filter=blob:none` clone of `llvmorg-22.1.8` with the patched files sparse-checked-out) and the patches saved in `.../scratchpad/patches/000{1,2,3,4}-*.patch`. If the scratchpad is gone, recreate it with the commands in Step 1.

**Interfaces:**
- Produces: git ref `graal/22.1.8` = `llvmorg-22.1.8` + 4 commits, consumed by `llvm.yml` (Task 6) as `inputs.llvm_ref`.

- [ ] **Step 1: Ensure the sparse clone and patches exist**

```bash
SP=/private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad
export GH_TOKEN=<token>
if [ ! -d "$SP/llvm-sparse/.git" ]; then
  cd "$SP" && git clone --filter=blob:none --no-checkout --depth 1 --branch llvmorg-22.1.8 https://github.com/llvm/llvm-project.git llvm-sparse
  cd llvm-sparse
  git sparse-checkout set --no-cone \
    llvm/lib/Target/AArch64/AArch64RegisterInfo.cpp llvm/include/llvm/IR/IRBuilder.h llvm/lib/IR/BuiltinGCs.cpp llvm/lib/IR/IRBuilder.cpp llvm/lib/Transforms/Scalar/RewriteStatepointsForGC.cpp \
    compiler-rt/lib/rtsan/CMakeLists.txt compiler-rt/lib/rtsan/rtsan_context.cpp compiler-rt/lib/rtsan/rtsan_suppressions.cpp \
    flang-rt/CMakeLists.txt flang-rt/lib/runtime/CMakeLists.txt flang-rt/lib/runtime/iso_fortran_env_impl.cpp flang-rt/test/Driver/compare_iso_fortran_env_symbols.f90 flang-rt/test/Driver/iso_fortran_env_impl.f90 flang/include/flang/Common/type-kinds.h flang/module/iso_fortran_env_impl.f90
  git read-tree -mu HEAD
fi
mkdir -p "$SP/patches"
for p in native-image/0001-GR-23578-AArch64-Introduce-option-to-force-placement native-image/0002-GR-17692-Statepoints-Support-for-compressed-pointers backports/0003-compiler-rt-rtsan-Fix-build-failures-when-building-a backports/0004-flang-rt-Implement-iso-module-in-C-in-the-runtime-19; do
  gh api "repos/oracle/graal/contents/sdk/llvm-patches/$p.patch?ref=graal-25.3.4.1" --jq '.content' | base64 -d > "$SP/patches/$(basename $p).patch"
done
cd "$SP/llvm-sparse" && git log --oneline -1
```
Expected: last line prints `ca7933e [libc++] Disable mistakenly enabled ...` (the llvmorg-22.1.8 commit).

- [ ] **Step 2: Verify the patches apply (the failing-test equivalent)**

```bash
cd "$SP/llvm-sparse" && for p in "$SP"/patches/000*.patch; do git apply --check "$p" && echo "OK $(basename $p)"; done
```
Expected: four `OK` lines.

- [ ] **Step 3: Apply as commits and push to the fork**

```bash
cd "$SP/llvm-sparse"
git config user.name "Throwaway68"; git config user.email "carpettohd@gmail.com"
git checkout -q -b graal/22.1.8
git am --committer-date-is-author-date "$SP"/patches/0001-*.patch "$SP"/patches/0002-*.patch "$SP"/patches/0003-*.patch "$SP"/patches/0004-*.patch
git log --oneline -5
git remote add fork https://github.com/Throwaway68/llvm-project.git
git -c credential.helper='!f() { echo username=x-access-token; echo password=$GH_TOKEN; }; f' push fork graal/22.1.8
```
Expected: `git log` shows 4 patch commits above `ca7933e`; push succeeds (a shallow clone can push because the parent commit exists on GitHub).

- [ ] **Step 4: Verify on GitHub**

```bash
gh api 'repos/Throwaway68/llvm-project/compare/llvmorg-22.1.8...graal/22.1.8' --jq '"ahead=\(.ahead_by) behind=\(.behind_by)"'
gh api 'repos/Throwaway68/llvm-project/contents/llvm/lib/Target/AArch64/AArch64RegisterInfo.cpp?ref=graal/22.1.8' --jq '.content' | base64 -d | grep -c 'aarch64-frame-record-on-top'
```
Expected: `ahead=4 behind=0` and `1`.

---

### Task 2: Graal fork branch `graal/25.3.4.1-ci`

**Files:**
- Remote only: branch `graal/25.3.4.1-ci` in `Throwaway68/graal`, one commit modifying `substratevm/mx.substratevm/mx_substratevm.py` (the GR-34811 guard).
- Uses scratchpad partial clone `.../scratchpad/graal-upstream` (`--filter=blob:none --no-checkout` of `oracle/graal`).

**Interfaces:**
- Produces: git ref `graal/25.3.4.1-ci`, consumed by `graalvm.yml` (Task 9) as `inputs.graal_ref`.

- [ ] **Step 1: Sparse-checkout the file at the tag**

```bash
SP=/private/tmp/claude-501/-Users-aislave-Projects-gha-graal/a22769b7-4e91-479f-9d6e-83f7a2920ab3/scratchpad
export GH_TOKEN=<token>
[ -d "$SP/graal-upstream/.git" ] || git clone --filter=blob:none --no-checkout https://github.com/oracle/graal.git "$SP/graal-upstream"
cd "$SP/graal-upstream"
git sparse-checkout set --no-cone substratevm/mx.substratevm/mx_substratevm.py
git checkout -q -b graal/25.3.4.1-ci graal-25.3.4.1
grep -n -A3 'GR-34811' substratevm/mx.substratevm/mx_substratevm.py
```
Expected:
```
# GR-34811
llvm_supported = not (mx.is_windows() or (mx.is_darwin() and mx.get_arch() == "aarch64"))
if llvm_supported:
    mx_sdk_vm.register_graalvm_component(ce_llvm_backend)
```

- [ ] **Step 2: Edit the guard so only Windows is excluded**

```bash
python3 - <<'EOF'
import pathlib
p = pathlib.Path("substratevm/mx.substratevm/mx_substratevm.py")
s = p.read_text()
old = 'llvm_supported = not (mx.is_windows() or (mx.is_darwin() and mx.get_arch() == "aarch64"))'
new = 'llvm_supported = not mx.is_windows()  # CI branch: darwin-aarch64 enabled best-effort (upstream GR-34811 excludes it)'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
EOF
git diff --stat
```
Expected: `1 file changed, 1 insertion(+), 1 deletion(-)`.

- [ ] **Step 3: Commit and push**

```bash
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -am "Register the Native Image LLVM backend on darwin-aarch64 (CI branch)

Upstream keeps darwin-aarch64 out under GR-34811. This branch enables it so
the CI can test the backend on macOS; Windows stays excluded because the
backend has no Windows code path.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git remote add fork https://github.com/Throwaway68/graal.git 2>/dev/null || true
git -c credential.helper='!f() { echo username=x-access-token; echo password=$GH_TOKEN; }; f' push fork graal/25.3.4.1-ci
```

- [ ] **Step 4: Verify on GitHub**

```bash
gh api 'repos/Throwaway68/graal/compare/graal-25.3.4.1...graal/25.3.4.1-ci' --jq '"ahead=\(.ahead_by) behind=\(.behind_by) files=\(.files|map(.filename)|join(","))"'
```
Expected: `ahead=1 behind=0 files=substratevm/mx.substratevm/mx_substratevm.py`.

---

### Task 3: Repository scaffold and `release_tools.py` (manifest + urlrewrites)

**Files:**
- Create: `.gitignore`, `scripts/release_tools.py`, `tests/test_release_tools.py`, `README.md` (stub, completed in Task 11)

**Interfaces:**
- Produces CLI: `python3 scripts/release_tools.py manifest <dir> --version <v>` prints JSON `{"version": v, "files": {"<name>": "sha512:<hex>"}}` for every regular file in `<dir>` except `manifest.json`.
- Produces CLI: `python3 scripts/release_tools.py urlrewrites <manifest.json> <base_url>` prints a JSON list, each element `{"<regex>": {"replacement": "<base_url>/<name>", "digest": "sha512:<hex>"}}`, one per manifest file, matching Oracle's lafo URL for that asset with any version.
- Python API: `build_manifest(directory: Path, version: str) -> dict`, `urlrewrites(manifest: dict, base_url: str) -> list[dict]`, `lafo_pattern(name: str, version: str) -> str`.

- [ ] **Step 1: Write `.gitignore` and the test file**

`.gitignore`:
```
__pycache__/
.pytest_cache/
out/
*.tar.gz
*.zip
```

`tests/test_release_tools.py`:
```python
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import release_tools  # noqa: E402

VERSION = "22.1.8-graal.1"
NAMES = [
    f"llvm-{VERSION}-linux-amd64.tar.gz",
    f"llvm-{VERSION}-windows-amd64.tar.gz",
    f"llvm-{VERSION}-darwin-aarch64.tar.gz",
    f"compiler-rt-{VERSION}-linux-amd64.tar.gz",
    f"llvm-src-{VERSION}.tar.gz",
    f"llvm-lldonly-{VERSION}-darwin-aarch64.tar.gz",
]
ORACLE_VERSION = "22.1.8-4-g1d96596a53-bg6891668b1e"
LAFO = "https://lafo.ssw.uni-linz.ac.at/pub/llvm"


@pytest.fixture
def asset_dir(tmp_path):
    for i, name in enumerate(NAMES):
        (tmp_path / name).write_bytes(b"payload-%d" % i)
    (tmp_path / "manifest.json").write_text("{}")  # must be ignored
    return tmp_path


def test_build_manifest_lists_files_with_sha512(asset_dir):
    m = release_tools.build_manifest(asset_dir, VERSION)
    assert m["version"] == VERSION
    assert set(m["files"]) == set(NAMES)
    expected = "sha512:" + hashlib.sha512(b"payload-0").hexdigest()
    assert m["files"][NAMES[0]] == expected


def test_lafo_pattern_matches_same_asset_with_oracle_version():
    for name in NAMES:
        pat = re.compile(release_tools.lafo_pattern(name, VERSION))
        oracle_name = name.replace(VERSION, ORACLE_VERSION)
        assert pat.match(f"{LAFO}/{oracle_name}"), name


def test_lafo_patterns_do_not_cross_match():
    pats = {n: re.compile(release_tools.lafo_pattern(n, VERSION)) for n in NAMES}
    for n_pat, pat in pats.items():
        for n_url in NAMES:
            url = f"{LAFO}/{n_url.replace(VERSION, ORACLE_VERSION)}"
            assert bool(pat.match(url)) == (n_pat == n_url), (n_pat, n_url)


def test_urlrewrites_shape(asset_dir):
    m = release_tools.build_manifest(asset_dir, VERSION)
    rules = release_tools.urlrewrites(m, "https://example.com/dl")
    assert len(rules) == len(NAMES)
    for rule in rules:
        assert len(rule) == 1
        (pattern, attrs), = rule.items()
        assert set(attrs) == {"replacement", "digest"}
        assert attrs["replacement"].startswith("https://example.com/dl/")
        assert attrs["digest"].startswith("sha512:")
        name = attrs["replacement"].rsplit("/", 1)[1]
        assert re.match(pattern, f"{LAFO}/{name.replace(VERSION, ORACLE_VERSION)}")


def test_cli_roundtrip(asset_dir):
    out = subprocess.check_output([sys.executable, str(ROOT / "scripts/release_tools.py"), "manifest", str(asset_dir), "--version", VERSION])
    m = json.loads(out)
    (asset_dir / "manifest.json").write_text(out.decode())
    out2 = subprocess.check_output([sys.executable, str(ROOT / "scripts/release_tools.py"), "urlrewrites", str(asset_dir / "manifest.json"), "https://example.com/dl"])
    rules = json.loads(out2)
    assert len(rules) == len(m["files"]) == len(NAMES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/aislave/Projects/gha-graal && python3 -m pytest tests/test_release_tools.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'release_tools'`. (If pytest is missing: `python3 -m pip install --user pytest`.)

- [ ] **Step 3: Implement `scripts/release_tools.py`**

```python
#!/usr/bin/env python3
"""Release helpers for the gha-graal workflows.

  release_tools.py manifest <dir> --version <v>
      Print a JSON manifest with sha512 digests of every file in <dir>
      (manifest.json itself is skipped).

  release_tools.py urlrewrites <manifest.json> <base_url>
      Print mx URL rewrite rules (for MX_URLREWRITES) that redirect graal's
      downloads from https://lafo.ssw.uni-linz.ac.at/pub/llvm to
      <base_url>/<asset>, with the manifest digest as override.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

LAFO_HOST = "https://lafo.ssw.uni-linz.ac.at/pub/llvm"
# Oracle's versions look like 22.1.8-4-g1d96596a53-bg6891668b1e; ours like
# 22.1.8-graal.1. Both start with a digit, which is what keeps
# "llvm-<v>-darwin-aarch64" from matching "llvm-lldonly-<v>-darwin-aarch64".
VERSION_RE = r"[0-9][^/]*"


def sha512_of(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return "sha512:" + h.hexdigest()


def build_manifest(directory: Path, version: str) -> dict:
    files = {}
    for p in sorted(Path(directory).iterdir()):
        if p.is_file() and p.name != "manifest.json":
            files[p.name] = sha512_of(p)
    return {"version": version, "files": files}


def lafo_pattern(name: str, version: str) -> str:
    if version not in name:
        raise ValueError(f"{name!r} does not contain version {version!r}")
    head, tail = name.split(version, 1)
    return "^" + re.escape(LAFO_HOST + "/" + head) + VERSION_RE + re.escape(tail) + "$"


def urlrewrites(manifest: dict, base_url: str) -> list:
    version = manifest["version"]
    base = base_url.rstrip("/")
    rules = []
    for name, digest in manifest["files"].items():
        rules.append({lafo_pattern(name, version): {"replacement": f"{base}/{name}", "digest": digest}})
    return rules


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("directory", type=Path)
    m.add_argument("--version", required=True)
    u = sub.add_parser("urlrewrites")
    u.add_argument("manifest", type=Path)
    u.add_argument("base_url")
    args = ap.parse_args(argv)
    if args.cmd == "manifest":
        json.dump(build_manifest(args.directory, args.version), sys.stdout, indent=2)
    else:
        json.dump(urlrewrites(json.loads(args.manifest.read_text()), args.base_url), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_release_tools.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Write the README stub and commit**

`README.md`:
```markdown
# gha-graal

GitHub Actions builds of a GraalVM-patched LLVM 22.1.8 toolchain and GraalVM CE 25.3.4.1
(with the LLVM toolchain, the Sulong LLVM runtime and the Native Image LLVM backend)
for linux-amd64, windows-amd64 and darwin-aarch64.

See `docs/superpowers/specs/2026-09-16-graal-llvm-ci-design.md` for the design.
(Usage instructions are completed in a later task.)
```

```bash
cd /Users/aislave/Projects/gha-graal
git add .gitignore scripts/release_tools.py tests/test_release_tools.py README.md docs/superpowers/plans
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add release_tools (sha512 manifest, mx URL rewrites) and repo scaffold

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `scripts/llvm/build.sh`

**Files:**
- Create: `scripts/llvm/build.sh`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `build.sh <platform> <src-dir> <install-dir> [crt-install-dir]` where platform is `linux-amd64|darwin-aarch64|windows-amd64`. Installs the toolchain into `<install-dir>`; on `linux-amd64` also builds compiler-rt builtins standalone into `<crt-install-dir>` (default `<install-dir>-crt`), laid out as `lib/clang/<major>/lib/linux/{libclang_rt.builtins-x86_64.a,clang_rt.crtbegin-x86_64.o,clang_rt.crtend-x86_64.o}`. Requires `cmake`, `ninja`, `sccache` on PATH (sccache optional: skipped if absent).

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Build the GraalVM-patched LLVM toolchain for one platform.
#
#   build.sh <platform> <src-dir> <install-dir> [crt-install-dir]
#
# platform: linux-amd64 | darwin-aarch64 | windows-amd64
# The build directory is ./build-llvm (and ./build-crt on linux) relative to $PWD.
set -euo pipefail

PLATFORM=${1:?platform}
SRC=${2:?llvm-project source dir}
INSTALL=${3:?install dir}
CRT_INSTALL=${4:-${INSTALL}-crt}

case "$PLATFORM" in
  windows-amd64)
    # Git Bash: give cmake clean forward-slash Windows paths.
    SRC=$(cygpath -m "$SRC"); INSTALL=$(cygpath -m "$INSTALL") ;;
  linux-amd64|darwin-aarch64) ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac

LAUNCHER=()
if command -v sccache >/dev/null 2>&1; then
  LAUNCHER=(-DCMAKE_C_COMPILER_LAUNCHER=sccache -DCMAKE_CXX_COMPILER_LAUNCHER=sccache)
fi

COMMON=(
  -G Ninja
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_INSTALL_PREFIX="$INSTALL"
  -DLLVM_ENABLE_PROJECTS="clang;lld"
  -DLLVM_TARGETS_TO_BUILD="X86;AArch64"
  -DLLVM_ENABLE_ASSERTIONS=OFF
  -DLLVM_INCLUDE_TESTS=OFF
  -DLLVM_INCLUDE_DOCS=OFF
  -DLLVM_INCLUDE_EXAMPLES=OFF
  -DLLVM_INCLUDE_BENCHMARKS=OFF
  -DCLANG_INCLUDE_TESTS=OFF
  -DCLANG_INCLUDE_DOCS=OFF
  -DCLANG_ENABLE_STATIC_ANALYZER=OFF
  -DCLANG_ENABLE_ARCMT=OFF
  -DLLVM_ENABLE_ZLIB=OFF
  -DLLVM_ENABLE_ZSTD=OFF
  -DLLVM_ENABLE_LIBXML2=OFF
  -DLLVM_ENABLE_LIBEDIT=OFF
  -DLLVM_ENABLE_LIBPFM=OFF
  -DLLVM_ENABLE_BINDINGS=OFF
  -DLLVM_PARALLEL_LINK_JOBS=2
  "${LAUNCHER[@]}"
)

# Runtime options are forwarded to the bootstrapping runtimes build by prefix.
RUNTIMES=(
  -DLLVM_ENABLE_RUNTIMES="compiler-rt;libunwind;libcxxabi;libcxx"
  -DCOMPILER_RT_BUILD_BUILTINS=ON
  -DCOMPILER_RT_BUILD_CRT=ON
  -DCOMPILER_RT_BUILD_SANITIZERS=OFF
  -DCOMPILER_RT_BUILD_XRAY=OFF
  -DCOMPILER_RT_BUILD_LIBFUZZER=OFF
  -DCOMPILER_RT_BUILD_PROFILE=OFF
  -DCOMPILER_RT_BUILD_MEMPROF=OFF
  -DCOMPILER_RT_BUILD_ORC=OFF
  -DCOMPILER_RT_BUILD_GWP_ASAN=OFF
  -DCOMPILER_RT_BUILD_CTX_PROFILE=OFF
  -DLIBCXX_INCLUDE_TESTS=OFF
  -DLIBCXX_INCLUDE_BENCHMARKS=OFF
  -DLIBCXXABI_INCLUDE_TESTS=OFF
  -DLIBUNWIND_INCLUDE_TESTS=OFF
)

case "$PLATFORM" in
  linux-amd64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
      -DLLVM_USE_LINKER=lld
      "${RUNTIMES[@]}"
    ) ;;
  darwin-aarch64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
      -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0
      -DCOMPILER_RT_ENABLE_IOS=OFF -DCOMPILER_RT_ENABLE_WATCHOS=OFF -DCOMPILER_RT_ENABLE_TVOS=OFF
      -DCOMPILER_RT_ENABLE_MACCATALYST=OFF
      -DDARWIN_osx_ARCHS=arm64 -DDARWIN_osx_BUILTIN_ARCHS=arm64
      "${RUNTIMES[@]}"
    ) ;;
  windows-amd64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl
      -DLLVM_ENABLE_DIA_SDK=OFF
    ) ;;
esac

echo "== configure ($PLATFORM)"
cmake -S "$SRC/llvm" -B build-llvm "${COMMON[@]}" "${PLATFORM_ARGS[@]}"
echo "== build + install"
cmake --build build-llvm --target install
echo "== installed tools"
ls "$INSTALL/bin" | head -50

if [ "$PLATFORM" = linux-amd64 ]; then
  echo "== standalone compiler-rt builtins (non per-target layout)"
  MAJOR=$("$INSTALL/bin/llvm-config" --version | cut -d. -f1)
  cmake -S "$SRC/runtimes" -B build-crt -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$CRT_INSTALL/stage" \
    -DCMAKE_C_COMPILER="$INSTALL/bin/clang" -DCMAKE_CXX_COMPILER="$INSTALL/bin/clang++" -DCMAKE_ASM_COMPILER="$INSTALL/bin/clang" \
    -DLLVM_ENABLE_RUNTIMES=compiler-rt \
    -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=OFF \
    -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON \
    -DCOMPILER_RT_BUILD_BUILTINS=ON -DCOMPILER_RT_BUILD_CRT=ON \
    -DCOMPILER_RT_BUILD_SANITIZERS=OFF -DCOMPILER_RT_BUILD_XRAY=OFF -DCOMPILER_RT_BUILD_LIBFUZZER=OFF \
    -DCOMPILER_RT_BUILD_PROFILE=OFF -DCOMPILER_RT_BUILD_MEMPROF=OFF -DCOMPILER_RT_BUILD_ORC=OFF \
    -DCOMPILER_RT_BUILD_GWP_ASAN=OFF -DCOMPILER_RT_BUILD_CTX_PROFILE=OFF \
    "${LAUNCHER[@]}"
  cmake --build build-crt --target install
  DEST="$CRT_INSTALL/lib/clang/$MAJOR/lib/linux"
  mkdir -p "$DEST"
  for f in libclang_rt.builtins-x86_64.a clang_rt.crtbegin-x86_64.o clang_rt.crtend-x86_64.o; do
    src=$(find "$CRT_INSTALL/stage" -name "$f" | head -1)
    [ -n "$src" ] || { echo "missing $f in compiler-rt build" >&2; find "$CRT_INSTALL/stage" -type f | head; exit 1; }
    cp "$src" "$DEST/"
  done
  rm -rf "$CRT_INSTALL/stage"
  find "$CRT_INSTALL" -type f
fi
```

- [ ] **Step 2: Syntax-check and dry-run the argument handling**

```bash
cd /Users/aislave/Projects/gha-graal && chmod +x scripts/llvm/build.sh && bash -n scripts/llvm/build.sh && scripts/llvm/build.sh bogus /x /y; echo "exit=$?"
```
Expected: `unknown platform: bogus` and `exit=2`.

- [ ] **Step 3: Commit**

```bash
git add scripts/llvm/build.sh
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add LLVM toolchain build script

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `scripts/llvm/package.sh` with local test

**Files:**
- Create: `scripts/llvm/package.sh`, `tests/test_package_llvm.sh`

**Interfaces:**
- Produces: `package.sh <platform> <version> <install-dir> <out-dir> [src-git-dir] [crt-dir]`. Writes into `<out-dir>`:
  - always `llvm-<version>-<platform>.tar.gz` (contents of `<install-dir>`, no top-level dir);
  - `linux-amd64`: also `compiler-rt-<version>-linux-amd64.tar.gz` (contents of `<crt-dir>`) and `llvm-src-<version>.tar.gz` (`git archive HEAD` of `<src-git-dir>`, no top-level dir);
  - `darwin-aarch64`: also `llvm-lldonly-<version>-darwin-aarch64.tar.gz` with `bin/{lld,ld.lld,ld64.lld,lld-link,wasm-ld,llvm-tblgen}` and `include/{lld,llvm,llvm-c}`.

- [ ] **Step 1: Write the failing test**

`tests/test_package_llvm.sh`:
```bash
#!/usr/bin/env bash
# Local test of scripts/llvm/package.sh on a fake install tree.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
V=1.0-test

# fake install tree
mkdir -p "$T/inst/bin" "$T/inst/lib/clang/22/lib/x86_64-unknown-linux-gnu" "$T/inst/include/lld" "$T/inst/include/llvm" "$T/inst/include/llvm-c"
for b in clang lld ld.lld ld64.lld lld-link wasm-ld llvm-tblgen llc; do echo "#!/bin/sh" > "$T/inst/bin/$b"; done
ln -s clang "$T/inst/bin/clang++"
echo x > "$T/inst/lib/libLLVM.a"; echo h > "$T/inst/include/llvm/a.h"
# fake crt tree
mkdir -p "$T/crt/lib/clang/22/lib/linux"; echo a > "$T/crt/lib/clang/22/lib/linux/libclang_rt.builtins-x86_64.a"
# fake source git repo
mkdir -p "$T/src/llvm"; echo s > "$T/src/llvm/CMakeLists.txt"
git -C "$T/src" init -q && git -C "$T/src" add -A && git -C "$T/src" -c user.name=t -c user.email=t@t commit -q -m init

fail() { echo "FAIL: $*" >&2; exit 1; }

# linux: three tarballs, no top-level dir
bash "$ROOT/scripts/llvm/package.sh" linux-amd64 "$V" "$T/inst" "$T/out-linux" "$T/src" "$T/crt"
[ -f "$T/out-linux/llvm-$V-linux-amd64.tar.gz" ] || fail "main tarball missing"
tar tzf "$T/out-linux/llvm-$V-linux-amd64.tar.gz" | grep -qx 'bin/clang' || fail "bin/clang not at root of main tarball"
tar tzf "$T/out-linux/llvm-$V-linux-amd64.tar.gz" | grep -q '^\./' && fail "main tarball has ./ prefix"
tar tzf "$T/out-linux/compiler-rt-$V-linux-amd64.tar.gz" | grep -qx 'lib/clang/22/lib/linux/libclang_rt.builtins-x86_64.a' || fail "crt layout"
tar tzf "$T/out-linux/llvm-src-$V.tar.gz" | grep -qx 'llvm/CMakeLists.txt' || fail "src tarball layout"
[ "$(ls "$T/out-linux" | wc -l)" -eq 3 ] || fail "linux should produce exactly 3 files"

# darwin: main + lldonly
bash "$ROOT/scripts/llvm/package.sh" darwin-aarch64 "$V" "$T/inst" "$T/out-mac"
L="$T/out-mac/llvm-lldonly-$V-darwin-aarch64.tar.gz"
[ -f "$L" ] || fail "lldonly missing"
for e in bin/lld bin/ld.lld bin/ld64.lld bin/lld-link bin/wasm-ld bin/llvm-tblgen include/llvm/a.h; do tar tzf "$L" | grep -qx "$e" || fail "lldonly lacks $e"; done
tar tzf "$L" | grep -qx 'bin/llc' && fail "lldonly must not contain llc"
[ "$(ls "$T/out-mac" | wc -l)" -eq 2 ] || fail "darwin should produce exactly 2 files"

# windows: main only
bash "$ROOT/scripts/llvm/package.sh" windows-amd64 "$V" "$T/inst" "$T/out-win"
[ "$(ls "$T/out-win" | wc -l)" -eq 1 ] || fail "windows should produce exactly 1 file"

echo "PASS test_package_llvm"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/aislave/Projects/gha-graal && bash tests/test_package_llvm.sh`
Expected: error `scripts/llvm/package.sh: No such file or directory` (non-zero exit).

- [ ] **Step 3: Write `scripts/llvm/package.sh`**

```bash
#!/usr/bin/env bash
# Pack the LLVM install tree into the tarballs graal's suite.py expects.
#
#   package.sh <platform> <version> <install-dir> <out-dir> [src-git-dir] [crt-dir]
#
# All tarballs have bin/, lib/, include/ ... at their root (no top-level dir),
# matching Oracle's bundles on lafo.ssw.uni-linz.ac.at.
set -euo pipefail

PLATFORM=${1:?platform}
VERSION=${2:?version}
INSTALL=${3:?install dir}
OUT=${4:?out dir}
SRC=${5:-}
CRT=${6:-}

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

pack_dir() {  # pack_dir <dir> <tarball>: archive the entries of <dir> at the tarball root
  local dir=$1 tarball=$2
  ( cd "$dir" && tar -czf "$tarball" -- * )
}

echo "== $PLATFORM: main bundle"
pack_dir "$INSTALL" "$OUT/llvm-$VERSION-$PLATFORM.tar.gz"

case "$PLATFORM" in
  linux-amd64)
    [ -n "$SRC" ] && [ -n "$CRT" ] || { echo "linux-amd64 needs <src-git-dir> and <crt-dir>" >&2; exit 2; }
    echo "== compiler-rt bundle"
    pack_dir "$CRT" "$OUT/compiler-rt-$VERSION-linux-amd64.tar.gz"
    echo "== source bundle"
    git -C "$SRC" archive --format=tar.gz -o "$OUT/llvm-src-$VERSION.tar.gz" HEAD
    ;;
  darwin-aarch64)
    echo "== lld-only bundle"
    ( cd "$INSTALL" && tar -czf "$OUT/llvm-lldonly-$VERSION-darwin-aarch64.tar.gz" \
        bin/lld bin/ld.lld bin/ld64.lld bin/lld-link bin/wasm-ld bin/llvm-tblgen include/lld include/llvm include/llvm-c )
    ;;
  windows-amd64) ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac

ls -la "$OUT"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `chmod +x scripts/llvm/package.sh && bash tests/test_package_llvm.sh`
Expected: `PASS test_package_llvm`.

- [ ] **Step 5: Commit**

```bash
git add scripts/llvm/package.sh tests/test_package_llvm.sh
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add LLVM bundle packaging script with local test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Workflow `llvm.yml`, create the GitHub repo, first real run

**Files:**
- Create: `.github/workflows/llvm.yml`

**Interfaces:**
- Consumes: `scripts/llvm/build.sh` (Task 4), `scripts/llvm/package.sh` (Task 5), `scripts/release_tools.py manifest` (Task 3), branch `graal/22.1.8` (Task 1).
- Produces: GitHub Release `llvm-<version>` in `Throwaway68/gha-graal` with the 6 tarballs plus `manifest.json`. Consumed by `graalvm.yml` (Task 9) via `inputs.llvm_release`.

- [ ] **Step 1: Write the workflow**

```yaml
name: LLVM toolchain

on:
  workflow_dispatch:
    inputs:
      llvm_ref:
        description: 'Ref in Throwaway68/llvm-project to build'
        default: 'graal/22.1.8'
        required: true
        type: string
      version:
        description: 'Version label used in asset names; the release tag is llvm-<version>'
        default: '22.1.8-graal.1'
        required: true
        type: string
      publish:
        description: 'Create the GitHub release'
        default: true
        type: boolean

permissions:
  contents: write

env:
  SCCACHE_GHA_ENABLED: 'true'

jobs:
  build:
    name: ${{ matrix.platform }}
    runs-on: ${{ matrix.os }}
    timeout-minutes: 360
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: ubuntu-22.04, platform: linux-amd64 }
          - { os: macos-14, platform: darwin-aarch64 }
          - { os: windows-2022, platform: windows-amd64 }
    steps:
      - name: Checkout gha-graal
        uses: actions/checkout@v7.0.1
        with:
          path: ci
      - name: Checkout llvm-project
        uses: actions/checkout@v7.0.1
        with:
          repository: Throwaway68/llvm-project
          ref: ${{ inputs.llvm_ref }}
          path: llvm-project
          fetch-depth: 1
      - name: Set up sccache
        uses: mozilla-actions/sccache-action@v0.0.11
      - name: Linux dependencies
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y ninja-build lld
      - name: macOS dependencies
        if: runner.os == 'macOS'
        run: brew install ninja
      - name: Windows MSVC environment
        if: runner.os == 'Windows'
        uses: ilammy/msvc-dev-cmd@v1.13.0
        with:
          arch: x64
      - name: Windows dependencies
        if: runner.os == 'Windows'
        run: choco install ninja --no-progress -y
      - name: Build
        shell: bash
        run: bash ci/scripts/llvm/build.sh "${{ matrix.platform }}" "$GITHUB_WORKSPACE/llvm-project" "$GITHUB_WORKSPACE/llvm-install" "$GITHUB_WORKSPACE/llvm-install-crt"
      - name: sccache stats
        if: always()
        shell: bash
        run: sccache --show-stats || true
      - name: Package
        shell: bash
        run: bash ci/scripts/llvm/package.sh "${{ matrix.platform }}" "${{ inputs.version }}" "$GITHUB_WORKSPACE/llvm-install" "$GITHUB_WORKSPACE/out" "$GITHUB_WORKSPACE/llvm-project" "$GITHUB_WORKSPACE/llvm-install-crt"
      - name: Upload
        uses: actions/upload-artifact@v7.0.1
        with:
          name: llvm-${{ matrix.platform }}
          path: out/*
          if-no-files-found: error
          compression-level: 0

  release:
    name: Release llvm-${{ inputs.version }}
    needs: build
    if: ${{ inputs.publish }}
    runs-on: ubuntu-22.04
    steps:
      - name: Checkout gha-graal
        uses: actions/checkout@v7.0.1
        with:
          path: ci
      - name: Download all bundles
        uses: actions/download-artifact@v8.0.1
        with:
          pattern: llvm-*
          merge-multiple: true
          path: assets
      - name: Write manifest
        run: |
          python3 ci/scripts/release_tools.py manifest assets --version "${{ inputs.version }}" > manifest.json
          mv manifest.json assets/
          cat assets/manifest.json
      - name: Create release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          cat > notes.md <<EOF
          LLVM toolchain for GraalVM, built from \`Throwaway68/llvm-project@${{ inputs.llvm_ref }}\`
          (llvmorg-22.1.8 + graal patches). Projects: clang, lld. Targets: X86, AArch64.
          Runtimes (linux/darwin): compiler-rt builtins, libunwind, libc++abi, libc++.
          Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          EOF
          gh release create "llvm-${{ inputs.version }}" assets/* \
            --repo "${{ github.repository }}" \
            --title "LLVM ${{ inputs.version }}" \
            --notes-file notes.md
```

- [ ] **Step 2: Validate YAML locally**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/llvm.yml')); print('yaml ok')"` (if PyYAML is missing: `python3 -m pip install --user pyyaml`).
Expected: `yaml ok`.

- [ ] **Step 3: Commit, create the GitHub repo and push**

```bash
cd /Users/aislave/Projects/gha-graal
git add .github/workflows/llvm.yml
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add LLVM toolchain workflow

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
export GH_TOKEN=<token>
gh repo create Throwaway68/gha-graal --public --description "CI builds of GraalVM + patched LLVM toolchain" --source . --push
gh repo view Throwaway68/gha-graal --json url,defaultBranchRef --jq '"\(.url) \(.defaultBranchRef.name)"'
```
Expected: `https://github.com/Throwaway68/gha-graal main`.

- [ ] **Step 4: Dispatch the workflow and watch it**

```bash
gh workflow run llvm.yml --repo Throwaway68/gha-graal -f llvm_ref=graal/22.1.8 -f version=22.1.8-graal.1 -f publish=true
sleep 20; gh run list --repo Throwaway68/gha-graal --workflow llvm.yml --limit 1 --json databaseId,status,url
```
Then poll every 10–15 minutes with `gh run view <id> --repo Throwaway68/gha-graal` and, on a failed job, `gh run view <id> --repo Throwaway68/gha-graal --log-failed | tail -100`. The Linux job is expected to take about 2–3 h, macOS about 3 h, Windows 3–5 h. If a job times out at 6 h, re-run only failed jobs (`gh run rerun <id> --failed --repo Throwaway68/gha-graal`); sccache makes the second attempt much faster.

Fix loop: for each failure, change the script or workflow, commit with a message describing the fix, push, and re-dispatch. Known likely adjustments: CMake option names that LLVM 22 no longer accepts (they produce a warning, not an error), missing `ninja` on the Windows image, compiler-rt standalone install layout (the `find` in `build.sh` tolerates layout differences; if a file is genuinely missing, add `-DCOMPILER_RT_INSTALL_PATH=...` or check `build-crt` for the built file names).

- [ ] **Step 5: Verify the release**

```bash
gh release view llvm-22.1.8-graal.1 --repo Throwaway68/gha-graal --json assets --jq '.assets[] | "\(.name) \(.size)"'
gh release download llvm-22.1.8-graal.1 --repo Throwaway68/gha-graal --pattern manifest.json --dir /tmp/llvmrel --clobber && python3 -c "import json; m=json.load(open('/tmp/llvmrel/manifest.json')); print(len(m['files']), 'files'); assert len(m['files'])==6"
```
Expected: 7 assets (6 tarballs + manifest.json), `6 files`.

---

### Task 7: mx env file and GraalVM smoke test script

**Files:**
- Create: `mx-env/ce-llvm-ci`, `scripts/graalvm/smoke.sh`

**Interfaces:**
- Produces: `mx-env/ce-llvm-ci`, copied by the workflow into `graal/vm/mx.vm/ce-llvm-ci` and selected with `mx --env ce-llvm-ci`.
- Produces: `smoke.sh <graalvm-home> <work-dir>`; exits non-zero on any failure; prints `LLVM backend: tested` or `LLVM backend: not available in this build`.

- [ ] **Step 1: Write `mx-env/ce-llvm-ci`**

```
# GraalVM CE + LLVM toolchain + Sulong + Native Image LLVM backend (gha-graal CI env)
# Unknown components (e.g. svml on Windows, where mx does not register it) only produce a warning.
DYNAMIC_IMPORTS=/sdk,/truffle,/compiler,/substratevm,/sulong
COMPONENTS=antlr4,cmp,gvm,lg,llp,llrc,llrl,llrlf,llrn,nfi,nfi-libffi,ni,nic,nil,sdkni,svm,svmjdwp,svml,svmsl,svmt,tfl,tfla,tflc,tflm,tflsm
NATIVE_IMAGES=lib:jvmcicompiler,lib:llvmvm,lib:native-image-agent,lib:native-image-diagnostics-agent,native-image,graalvm-native-binutil,graalvm-native-clang,graalvm-native-clang-cl,graalvm-native-clang++,graalvm-native-ld
NON_REBUILDABLE_IMAGES=lib:jvmcicompiler
```

- [ ] **Step 2: Write `scripts/graalvm/smoke.sh`**

```bash
#!/usr/bin/env bash
# Smoke-test a GraalVM home built by graalvm.yml.
#
#   smoke.sh <graalvm-home> <work-dir>
#
# Checks: java, native-image, lli, compiling C with the bundled toolchain and
# running it on Sulong, and (when the llvm-backend tool exists) building a
# Java hello world with `native-image --tool:llvm-backend`.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not mangle -cp / --tool: arguments

H=${1:?graalvm home}
W=${2:?work dir}
mkdir -p "$W"; W=$(cd "$W" && pwd)
cd "$W"

exe() {  # exe <dir> <name>: first existing of name, name.exe, name.cmd
  local d=$1 n=$2 c
  for c in "$n" "$n.exe" "$n.cmd"; do
    if [ -e "$d/$c" ]; then echo "$d/$c"; return 0; fi
  done
  echo "missing $n in $d" >&2; ls "$d" >&2; return 1
}

JAVA=$(exe "$H/bin" java); NI=$(exe "$H/bin" native-image); LLI=$(exe "$H/bin" lli); JAVAC=$(exe "$H/bin" javac)

echo "== java --version";          "$JAVA" --version
echo "== native-image --version";  "$NI" --version
echo "== lli --version";           "$LLI" --version

echo "== Sulong: compile C with the bundled toolchain and run it"
TC=$("$LLI" --print-toolchain-path | tr -d '\r')
echo "toolchain: $TC"; ls "$TC/bin"
CLANG=$(exe "$TC/bin" clang)
cat > hello.c <<'EOF'
#include <stdio.h>
int main(void) { printf("Hello from Sulong\n"); return 0; }
EOF
"$CLANG" hello.c -o hello.exe
"$LLI" hello.exe | tee lli.out
grep -q 'Hello from Sulong' lli.out

if [ -d "$H/lib/svm/tools/llvm-backend" ] || [ -d "$H/lib/svm/macros/llvm-backend" ]; then
  echo "== Native Image LLVM backend"
  cat > Hello.java <<'EOF'
public class Hello { public static void main(String[] a) { System.out.println("Hello from the LLVM backend"); } }
EOF
  "$JAVAC" Hello.java
  "$NI" --tool:llvm-backend -cp . Hello -o hello-llvm
  ./hello-llvm | tee ni.out
  grep -q 'Hello from the LLVM backend' ni.out
  echo "LLVM backend: tested"
else
  echo "LLVM backend: not available in this build"
fi
echo "SMOKE OK"
```

- [ ] **Step 3: Syntax check and negative test**

```bash
cd /Users/aislave/Projects/gha-graal && chmod +x scripts/graalvm/smoke.sh && bash -n scripts/graalvm/smoke.sh && bash scripts/graalvm/smoke.sh /nonexistent /tmp/smoke-neg; echo "exit=$?"
```
Expected: `missing java in /nonexistent/bin` and a non-zero exit.

- [ ] **Step 4: Commit**

```bash
git add mx-env/ce-llvm-ci scripts/graalvm/smoke.sh
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add GraalVM mx env file and smoke test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `scripts/graalvm/package.sh` with local test

**Files:**
- Create: `scripts/graalvm/package.sh`, `tests/test_package_graalvm.sh`

**Interfaces:**
- Produces: `package.sh <graalvm-home> <name> <platform> <out-dir>`. Stages the distribution root as `<name>/` (on darwin the root is two levels above `Contents/Home`, so the archive contains `<name>/Contents/Home/...`) and writes `<out-dir>/<name>.tar.gz` (linux, darwin) or `<out-dir>/<name>.zip` (windows, via `7z`; falls back to `zip` if `7z` is absent).

- [ ] **Step 1: Write the failing test**

`tests/test_package_graalvm.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# linux-style home
mkdir -p "$T/lin/graalvm-abc123-java25/bin"; echo j > "$T/lin/graalvm-abc123-java25/bin/java"
bash "$ROOT/scripts/graalvm/package.sh" "$T/lin/graalvm-abc123-java25" graalvm-test-linux-amd64 linux-amd64 "$T/out"
tar tzf "$T/out/graalvm-test-linux-amd64.tar.gz" | grep -qx 'graalvm-test-linux-amd64/bin/java' || fail "linux layout"

# darwin-style home (Contents/Home)
mkdir -p "$T/mac/graalvm-abc123-java25/Contents/Home/bin"; echo j > "$T/mac/graalvm-abc123-java25/Contents/Home/bin/java"
bash "$ROOT/scripts/graalvm/package.sh" "$T/mac/graalvm-abc123-java25/Contents/Home" graalvm-test-darwin-aarch64 darwin-aarch64 "$T/out"
tar tzf "$T/out/graalvm-test-darwin-aarch64.tar.gz" | grep -qx 'graalvm-test-darwin-aarch64/Contents/Home/bin/java' || fail "darwin layout"

# windows-style home -> zip
mkdir -p "$T/win/graalvm-abc123-java25/bin"; echo j > "$T/win/graalvm-abc123-java25/bin/java.exe"
bash "$ROOT/scripts/graalvm/package.sh" "$T/win/graalvm-abc123-java25" graalvm-test-windows-amd64 windows-amd64 "$T/out"
[ -f "$T/out/graalvm-test-windows-amd64.zip" ] || fail "zip missing"
unzip -l "$T/out/graalvm-test-windows-amd64.zip" | grep -q 'graalvm-test-windows-amd64/bin/java.exe' || fail "zip layout"
echo "PASS test_package_graalvm"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/test_package_graalvm.sh`
Expected: `scripts/graalvm/package.sh: No such file or directory`, non-zero exit.

- [ ] **Step 3: Write `scripts/graalvm/package.sh`**

```bash
#!/usr/bin/env bash
# Package a GraalVM home as <out-dir>/<name>.tar.gz (linux/darwin) or <name>.zip (windows).
#
#   package.sh <graalvm-home> <name> <platform> <out-dir>
#
# The archive contains a single top-level directory <name>. On darwin the
# distribution root is the directory two levels above Contents/Home.
set -euo pipefail
HOME_DIR=${1:?graalvm home}
NAME=${2:?archive name}
PLATFORM=${3:?platform}
OUT=${4:?out dir}

HOME_DIR=$(cd "$HOME_DIR" && pwd -P)
ROOT=$HOME_DIR
case "$HOME_DIR" in */Contents/Home) ROOT=$(cd "$HOME_DIR/../.." && pwd -P) ;; esac

mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/graalvm-stage.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
cp -R "$ROOT" "$STAGE/$NAME"

case "$PLATFORM" in
  linux-amd64|darwin-aarch64)
    tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME" ;;
  windows-amd64)
    if command -v 7z >/dev/null 2>&1; then
      ( cd "$STAGE" && 7z a -tzip -bd -mx=5 "$OUT/$NAME.zip" "$NAME" >/dev/null )
    else
      ( cd "$STAGE" && zip -qr "$OUT/$NAME.zip" "$NAME" )
    fi ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac
ls -la "$OUT"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `chmod +x scripts/graalvm/package.sh && bash tests/test_package_graalvm.sh`
Expected: `PASS test_package_graalvm`.

- [ ] **Step 5: Commit**

```bash
git add scripts/graalvm/package.sh tests/test_package_graalvm.sh
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add GraalVM packaging script with local test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Workflow `graalvm.yml` and first real run

**Files:**
- Create: `.github/workflows/graalvm.yml`

**Interfaces:**
- Consumes: release `llvm-<version>` (Task 6), `mx-env/ce-llvm-ci` and `scripts/graalvm/smoke.sh` (Task 7), `scripts/graalvm/package.sh` (Task 8), `scripts/release_tools.py urlrewrites` (Task 3), branch `graal/25.3.4.1-ci` (Task 2).
- Produces: GitHub Release `graalvm-<label>` with `graalvm-<label>-{linux-amd64,darwin-aarch64}.tar.gz`, `graalvm-<label>-windows-amd64.zip` and `manifest.json`.

- [ ] **Step 1: Write the workflow**

```yaml
name: GraalVM

on:
  workflow_dispatch:
    inputs:
      graal_ref:
        description: 'Ref in Throwaway68/graal to build'
        default: 'graal/25.3.4.1-ci'
        required: true
        type: string
      llvm_release:
        description: 'Release tag in this repo providing the LLVM bundles (llvm-<version>)'
        default: 'llvm-22.1.8-graal.1'
        required: true
        type: string
      label:
        description: 'Archive/release label (default: <graal_ref>-<llvm_release>, slashes replaced by dashes)'
        default: ''
        type: string
      publish:
        description: 'Create the GitHub release'
        default: true
        type: boolean

permissions:
  contents: write

env:
  LANG: en_US.UTF-8
  MX_GIT_CACHE: refcache
  PYTHONIOENCODING: utf-8
  # Experimental option checking as in Oracle's CI
  NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL: 'true'

jobs:
  build:
    name: ${{ matrix.platform }}
    runs-on: ${{ matrix.os }}
    timeout-minutes: 360
    strategy:
      fail-fast: false
      matrix:
        include:
          - { os: ubuntu-22.04, platform: linux-amd64 }
          - { os: macos-14, platform: darwin-aarch64 }
          - { os: windows-2022, platform: windows-amd64 }
    steps:
      - name: Checkout gha-graal
        uses: actions/checkout@v7.0.1
        with:
          path: ci
      - name: Checkout graal
        uses: actions/checkout@v7.0.1
        with:
          repository: Throwaway68/graal
          ref: ${{ inputs.graal_ref }}
          path: graal
      - name: Derive label and paths
        shell: bash
        run: |
          label='${{ inputs.label }}'
          if [ -z "$label" ]; then label="${{ inputs.graal_ref }}-${{ inputs.llvm_release }}"; fi
          label=${label//\//-}
          echo "LABEL=$label" >> "$GITHUB_ENV"
          echo "MX_PATH=$GITHUB_WORKSPACE/mx" >> "$GITHUB_ENV"
          echo "JAVA_HOME=$GITHUB_WORKSPACE/jdk" >> "$GITHUB_ENV"
          echo "MX_VERSION=$(jq -r '.mx_version' graal/common.json)" >> "$GITHUB_ENV"
          echo "GRAAL_SHA=$(git -C graal rev-parse HEAD)" >> "$GITHUB_ENV"
          if [ "$RUNNER_OS" = Windows ]; then echo "MX_PYTHON=python" >> "$GITHUB_ENV"; else echo "MX_PYTHON=python3" >> "$GITHUB_ENV"; fi
      - name: Checkout mx
        uses: actions/checkout@v7.0.1
        with:
          repository: graalvm/mx
          ref: ${{ env.MX_VERSION }}
          path: mx
      - name: Set up Python
        uses: actions/setup-python@v7.0.0
        with:
          python-version: '3.11'
      - name: Linux dependencies
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y build-essential cmake ninja-build zlib1g-dev libz-dev
      - name: macOS dependencies
        if: runner.os == 'macOS'
        run: brew install ninja cmake || true
      - name: Windows MSVC environment
        if: runner.os == 'Windows'
        uses: ilammy/msvc-dev-cmd@v1.13.0
        with:
          arch: x64
      - name: Fetch LabsJDK
        shell: bash
        run: |
          mkdir -p jdk-dl
          "$MX_PATH/mx" --java-home= fetch-jdk --jdk-id labsjdk-ce-latest --to jdk-dl --alias "$JAVA_HOME"
          if [ -d "$JAVA_HOME/Contents/Home" ]; then echo "JAVA_HOME=$JAVA_HOME/Contents/Home" >> "$GITHUB_ENV"; fi
      - name: Point graal at our LLVM release (MX_URLREWRITES)
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release download "${{ inputs.llvm_release }}" --repo "${{ github.repository }}" --pattern manifest.json --dir llvm-release --clobber
          python3 ci/scripts/release_tools.py urlrewrites llvm-release/manifest.json \
            "${{ github.server_url }}/${{ github.repository }}/releases/download/${{ inputs.llvm_release }}" > urlrewrites.json
          cat urlrewrites.json
          echo "MX_URLREWRITES=$GITHUB_WORKSPACE/urlrewrites.json" >> "$GITHUB_ENV"
      - name: Install env file
        shell: bash
        run: cp ci/mx-env/ce-llvm-ci graal/vm/mx.vm/ce-llvm-ci
      - name: Build GraalVM (Linux/macOS)
        if: runner.os != 'Windows'
        shell: bash
        run: |
          cd graal/vm
          "$MX_PATH/mx" --env ce-llvm-ci graalvm-show
          "$MX_PATH/mx" --env ce-llvm-ci build
          echo "GRAALVM_HOME=$("$MX_PATH/mx" --env ce-llvm-ci graalvm-home)" >> "$GITHUB_ENV"
      - name: Build GraalVM (Windows)
        if: runner.os == 'Windows'
        shell: cmd
        run: |
          cd graal\vm
          call %MX_PATH%\mx.cmd --env ce-llvm-ci graalvm-show
          call %MX_PATH%\mx.cmd --env ce-llvm-ci build
          call %MX_PATH%\mx.cmd --env ce-llvm-ci graalvm-home > graalvm-home.txt
          set /p GRAALVM_HOME=<graalvm-home.txt
          echo GRAALVM_HOME=%GRAALVM_HOME%>>%GITHUB_ENV%
      - name: Smoke test
        shell: bash
        run: bash ci/scripts/graalvm/smoke.sh "$GRAALVM_HOME" "$GITHUB_WORKSPACE/smoke"
      - name: Package
        shell: bash
        run: bash ci/scripts/graalvm/package.sh "$GRAALVM_HOME" "graalvm-$LABEL-${{ matrix.platform }}" "${{ matrix.platform }}" "$GITHUB_WORKSPACE/out"
      - name: Upload
        uses: actions/upload-artifact@v7.0.1
        with:
          name: graalvm-${{ matrix.platform }}
          path: out/*
          if-no-files-found: error
          compression-level: 0

  release:
    name: Release
    needs: build
    if: ${{ inputs.publish }}
    runs-on: ubuntu-22.04
    steps:
      - name: Checkout gha-graal
        uses: actions/checkout@v7.0.1
        with:
          path: ci
      - name: Download archives
        uses: actions/download-artifact@v8.0.1
        with:
          pattern: graalvm-*
          merge-multiple: true
          path: assets
      - name: Derive label
        shell: bash
        run: |
          label='${{ inputs.label }}'
          if [ -z "$label" ]; then label="${{ inputs.graal_ref }}-${{ inputs.llvm_release }}"; fi
          echo "LABEL=${label//\//-}" >> "$GITHUB_ENV"
      - name: Write manifest and create release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          python3 ci/scripts/release_tools.py manifest assets --version "$LABEL" > manifest.json
          mv manifest.json assets/
          cat > notes.md <<EOF
          GraalVM CE built from \`Throwaway68/graal@${{ inputs.graal_ref }}\` with the LLVM toolchain from release \`${{ inputs.llvm_release }}\`.
          Components: CE base, LLVM.org toolchain, Sulong (LLVM runtime), Native Image LLVM backend where the build system registers it (linux-amd64, darwin-aarch64 on the CI branch; not on Windows).
          Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          EOF
          gh release create "graalvm-$LABEL" assets/* \
            --repo "${{ github.repository }}" \
            --title "GraalVM $LABEL" \
            --notes-file notes.md
```

- [ ] **Step 2: Validate YAML, commit, push**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/graalvm.yml')); print('yaml ok')"
git add .github/workflows/graalvm.yml
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Add GraalVM workflow

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
export GH_TOKEN=<token>; git push
```

- [ ] **Step 3: Dispatch and watch**

```bash
gh workflow run graalvm.yml --repo Throwaway68/gha-graal -f graal_ref=graal/25.3.4.1-ci -f llvm_release=llvm-22.1.8-graal.1 -f publish=true
sleep 20; gh run list --repo Throwaway68/gha-graal --workflow graalvm.yml --limit 1 --json databaseId,status,url
```
Poll as in Task 6. Expected durations: Linux 1–1.5 h, macOS 1.5–2 h, Windows 1.5–2.5 h.

Fix loop guidance for likely failures:
- `mx` complains a download digest mismatches: the manifest and the release asset differ; re-check `urlrewrites.json` output in the log and the asset that was actually downloaded.
- mx cannot find a component name from `COMPONENTS`: it warns only; but if `graalvm-show` lists no Sulong components, check that `/sulong` is in `DYNAMIC_IMPORTS`.
- On macOS, if the `svml` build or the backend smoke test fails, first retry with `-f graal_ref=graal-25.3.4.1` (pristine tag, no backend on macOS) so the other deliverables ship, then report the macOS backend failure with the log excerpt.
- On Windows, if Sulong fails to build, create `mx-env/ce-llvm-ci-windows` without `antlr4,llrc,llrl,llrlf,llrn,lib:llvmvm` and the toolchain launchers, select it in the Windows build step, and report this fallback explicitly.

- [ ] **Step 4: Verify the release**

```bash
gh release view "graalvm-graal-25.3.4.1-ci-llvm-22.1.8-graal.1" --repo Throwaway68/gha-graal --json assets --jq '.assets[] | "\(.name) \(.size)"'
```
Expected: 4 assets (two `.tar.gz`, one `.zip`, `manifest.json`). Also confirm in the run logs that the Linux smoke test printed `LLVM backend: tested` and note what macOS printed.

---

### Task 10: README, sync manifest, final report

**Files:**
- Modify: `README.md`
- Modify: `.sync-manifest`

- [ ] **Step 1: Complete the README**

Replace `README.md` with:
```markdown
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
```

- [ ] **Step 2: Update `.sync-manifest`**

```bash
cd /Users/aislave/Projects/gha-graal
cat > .sync-manifest <<'EOF'
.github/workflows/llvm.yml
.github/workflows/graalvm.yml
.gitignore
README.md
docs/superpowers/specs/2026-09-16-graal-llvm-ci-design.md
docs/superpowers/plans/2026-09-16-graal-llvm-ci.md
mx-env/ce-llvm-ci
scripts/release_tools.py
scripts/llvm/build.sh
scripts/llvm/package.sh
scripts/graalvm/smoke.sh
scripts/graalvm/package.sh
tests/test_release_tools.py
tests/test_package_llvm.sh
tests/test_package_graalvm.sh
EOF
```
(Add any file created during the fix loops, e.g. `mx-env/ce-llvm-ci-windows`.)

- [ ] **Step 3: Commit and push**

```bash
git add README.md .sync-manifest
git -c user.name="Throwaway68" -c user.email="carpettohd@gmail.com" commit -m "Document workflows and branch plumbing

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
export GH_TOKEN=<token>; git push
```

- [ ] **Step 4: Final report to the user**

Report: the two release URLs, per-platform smoke-test outcome (especially `LLVM backend: tested` on Linux and the macOS result), job durations, anything that fell back (Windows Sulong, macOS backend) with the log excerpt, and the two workflow run URLs.
