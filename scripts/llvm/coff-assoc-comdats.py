#!/usr/bin/env python3
"""Make the unwind COMDATs of a mingw-target COFF archive linkable by MSVC's link.exe.

    coff-assoc-comdats.py [-v] <archive.a|object.obj> ...

Clang emits one COMDAT per function when the function's section is a COMDAT
(-ffunction-sections, or a linkonce_odr C++ method).  For the MSVC target the
companion .xdata/.pdata sections are IMAGE_COMDAT_SELECT_ASSOCIATIVE with the
function's section, but for windows-gnu targets LLVM deliberately avoids
associative COMDATs (llvm/lib/MC/MCStreamer.cpp: "In a GNU environment, we
can't use associative comdats") and emits '.xdata$<fn>' / '.pdata$<fn>' as
IMAGE_COMDAT_SELECT_ANY sections whose only symbol is the section symbol.
GNU ld keys those off the section name; link.exe wants a leader symbol and
fails with

    fatal error LNK1143: invalid or corrupt file: no symbol for COMDAT section 0x5

This rewrites exactly those section definitions to SELECT_ASSOCIATIVE pointing
at the matching '.text$<fn>' section, which is what the MSVC target emits
anyway.  Every edit is in place and keeps the file size, so the archive index
stays valid.

The rewriter only ever writes a file when it understood every byte it looked
at: anything unexpected (a member that is not an x86_64 COFF object, a thin
archive, a truncated table, a COMDAT whose section definition does not look
like one, a leaderless COMDAT with no sibling to associate with) is an error,
nothing is written and the exit status is non-zero.
"""
import struct
import sys

IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_SCN_LNK_COMDAT = 0x00001000
IMAGE_COMDAT_SELECT_ASSOCIATIVE = 5
IMAGE_SYM_CLASS_STATIC = 3
COFF_HEADER_SIZE = 20
SECTION_HEADER_SIZE = 40
SYMBOL_SIZE = 18
ARCHIVE_MAGIC = b'!<arch>\n'
THIN_ARCHIVE_MAGIC = b'!<thin>\n'


class CoffError(Exception):
    """Anything about the input we do not understand."""


def _section_name(raw, string_at, what):
    name = raw.rstrip(b'\0').decode('latin1')
    if not name.startswith('/'):
        return name
    digits = name[1:]
    if not digits.isdigit():
        raise CoffError(f"{what}: section name {name!r} is not a decimal string table offset")
    return string_at(int(digits), what)


def patch_object(buf, base, size, name, verbose):
    """Patch one COFF object at buf[base:base + size]. Returns the number of patched sections."""
    end = base + size
    if size < COFF_HEADER_SIZE:
        raise CoffError(f"{name}: {size} bytes is too small for a COFF header")
    machine, nsec, _stamp, symptr, nsym, opthdr, _chars = struct.unpack_from('<HHIIIHH', buf, base)
    if machine != IMAGE_FILE_MACHINE_AMD64:
        raise CoffError(f"{name}: machine 0x{machine:04x} is not x86_64 COFF "
                        "(bigobj, import members and other architectures are not understood)")
    if nsec == 0:
        raise CoffError(f"{name}: no sections")
    if symptr == 0 or nsym == 0:
        raise CoffError(f"{name}: no symbol table")

    sec_base = base + COFF_HEADER_SIZE + opthdr
    if sec_base + nsec * SECTION_HEADER_SIZE > end:
        raise CoffError(f"{name}: {nsec} section headers do not fit in {size} bytes")
    symtab = base + symptr
    symtab_end = symtab + nsym * SYMBOL_SIZE
    if symptr < COFF_HEADER_SIZE or symtab_end > end:
        raise CoffError(f"{name}: symbol table (offset {symptr}, {nsym} entries) does not fit in {size} bytes")

    strtab = symtab_end
    if strtab + 4 <= end:
        strtab_size = struct.unpack_from('<I', buf, strtab)[0]
        strtab_end = strtab + strtab_size if 4 <= strtab_size <= end - strtab else end
    else:
        strtab_end = end

    def string_at(off, what):
        if off < 4 or strtab + off >= strtab_end:
            raise CoffError(f"{what}: string table offset {off} is outside the member")
        stop = buf.find(b'\0', strtab + off, strtab_end)
        if stop < 0:
            raise CoffError(f"{what}: unterminated string at string table offset {off}")
        return buf[strtab + off:stop].decode('latin1')

    sections = {}   # index -> (name, characteristics)
    for i in range(nsec):
        off = sec_base + i * SECTION_HEADER_SIZE
        raw, _vs, _va, _sz, _ptr, _rp, _lp, _nr, _nl, chars = struct.unpack_from('<8sIIIIIIHHI', buf, off)
        sections[i + 1] = (_section_name(raw, string_at, f"{name}: section {i + 1}"), chars)
    by_name = {n: i for i, (n, _c) in sections.items()}

    secdef = {}     # index -> offset of its section definition aux record
    has_leader = set()
    i = 0
    while i < nsym:
        off = symtab + i * SYMBOL_SIZE
        raw = bytes(buf[off:off + 8])
        value, secnum, _typ, sclass, naux = struct.unpack_from('<IhHBB', buf, off + 8)
        if off + (1 + naux) * SYMBOL_SIZE > symtab_end:
            raise CoffError(f"{name}: symbol {i} claims {naux} auxiliary records past the symbol table")
        if secnum > 0:
            if secnum > nsec:
                raise CoffError(f"{name}: symbol {i} refers to section {secnum} of {nsec}")
            sym_name = string_at(struct.unpack_from('<I', raw, 4)[0], f"{name}: symbol {i}") \
                if raw[:4] == b'\0\0\0\0' else raw.rstrip(b'\0').decode('latin1')
            is_secdef = (sclass == IMAGE_SYM_CLASS_STATIC and naux >= 1 and value == 0
                         and sym_name == sections[secnum][0])
            if is_secdef and secnum not in secdef:
                secdef[secnum] = off + SYMBOL_SIZE
            else:
                has_leader.add(secnum)
        i += 1 + naux

    patched = 0
    for idx, (sname, chars) in sections.items():
        if not chars & IMAGE_SCN_LNK_COMDAT or idx in has_leader:
            continue
        aux = secdef.get(idx)
        if aux is None:
            raise CoffError(f"{name}: COMDAT section [{idx}] {sname} has neither a leader "
                            "nor a section definition symbol")
        if buf[aux + 14] == IMAGE_COMDAT_SELECT_ASSOCIATIVE:
            continue
        prefix, _, suffix = sname.partition('$')
        sibling = '.text$' + suffix if prefix in ('.xdata', '.pdata') and suffix else None
        target = by_name.get(sibling) if sibling else None
        if target is None:
            raise CoffError(f"{name}: leaderless COMDAT [{idx}] {sname} (selection {buf[aux + 14]}) "
                            f"has no {sibling or '.text$<fn>'} section to associate with")
        if not sections[target][1] & IMAGE_SCN_LNK_COMDAT:
            raise CoffError(f"{name}: [{idx}] {sname} would associate with the non-COMDAT section {sibling}")
        struct.pack_into('<H', buf, aux + 12, target)
        buf[aux + 14] = IMAGE_COMDAT_SELECT_ASSOCIATIVE
        patched += 1
        if verbose:
            print(f"  {name}: [{idx}] {sname} -> associative with [{target}] {sibling}")
    return patched


