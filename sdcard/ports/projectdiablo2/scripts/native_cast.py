"""Build the private, pinned R36S native-cast derivative entirely in memory.

No DLL is shipped or written by this module. Only the two native dispatch calls
are redirected; the original sender and its render-boundary guard stay intact.
"""

import hashlib
from pathlib import Path
import struct

SOURCE_SIZE = 4312576
SOURCE_SHA256 = "538a77b7ccef3d5334e56c4e9e57a4d8fc69a1e27c46beb694c0dedfcfbf9cb3"
TARGET_SIZE = 4313088
TARGET_SHA256 = "d81426020df70aca95ac49cc92c918a46dc0ec3303386b3e865a629ee7a04c21"
CALLSITES = ((0x2180FD, bytes.fromhex("e8de1b0400")),
             (0x21863F, bytes.fromhex("e89c160400")))
ORIGINAL_TARGET_RVA = 0x259CE0


def _align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def _wrapper(rva):
    """PC-relative i386 stdcall(event*) wrapper; no imports or relocations."""
    code = bytearray(b"\x9c\x60\xe8\x00\x00\x00\x00\x5b")
    pc = rva + 7  # CALL pushes the address of POP EBX.
    branches = []

    def disp(address):
        return struct.pack("<i", address - pc)

    def skip(opcode):
        code.extend(bytes((opcode, 0)))
        branches.append(len(code) - 1)

    code.extend(b"\x80\xbb" + disp(0x3D9867) + b"\x01")
    skip(0x75)  # native controller only
    code.extend(b"\x8b\x83" + disp(0x4DCEE8))
    code.extend(b"\x81\x38" + struct.pack("<I", 640))
    skip(0x75)
    code.extend(b"\x8b\x83" + disp(0x4DCE08))
    code.extend(b"\x81\x38" + struct.pack("<I", 480))
    skip(0x75)
    code.extend(b"\x8b\x83" + disp(0x4DCE14))
    code.extend(b"\x81\x38" + struct.pack("<i", 431))
    skip(0x7E)  # signed JLE: legitimate Y=431 is not changed
    code.extend(b"\xc7\x00" + struct.pack("<i", 240))
    restore = len(code)
    for branch in branches:
        code[branch] = restore - (branch + 1)
    code.extend(b"\x61\x9d\xff\x74\x24\x04")  # restore; duplicate event
    code.extend(b"\xe8" + struct.pack(
        "<i", ORIGINAL_TARGET_RVA - (rva + len(code) + 5)))
    code.extend(b"\xc2\x04\x00")
    return bytes(code)


def _build(source):
    """Structural checks remain independent of the public source hash gate."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(len(source) >= 0x40 and source[:2] == b"MZ", "not a DOS/PE image")
    pe = struct.unpack_from("<I", source, 0x3C)[0]
    require(0x40 <= pe <= len(source) - 24, "invalid PE header offset")
    require(source[pe:pe + 4] == b"PE\0\0", "invalid PE signature")
    machine, count = struct.unpack_from("<HH", source, pe + 4)
    require(machine == 0x14C, "source must be i386")
    optional_size = struct.unpack_from("<H", source, pe + 20)[0]
    opt = pe + 24
    table = opt + optional_size
    require(optional_size >= 96 and table <= len(source), "invalid optional header")
    require(struct.unpack_from("<H", source, opt)[0] == 0x10B,
            "source must be PE32")
    require(0 < count < 0xFFFF and table + (count + 1) * 40 <= len(source),
            "invalid section table")
    section_alignment, file_alignment = struct.unpack_from("<II", source, opt + 32)
    require(file_alignment > 0 and file_alignment & (file_alignment - 1) == 0
            and section_alignment >= file_alignment
            and section_alignment & (section_alignment - 1) == 0,
            "invalid PE alignment")
    sections = [struct.unpack_from("<8sIIII", source, table + i * 40)
                for i in range(count)]
    for name, virtual_size, virtual_rva, raw_size, raw_offset in sections:
        require(name.rstrip(b"\0") != b".r2fix", "already patched section")
        require(raw_offset + raw_size <= len(source), "section outside source")
        require(virtual_rva + max(virtual_size, raw_size) <= 0xFFFFFFFF,
                "section RVA overflow")
    raw_offsets = [s[4] for s in sections if s[3]]
    require(bool(raw_offsets), "no raw sections")
    header = table + count * 40
    size_headers = struct.unpack_from("<I", source, opt + 60)[0]
    require(header + 40 <= min(raw_offsets) and header + 40 <= size_headers
            and size_headers <= len(source) and not any(source[header:header + 40]),
            "no zero section header space")

    def file_offset(rva, size):
        matches = [rp + rva - vr for _, vs, vr, rs, rp in sections
                   if vr <= rva and rva + size <= vr + rs]
        require(len(matches) == 1, "unmapped or ambiguous callsite")
        return matches[0]

    patches = []
    for rva, preimage in CALLSITES:
        offset = file_offset(rva, len(preimage))
        require(source[offset:offset + len(preimage)] == preimage,
                "changed callsite preimage")
        patches.append((rva, offset))
    rva = _align(max(vr + max(vs, rs) for _, vs, vr, rs, rp in sections),
                 section_alignment)
    raw = _align(len(source), file_alignment)
    code = _wrapper(rva)
    raw_size = _align(len(code), file_alignment)
    image_size = _align(rva + len(code), section_alignment)
    code_size = struct.unpack_from("<I", source, opt + 4)[0] + raw_size
    require(max(raw + raw_size, image_size, code_size) <= 0xFFFFFFFF,
            "PE size overflow")
    result = bytearray(source)
    for call_rva, offset in patches:
        result[offset:offset + 5] = b"\xe8" + struct.pack("<i", rva - call_rva - 5)
    result.extend(b"\0" * (raw - len(result)))
    result.extend(code + b"\0" * (raw_size - len(code)))
    struct.pack_into("<H", result, pe + 6, count + 1)
    struct.pack_into("<I", result, opt + 4, code_size)
    struct.pack_into("<I", result, opt + 56, image_size)
    struct.pack_into("<I", result, opt + 64, 0)
    struct.pack_into("<8sIIIIIIHHI", result, header, b".r2fix\0\0", len(code),
                     rva, raw_size, raw, 0, 0, 0, 0, 0xE0000020)
    return bytes(result)


def native_cast_bytes(source):
    """Return pinned derivative bytes; reject unknown/modified input or output."""
    if len(source) != SOURCE_SIZE or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("unknown native-cast source")
    result = _build(source)
    if len(result) != TARGET_SIZE or hashlib.sha256(result).hexdigest() != TARGET_SHA256:
        raise ValueError("native-cast target integrity mismatch")
    return result


def native_cast_file(path):
    """Read source only; return derivative in memory without writing any DLL."""
    return native_cast_bytes(Path(path).read_bytes())
