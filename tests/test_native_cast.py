"""Synthetic PE and instruction-level tests; no proprietary fixture required."""

import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "sdcard/ports/projectdiablo2/scripts/native_cast.py"
SPEC = importlib.util.spec_from_file_location("native_cast_under_test", MODULE)
native_cast = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_cast)

PE = 0x80
OPT = PE + 24
TABLE = OPT + 0xE0
HEADER = TABLE + 40
SECTION_RVA = 0x218000
SECTION_RAW = 0x200
FIXTURE_TARGET_SHA256 = "721f3c8f196d04c3997de1e5e8a13c71191d1abb1372581f786eb80de14a9093"


def fixture():
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, PE)
    data[PE:PE + 4] = b"PE\0\0"
    struct.pack_into("<HH", data, PE + 4, 0x14C, 1)
    struct.pack_into("<H", data, PE + 20, 0xE0)
    struct.pack_into("<H", data, OPT, 0x10B)
    struct.pack_into("<I", data, OPT + 4, 0x1000)
    struct.pack_into("<II", data, OPT + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, OPT + 56, 0x518000, 0x200)
    struct.pack_into("<I", data, OPT + 64, 0x12345678)
    struct.pack_into("<8sIIIIIIHHI", data, TABLE, b".text\0\0\0", 0x300000,
                     SECTION_RVA, 0x1000, SECTION_RAW, 0, 0, 0, 0, 0x60000020)
    for rva, preimage in native_cast.CALLSITES:
        offset = SECTION_RAW + rva - SECTION_RVA
        data[offset:offset + 5] = preimage
    return bytes(data)


def pins(source, target_hash=FIXTURE_TARGET_SHA256, target_size=0x1400):
    return patch.multiple(native_cast, SOURCE_SIZE=len(source),
                          SOURCE_SHA256=hashlib.sha256(source).hexdigest(),
                          TARGET_SIZE=target_size, TARGET_SHA256=target_hash)