def members(buf):
    """Yield (name, offset, size) for every real member of a GNU ar archive."""
    off = len(ARCHIVE_MAGIC)
    longnames = b''
    while off < len(buf):
        if off + 60 > len(buf):
            raise CoffError(f"truncated archive member header at offset {off}")
        header = bytes(buf[off:off + 60])
        if header[58:60] != b'\x60\x0a':
            raise CoffError(f"bad archive member header magic at offset {off}")
        name = header[0:16].decode('latin1').rstrip()
        try:
            size = int(header[48:58].decode('latin1').strip())
        except ValueError:
            raise CoffError(f"unparsable member size at offset {off}")
        body = off + 60
        if body + size > len(buf):
            raise CoffError(f"member {name!r} at offset {off} runs past the end of the archive")
        if name.startswith('//'):
            longnames = bytes(buf[body:body + size])
        elif name.startswith('/') and name[1:].strip().isdigit():
            start = int(name[1:])
            stops = [x for x in (longnames.find(b'\0', start), longnames.find(b'\n', start)) if x != -1]
            if not stops or start >= len(longnames):
                raise CoffError(f"member name offset {start} is outside the archive string table")
            yield longnames[start:min(stops)].decode('latin1').rstrip('/'), body, size
        elif name not in ('/', '//', '/SYM64/'):
            yield name.rstrip('/'), body, size
        off = body + size + (size & 1)


def process(path, verbose):
    """Patch one file. Returns (objects, patched, [errors]); writes only when there are no errors."""
    with open(path, 'rb') as handle:
        buf = bytearray(handle.read())
    objects = patched = 0
    errors = []
    if buf[:len(THIN_ARCHIVE_MAGIC)] == THIN_ARCHIVE_MAGIC:
        return 0, 0, [f"{path}: thin archives are not supported; "
                      "re-create the archive without --thin so the members can be rewritten"]
    if buf[:len(ARCHIVE_MAGIC)] == ARCHIVE_MAGIC:
        try:
            for name, off, size in members(buf):
                objects += 1
                try:
                    patched += patch_object(buf, off, size, f"{path}({name})", verbose)
                except CoffError as exc:
                    errors.append(str(exc))
        except CoffError as exc:
            errors.append(f"{path}: {exc}")
    else:
        objects = 1
        try:
            patched += patch_object(buf, 0, len(buf), path, verbose)
        except CoffError as exc:
            errors.append(str(exc))
    if not objects:
        errors.append(f"{path}: no COFF object found")
    if not errors:
        with open(path, 'wb') as handle:
            handle.write(buf)
    return objects, patched, errors


def main(argv):
    verbose = '-v' in argv
    paths = [a for a in argv[1:] if not a.startswith('-')]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for path in paths:
        objects, patched, errors = process(path, verbose)
        for message in errors:
            print(message, file=sys.stderr)
        if errors:
            print(f"{path}: NOT rewritten, {len(errors)} problem(s)", file=sys.stderr)
            rc = 1
        else:
            print(f"{path}: {objects} object(s), {patched} COMDAT section(s) made associative")
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
