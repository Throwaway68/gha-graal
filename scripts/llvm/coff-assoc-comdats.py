#!/usr/bin/env python3
"""Make the unwind COMDATs of a mingw-target COFF archive linkable by MSVC's link.exe.

    coff-assoc-comdats.py <archive.a|object.obj> ...

Clang emits one COMDAT per function when the function's section is a COMDAT
(-ffunction-sections, or a linkonce_odr C++ method).  For the MSVC target the
companion .xdata/.pdata sections are IMAGE_COMDAT_SELECT_ASSOCIATIVE with the
function's section, but for windows-gnu targets LLVM deliberately avoids
associative COMDATs (MCStreamer.cpp: "In a GNU environment, we can't use
associative comdats") and emits '.xdata$<fn>' / '.pdata$<fn>' as
IMAGE_COMDAT_SELECT_ANY sections whose only symbol is the section symbol.
GNU ld keys those off the section name; link.exe wants a leader symbol and
fails with

    fatal error LNK1143: invalid or corrupt file: no symbol for COMDAT section 0x5

This rewrites exactly those section definitions to SELECT_ASSOCIATIVE pointing
at the matching '.text$<fn>' section, which is what the MSVC target emits
anyway.  Every edit is in place and keeps the file size, so the archive index
stays valid.  Exits non-zero if a leaderless non-associative COMDAT remains.
"""
import struct
import sys

IMAGE_SCN_LNK_COMDAT = 0x00001000
IMAGE_COMDAT_SELECT_ASSOCIATIVE = 5
IMAGE_SYM_CLASS_STATIC = 3
MACHINE_AMD64 = 0x8664


def patch_coff(buf, base, size, name, verbose):
    """Patch one COFF object living at buf[base:base+size]. Returns (patched, remaining)."""
    machine, nsec, _ts, symptr, nsym, _osz, _ch = struct.unpack_from('<HHIIIHH', buf, base)
    if machine != MACHINE_AMD64 or nsec == 0 or symptr == 0:
        return 0, 0
    strtab = base + symptr + nsym * 18

    def string_at(off):
        end = buf.index(b'\0', strtab + off)
        return buf[strtab + off:end].decode('latin1')

    sections = {}          # index -> (name, characteristics)
    for i in range(nsec):
        off = base + 20 + i * 40
        raw, _vs, _va, _sz, _p, _rp, _lp, _nr, _nl, chars = struct.unpack_from('<8sIIIIIIHHI', buf, off)
        sname = raw.rstrip(b'\0').decode('latin1')
        if sname.startswith('/'):
            sname = string_at(int(sname[1:]))
        sections[i + 1] = (sname, chars)
    by_name = {n: i for i, (n, _c) in sections.items()}

    secdef_aux = {}        # index -> file offset of the section definition aux record
    has_leader = set()     # indices with a symbol other than the section definition
    i = 0
    while i < nsym:
        off = base + symptr + i * 18
        _val, secnum, _typ, sclass, naux = struct.unpack_from('<IhHBB', buf, off + 8)
        if secnum > 0:
            if sclass == IMAGE_SYM_CLASS_STATIC and naux == 1 and secnum not in secdef_aux:
                secdef_aux[secnum] = off + 18
            else:
                has_leader.add(secnum)
        i += 1 + naux

    patched = remaining = 0
    for idx, (sname, chars) in sections.items():
        if not chars & IMAGE_SCN_LNK_COMDAT or idx in has_leader:
            continue
        aux = secdef_aux.get(idx)
        if aux is None:
            remaining += 1
            continue
        selection = buf[aux + 14]
        if selection == IMAGE_COMDAT_SELECT_ASSOCIATIVE:
            continue
        prefix, _, suffix = sname.partition('$')
        target = by_name.get('.text$' + suffix) if prefix in ('.xdata', '.pdata') and suffix else None
        if target is None:
            remaining += 1
            print(f"  {name}: leaderless COMDAT [{idx}] {sname} (selection {selection}) has no .text sibling",
                  file=sys.stderr)
            continue
        struct.pack_into('<H', buf, aux + 12, target)
        buf[aux + 14] = IMAGE_COMDAT_SELECT_ASSOCIATIVE
        patched += 1
        if verbose:
            print(f"  {name}: [{idx}] {sname} -> associative with [{target}] .text${suffix}")
    return patched, remaining


def members(buf):
    """Yield (name, offset, size) for every member of a GNU ar archive."""
    off = 8
    longnames = b''
    while off + 60 <= len(buf):
        header = bytes(buf[off:off + 60])
        name = header[0:16].decode('latin1').rstrip()
        size = int(header[48:58].decode('latin1').strip())
        body = off + 60
        if name.startswith('//'):
            longnames = bytes(buf[body:body + size])
        elif name.startswith('/') and name[1:].strip().isdigit():
            start = int(name[1:])
            end = min(x for x in (longnames.find(b'\0', start), longnames.find(b'\n', start)) if x != -1)
            yield longnames[start:end].decode('latin1').rstrip('/'), body, size
        elif name not in ('/', '//', '/SYM64/'):
            yield name.rstrip('/'), body, size
        off = body + size + (size & 1)


def main(argv):
    verbose = '-v' in argv
    paths = [a for a in argv[1:] if not a.startswith('-')]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for path in paths:
        with open(path, 'rb') as f:
            buf = bytearray(f.read())
        patched = remaining = 0
        if buf[:8] == b'!<arch>\n':
            for name, off, size in members(buf):
                p, r = patch_coff(buf, off, size, name, verbose)
                patched += p
                remaining += r
        else:
            patched, remaining = patch_coff(buf, 0, len(buf), path, verbose)
        with open(path, 'wb') as f:
            f.write(buf)
        print(f"{path}: {patched} COMDAT section(s) made associative, {remaining} still without a leader symbol")
        if remaining:
            rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