class WrapperMachine:
    """Tiny strict decoder for emitted i386 subset, including stack/call ABI."""

    def __init__(self, base, native, width, height, y):
        self.base = base
        self.rva = 0x518000
        self.start = base + self.rva
        self.code = native_cast._wrapper(self.rva)
        self.ip = self.start
        self.reg = [0x101 + i * 0x111 for i in range(8)]  # EAX..EDI
        self.reg[4] = 0x900000
        self.initial_reg = list(self.reg)
        self.flags = 0xA47
        self.initial_flags = self.flags
        self.xmm = tuple(bytes([i]) * 16 for i in range(8))
        self.initial_xmm = self.xmm
        self.memory = {}
        self.writes = []
        self.event = 0xBADF00D
        self.return_to = 0x12345678
        self.memory[self.reg[4]] = self.return_to
        self.memory[self.reg[4] + 4] = self.event
        self.memory[base + 0x3D9867] = native
        for slot, address, value in ((0x4DCEE8, 0x800000, width),
                                     (0x4DCE08, 0x800004, height),
                                     (0x4DCE14, 0x800008, y)):
            self.memory[base + slot] = address
            self.memory[address] = value & 0xFFFFFFFF
        self.original_calls = 0
        self.compare = (0, 0)

    def push(self, value):
        self.reg[4] -= 4
        self.memory[self.reg[4]] = value

    def pop(self):
        value = self.memory[self.reg[4]]
        self.reg[4] += 4
        return value

    def run(self):
        for _ in range(100):
            offset = self.ip - self.start
            op = self.code[offset]
            if op == 0x9C:
                self.push(self.flags)
                self.ip += 1
            elif op == 0x60:
                old_sp = self.reg[4]
                for index in (0, 1, 2, 3, 4, 5, 6, 7):
                    self.push(old_sp if index == 4 else self.reg[index])
                self.ip += 1
            elif op == 0xE8:
                target = self.ip + 5 + struct.unpack_from("<i", self.code, offset + 1)[0]
                self.push(self.ip + 5)
                if target == self.base + native_cast.ORIGINAL_TARGET_RVA:
                    self.original_calls += 1
                    assert self.memory[self.reg[4] + 4] == self.event
                    assert self.reg[4] == self.initial_reg[4] - 8
                    assert self.flags == self.initial_flags
                    assert self.xmm == self.initial_xmm
                    assert all(self.reg[i] == self.initial_reg[i]
                               for i in range(8) if i != 4)
                    # Stand in for original's own register/flag semantics.
                    self.reg[0] = 0xC0FFEE
                    self.flags = 0x202
                    self.ip = self.pop()
                    self.reg[4] += 4  # original stdcall ret 4
                else:
                    assert target == self.start + 7  # local call/pop only
                    self.ip = target
            elif op == 0x5B:
                self.reg[3] = self.pop()
                self.ip += 1
            elif self.code[offset:offset + 2] == b"\x80\xbb":
                disp = struct.unpack_from("<i", self.code, offset + 2)[0]
                self.compare = (self.memory[self.reg[3] + disp] & 255,
                                self.code[offset + 6])
                self.flags = 0
                self.ip += 7
            elif self.code[offset:offset + 2] == b"\x8b\x83":
                disp = struct.unpack_from("<i", self.code, offset + 2)[0]
                self.reg[0] = self.memory[self.reg[3] + disp]
                self.ip += 6
            elif self.code[offset:offset + 2] == b"\x81\x38":
                value = self.memory[self.reg[0]]
                value = value if value < 0x80000000 else value - 0x100000000
                self.compare = (value, struct.unpack_from("<i", self.code, offset + 2)[0])
                self.flags = 0
                self.ip += 6
            elif op in (0x75, 0x7E):
                taken = (self.compare[0] != self.compare[1] if op == 0x75
                         else self.compare[0] <= self.compare[1])
                jump = struct.unpack_from("<b", self.code, offset + 1)[0]
                self.ip += 2 + (jump if taken else 0)
            elif self.code[offset:offset + 2] == b"\xc7\x00":
                value = struct.unpack_from("<I", self.code, offset + 2)[0]
                self.memory[self.reg[0]] = value
                self.writes.append((self.reg[0], value))
                self.ip += 6
            elif op == 0x61:
                for index in (7, 6, 5, 4, 3, 2, 1, 0):
                    value = self.pop()
                    if index != 4:
                        self.reg[index] = value
                self.ip += 1
            elif op == 0x9D:
                self.flags = self.pop()
                self.ip += 1
            elif self.code[offset:offset + 4] == b"\xff\x74\x24\x04":
                self.push(self.memory[self.reg[4] + 4])
                self.ip += 4
            elif op == 0xC2:
                assert struct.unpack_from("<H", self.code, offset + 1)[0] == 4
                assert self.pop() == self.return_to
                self.reg[4] += 4
                assert self.reg[4] == self.initial_reg[4] + 8
                assert self.reg[0] == 0xC0FFEE and self.flags == 0x202
                assert all(self.reg[i] == self.initial_reg[i]
                           for i in (1, 2, 3, 5, 6, 7))
                assert self.xmm == self.initial_xmm
                assert self.original_calls == 1
                return
            else:
                raise AssertionError("unexpected opcode at %x: %02x" % (offset, op))
        raise AssertionError("wrapper did not return")


