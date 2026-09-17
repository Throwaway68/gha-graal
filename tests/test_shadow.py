"""Tests for scripts/jars/shadow.py, the shadowed-jar builder.

They need a JDK (javac/jar) on PATH: the descriptor is compiled, then read back
with `jar --describe-module --release 9`, so what is asserted is the real module
descriptor of the produced jar, not the source text we fed to javac.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "jars"))
import shadow  # noqa: E402

needs_jdk = pytest.mark.skipif(
    shutil.which("javac") is None or shutil.which("jar") is None,
    reason="needs a JDK with javac and jar on PATH",
)

MODULE = "com.oracle.svm.shadowed.org.bytedeco.javacpp.windows.x86_64"


def make_input(tmp_path):
    src = tmp_path / "in.jar"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMulti-Release: true\nBundle-Name: JavaCPP\n")
        z.writestr("META-INF/versions/9/module-info.class", b"old")
        z.writestr("META-INF/native-image/windows-x86_64/jnijavacpp/jni-config.json", "[]")
        z.writestr("META-INF/maven/org.bytedeco/javacpp/pom.xml", "<project/>")
        z.writestr("org/bytedeco/javacpp/windows-x86_64/", b"")  # directory entry
        z.writestr("org/bytedeco/javacpp/windows-x86_64/jnijavacpp.dll", b"MZ")
    return src


def describe(jar: Path) -> str:
    return subprocess.run(
        ["jar", "--describe-module", "--file", str(jar), "--release", "9"],
        capture_output=True, text=True, check=True,
    ).stdout


def base_module_jar(tmp_path, name: str) -> Path:
    """A modular jar for `name`, to stand in for the graal base jars."""
    work = tmp_path / ("base-" + name)
    classes = work / "classes"
    src = work / "module-info.java"
    work.mkdir()
    src.write_text(f"module {name} {{}}\n")
    subprocess.run(["javac", "--release", "9", "-d", str(classes), str(src)], check=True)
    jar = tmp_path / (name + ".jar")
    subprocess.run(["jar", "--create", "--file", str(jar), "-C", str(classes), "."], check=True)
    return jar


@needs_jdk
def test_relocates_and_adds_module_info(tmp_path):
    src = make_input(tmp_path)
    out = tmp_path / "out.jar"
    shadow.shadow(src, out, module=MODULE, requires=[], base_jars=[])
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "com/oracle/svm/shadowed/org/bytedeco/javacpp/windows-x86_64/jnijavacpp.dll" in names
        assert z.read("com/oracle/svm/shadowed/org/bytedeco/javacpp/windows-x86_64/jnijavacpp.dll") == b"MZ"
        assert not any(n.startswith("org/bytedeco/") for n in names)
        assert not any(n.startswith("META-INF/native-image/") for n in names)
        assert not any(n.startswith("META-INF/maven/") for n in names)
        assert not any(n.endswith("/") for n in names)
        assert "META-INF/versions/9/module-info.class" in names
        assert z.read("META-INF/versions/9/module-info.class") != b"old"
        assert b"Multi-Release: true" in z.read("META-INF/MANIFEST.MF")
    desc = describe(out)
    assert MODULE in desc
    assert any(line.endswith(" open") for line in desc.splitlines()), desc


@needs_jdk
def test_requires_transitive_resolved_against_base_jar(tmp_path):
    base = base_module_jar(tmp_path, "com.example.base")
    out = tmp_path / "out.jar"
    shadow.shadow(make_input(tmp_path), out, module=MODULE,
                  requires=["com.example.base"], base_jars=[base])
    desc = describe(out)
    assert "requires com.example.base transitive" in desc, desc


def test_unknown_requires_is_an_error(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        shadow.shadow(make_input(tmp_path), tmp_path / "out.jar", module=MODULE,
                      requires=["no.such.module"], base_jars=[])


@needs_jdk
def test_main_prints_name_and_digest(tmp_path, capsys):
    out = tmp_path / "javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar"
    assert shadow.main([str(make_input(tmp_path)), str(out), "--module", MODULE]) == 0
    line = capsys.readouterr().out.strip()
    assert line == f"{out.name} {shadow.sha512_of(out)}"


def test_sha512_of(tmp_path):
    src = make_input(tmp_path)
    m = shadow.sha512_of(src)
    assert m.startswith("sha512:") and len(m) == 7 + 128
