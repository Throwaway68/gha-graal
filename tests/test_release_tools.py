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