class NativeCastTests(unittest.TestCase):
    def setUp(self):
        self.source = fixture()

    def build(self):
        with pins(self.source):
            return native_cast.native_cast_bytes(self.source)

    def test_determinism_and_pinned_fixture_hash(self):
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual(hashlib.sha256(first).hexdigest(), FIXTURE_TARGET_SHA256)
        self.assertEqual(len(first), 0x1400)
        self.assertIsInstance(first, bytes)
        self.assertEqual(self.source, fixture())

    def test_unknown_source_size_and_hash(self):
        for source in (b"", self.source, b"MZ" + b"\0" * (native_cast.SOURCE_SIZE - 2)):
            with self.subTest(size=len(source)), self.assertRaisesRegex(ValueError, "unknown"):
                native_cast.native_cast_bytes(source)
        with pins(self.source), self.assertRaisesRegex(ValueError, "unknown"):
            native_cast.native_cast_bytes(self.source[:-1] + b"x")

    def test_target_hash_and_size_fail_closed(self):
        for kwargs in ({"target_hash": "0" * 64}, {"target_size": 1}):
            with pins(self.source, **kwargs), self.assertRaisesRegex(ValueError, "target integrity"):
                native_cast.native_cast_bytes(self.source)

    def test_exact_preimages(self):
        for rva, old in native_cast.CALLSITES:
            changed = bytearray(self.source)
            changed[SECTION_RAW + rva - SECTION_RVA + 1] ^= 1
            with pins(changed), self.assertRaisesRegex(ValueError, "preimage"):
                native_cast.native_cast_bytes(changed)

    def test_header_and_format_guards(self):
        mutations = ((0, b"NO"), (PE, b"PX\0\0"),
                     (PE + 4, struct.pack("<H", 0x8664)),
                     (OPT, struct.pack("<H", 0x20B)),
                     (HEADER, b"x"),
                     (OPT + 60, struct.pack("<I", HEADER + 39)),
                     (TABLE + 20, struct.pack("<I", HEADER + 39)),
                     (OPT + 36, b"\0" * 4),
                     (TABLE, b".r2fix\0\0"),
                     (0x3C, b"\xff" * 4))
        for offset, value in mutations:
            changed = bytearray(self.source)
            changed[offset:offset + len(value)] = value
            with self.subTest(offset=offset), pins(changed), self.assertRaises(ValueError):
                native_cast.native_cast_bytes(changed)

    def test_byte_patch_scope_and_pe_metadata(self):
        result = self.build()
        allowed = set()
        for offset, size in ((PE + 6, 2), (OPT + 4, 4), (OPT + 56, 4),
                             (OPT + 64, 4), (HEADER, 40)):
            allowed.update(range(offset, offset + size))
        for rva, old in native_cast.CALLSITES:
            offset = SECTION_RAW + rva - SECTION_RVA
            allowed.update(range(offset, offset + 5))
        changed = {i for i, (old, new) in enumerate(zip(self.source, result)) if old != new}
        self.assertTrue(changed <= allowed)
        name, vs, vr, rs, rp, rel, line, nr, nl, flags = struct.unpack_from(
            "<8sIIIIIIHHI", result, HEADER)
        self.assertEqual((name, vs, vr, rs, rp, rel, line, nr, nl, flags),
                         (b".r2fix\0\0", 79, 0x518000, 0x200, 0x1200,
                          0, 0, 0, 0, 0xE0000020))
        self.assertEqual(struct.unpack_from("<H", result, PE + 6)[0], 2)
        self.assertEqual(struct.unpack_from("<I", result, OPT + 4)[0], 0x1200)
        self.assertEqual(struct.unpack_from("<I", result, OPT + 56)[0], 0x519000)
        self.assertEqual(struct.unpack_from("<I", result, OPT + 64)[0], 0)
        self.assertEqual(result[rp:rp + vs], native_cast._wrapper(vr))
        self.assertEqual(result[rp + vs:], b"\0" * (rs - vs))
        # Entire data-directory block (including base relocations) stays identical.
        self.assertEqual(result[OPT + 96:TABLE], self.source[OPT + 96:TABLE])

    def test_both_call_targets_and_original_tail(self):
        result = self.build()
        for rva, old in native_cast.CALLSITES:
            offset = SECTION_RAW + rva - SECTION_RVA
            self.assertEqual(result[offset], 0xE8)
            self.assertEqual(rva + 5 + struct.unpack_from("<i", result, offset + 1)[0],
                             0x518000)
        code = native_cast._wrapper(0x518000)
        self.assertEqual(code[-14:-7], b"\x61\x9d\xff\x74\x24\x04\xe8")
        self.assertEqual(0x518000 + len(code) - 3 + struct.unpack_from("<i", code, len(code) - 7)[0],
                         native_cast.ORIGINAL_TARGET_RVA)
        self.assertEqual(code[-3:], b"\xc2\x04\x00")

    def test_signed_y_guards_relocation_and_abi(self):
        cases = ((1, 640, 480, 431, False), (1, 640, 480, 432, True),
                 (1, 640, 480, 547, True), (1, 640, 480, -1, False),
                 (1, 640, 480, -2147483648, False),
                 (1, 640, 480, 2147483647, True),
                 (0, 640, 480, 547, False), (2, 640, 480, 547, False),
                 (1, 800, 600, 547, False), (1, 800, 480, 547, False),
                 (1, 640, 600, 547, False))
        for base in (0x10000000, 0x65000000):
            for native, width, height, y, resets in cases:
                with self.subTest(base=base, native=native, width=width, height=height, y=y):
                    machine = WrapperMachine(base, native, width, height, y)
                    machine.run()
                    self.assertEqual(machine.memory[0x800008],
                                     240 if resets else y & 0xFFFFFFFF)
                    self.assertEqual(machine.writes, [(0x800008, 240)] if resets else [])

    def test_file_api_only_reads(self):
        with pins(self.source), patch.object(native_cast.Path, "read_bytes", return_value=self.source) as read:
            self.assertEqual(native_cast.native_cast_file("private.dll"), self.build())
            read.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
