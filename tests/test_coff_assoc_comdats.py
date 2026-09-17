"""Unit tests for scripts/llvm/coff-assoc-comdats.py.

Each test builds a minimal x86_64 COFF object in memory: one COMDAT '.text$x'
with an external leader symbol, one COMDAT '.xdata$x' whose only symbol is its
section definition (IMAGE_COMDAT_SELECT_ANY) - exactly the shape clang produces
for windows-gnu and link.exe rejects with LNK1143.
"""
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("coff_assoc_comdats", ROOT / "scripts" / "llvm" / "coff-assoc-comdats.py")
coff = importlib.util.module_from_spec(SPEC)
sys.modules["coff_assoc_comdats"] = coff
SPEC.loader.exec_module(coff)

SELECT_NODUPLICATES = 1
SELECT_ANY = 2
SELECT_ASSOCIATIVE = 5
TEXT_FLAGS = 0x60501020          # code, execute, read, COMDAT
XDATA_FLAGS = 0x40301040         # initialised data, read, COMDAT


def section_header(name, size, data_ptr, flags):
    return struct.pack('<8sIIIIIIHHI', name.encode(), 0, 0, size, data_ptr, 0, 0, 0, 0, flags)


def symbol(name, value, secnum, sclass, naux):
    assert len(name) <= 8
    return struct.pack('<8sIhHBB', name.encode(), value, secnum, 0, sclass, naux)


def section_def_aux(length, number, selection):
    return struct.pack('<IHHIHB3s', length, 0, 0, 0, number, selection, b'\0\0\0')


def build_object(xdata_name='.xdata$x', xdata_selection=SELECT_ANY, text_name='.text$x'):
    """A two-section object: .text$x (with a leader) and .xdata$x (leaderless)."""
    text, xdata = b'\x90\xc3', b'\x01\x00\x00\x00'
    nsec = 2
    data_start = 20 + nsec * 40
    headers = (section_header(text_name, len(text), data_start, TEXT_FLAGS)
               + section_header(xdata_name, len(xdata), data_start + len(text), XDATA_FLAGS))
    symbols = (symbol(text_name, 0, 1, coff.IMAGE_SYM_CLASS_STATIC, 1)
               + section_def_aux(len(text), 1, SELECT_NODUPLICATES)
               + symbol('x', 0, 1, 2, 0)                       # the .text$x leader
               + symbol(xdata_name, 0, 2, coff.IMAGE_SYM_CLASS_STATIC, 1)
               + section_def_aux(len(xdata), 2, xdata_selection))
    nsym = 5
    symptr = data_start + len(text) + len(xdata)
    header = struct.pack('<HHIIIHH', coff.IMAGE_FILE_MACHINE_AMD64, nsec, 0, symptr, nsym, 0, 0)
    return bytearray(header + headers + text + xdata + symbols + struct.pack('<I', 4))


def xdata_aux_offset(buf):
    """Offset of the .xdata$x section definition aux record (the last symbol record)."""
    _m, _nsec, _ts, symptr, nsym, _o, _c = struct.unpack_from('<HHIIIHH', buf, 0)
    return symptr + (nsym - 1) * 18


def test_leaderless_xdata_comdat_becomes_associative():
    buf = build_object()
    aux = xdata_aux_offset(buf)
    assert buf[aux + 14] == SELECT_ANY
    assert coff.patch_object(buf, 0, len(buf), 'probe.obj', False) == 1
    assert buf[aux + 14] == SELECT_ASSOCIATIVE
    assert struct.unpack_from('<H', buf, aux + 12)[0] == 1        # associated with section 1, .text$x


def test_already_associative_is_left_alone():
    buf = build_object(xdata_selection=SELECT_ASSOCIATIVE)
    before = bytes(buf)
    assert coff.patch_object(buf, 0, len(buf), 'probe.obj', False) == 0
    assert bytes(buf) == before


def test_pdata_is_patched_too():
    buf = build_object(xdata_name='.pdata$x')
    assert coff.patch_object(buf, 0, len(buf), 'probe.obj', False) == 1


def test_leaderless_comdat_without_sibling_is_refused():
    buf = build_object(xdata_name='.xdata$y')                     # no .text$y in the object
    with pytest.raises(coff.CoffError, match='no .text\\$y section'):
        coff.patch_object(buf, 0, len(buf), 'probe.obj', False)


def test_non_amd64_machine_is_refused():
    buf = build_object()
    struct.pack_into('<H', buf, 0, 0xAA64)                        # ARM64
    with pytest.raises(coff.CoffError, match='is not x86_64 COFF'):
        coff.patch_object(buf, 0, len(buf), 'probe.obj', False)


def test_truncated_symbol_table_is_refused():
    buf = build_object()
    with pytest.raises(coff.CoffError, match='does not fit'):
        coff.patch_object(buf, 0, len(buf) - 30, 'probe.obj', False)


def test_thin_archive_is_rejected(tmp_path):
    path = tmp_path / 'thin.a'
    path.write_bytes(b'!<thin>\n' + b'\0' * 64)
    objects, patched, errors = coff.process(str(path), False)
    assert (objects, patched) == (0, 0)
    assert errors and 'thin archives are not supported' in errors[0]
    assert path.read_bytes().startswith(b'!<thin>\n')


def test_refused_object_is_not_written(tmp_path):
    path = tmp_path / 'probe.obj'
    buf = build_object(xdata_name='.xdata$y')
    path.write_bytes(bytes(buf))
    objects, patched, errors = coff.process(str(path), False)
    assert (objects, patched) == (1, 0)
    assert errors
    assert path.read_bytes() == bytes(buf)                        # untouched


def test_archive_round_trip(tmp_path):
    """A one-member ar archive is patched in place and keeps its size."""
    member = bytes(build_object())
    name = b'probe.obj/'.ljust(16)
    header = name + b'0'.ljust(12) + b'0'.ljust(6) + b'0'.ljust(6) + b'644'.ljust(8) \
        + str(len(member)).encode().ljust(10) + b'\x60\x0a'
    blob = b'!<arch>\n' + header + member + (b'\n' if len(member) % 2 else b'')
    path = tmp_path / 'probe.a'
    path.write_bytes(blob)
    objects, patched, errors = coff.process(str(path), False)
    assert (objects, patched, errors) == (1, 1, [])
    out = path.read_bytes()
    assert len(out) == len(blob)
    aux = 8 + 60 + xdata_aux_offset(bytearray(member))
    assert out[aux + 14] == SELECT_ASSOCIATIVE


def test_main_exit_status(tmp_path, capsys):
    good = tmp_path / 'good.obj'
    good.write_bytes(bytes(build_object()))
    bad = tmp_path / 'bad.obj'
    bad.write_bytes(bytes(build_object(xdata_name='.xdata$y')))
    assert coff.main(['coff-assoc-comdats.py', str(good)]) == 0
    assert coff.main(['coff-assoc-comdats.py', str(bad)]) == 1
