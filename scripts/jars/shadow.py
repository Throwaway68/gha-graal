#!/usr/bin/env python3
"""Turn a JavaCPP platform jar from Maven Central into a graal "shadowed" jar.

  shadow.py <input.jar> <output.jar> --module <name> [--requires <module>]... [--base-jar <jar>]...

Relocates org/bytedeco/** to com/oracle/svm/shadowed/org/bytedeco/**, drops
META-INF/native-image, META-INF/maven and the jar's own module descriptors, and
adds `open module <name> { requires transitive <m>; ... }`, compiled with javac
--release 9 against the --base-jar entries on the module path. The descriptor
goes to META-INF/versions/9/module-info.class of a Multi-Release jar, which is
where Oracle's linux/macOS shadowed jars carry theirs.

Platform jars hold only native libraries, so relocating entry names is the whole
job: there is no bytecode referencing org.bytedeco to rewrite.

Retained for the record and superseded: the Windows LLVM backend branch uses the
stock org.bytedeco jars on every platform (stock-jars decision, task 6, in
docs/journal/windows-llvm-backend.md), so nothing consumes jars-1.5.7-graal.1.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

OLD = "org/bytedeco/"
NEW = "com/oracle/svm/shadowed/org/bytedeco/"
DROP_PREFIXES = ("META-INF/native-image/", "META-INF/maven/")
DROP_EXACT = ("META-INF/MANIFEST.MF", "module-info.class")
DROP_RE = re.compile(r"META-INF/versions/\d+/module-info\.class$")
MANIFEST = "Manifest-Version: 1.0\nMulti-Release: true\nCreated-By: gha-graal shadow.py\n\n"
MODULE_INFO = "META-INF/versions/9/module-info.class"
ZIP64_LIMIT = (1 << 31) - 1


def sha512_of(path: Path) -> str:
    h = hashlib.sha512()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return "sha512:" + h.hexdigest()


def is_dropped(name: str) -> bool:
    return (name.endswith("/") or name.startswith(DROP_PREFIXES)
            or name in DROP_EXACT or bool(DROP_RE.match(name)))


def relocate(name: str) -> str:
    return NEW + name[len(OLD):] if name.startswith(OLD) else name


def compile_module_info(module: str, requires: list, base_jars: list, workdir: Path) -> bytes:
    src = workdir / "module-info.java"
    body = "".join(f"    requires transitive {m};\n" for m in requires)
    src.write_text(f"open module {module} {{\n{body}}}\n")
    out = workdir / "classes"
    # -Xlint:-module: the module names are Oracle's and end in digits (x86_64).
    cmd = ["javac", "--release", "9", "-Xlint:-module", "-d", str(out)]
    if base_jars:
        cmd += ["--module-path", os.pathsep.join(str(Path(j).resolve()) for j in base_jars)]
    cmd.append(str(src))
    subprocess.run(cmd, check=True)
    return (out / "module-info.class").read_bytes()


def shadow(src: Path, dst: Path, module: str, requires: list, base_jars: list) -> None:
    with tempfile.TemporaryDirectory() as td:
        module_info = compile_module_info(module, requires, base_jars, Path(td))
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("META-INF/MANIFEST.MF", MANIFEST)
        zout.writestr(MODULE_INFO, module_info)
        for info in zin.infolist():
            if is_dropped(info.filename):
                continue
            entry = zipfile.ZipInfo(relocate(info.filename), date_time=info.date_time)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            with zin.open(info) as fin, zout.open(entry, "w",
                                                  force_zip64=info.file_size > ZIP64_LIMIT) as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--module", required=True, help="name of the produced module")
    ap.add_argument("--requires", action="append", default=[], metavar="MODULE",
                    help="add `requires transitive MODULE` (repeatable)")
    ap.add_argument("--base-jar", action="append", default=[], metavar="JAR",
                    help="jar on javac's module path while compiling the descriptor (repeatable)")
    a = ap.parse_args(argv)
    shadow(a.input, a.output, a.module, a.requires, a.base_jar)
    print(f"{a.output.name} {sha512_of(a.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
