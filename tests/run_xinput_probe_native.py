#!/usr/bin/env python3
"""Synthetic host Windows x86 probe tests; never proof of Wine/handheld input.

Run tools/test_xinput_probe.cmd from any directory. MSVC must be installed at
its documented path. All generated sources, objects, DLLs, EXEs and reports stay
in a fresh project .state/xinput-native-tests/run-* folder for inspection.
No production binary is built or changed. Child stdio is inherited, not piped.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

KEYS = 'a b y x start select menu l1 l2 l3 r1 r2 r3 up down left right'.split()
import uuid

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def run(command):
    subprocess.run([str(arg) for arg in command], check=True, timeout=60)


def assert_x86(path):
    with path.open("rb") as source:
        header = source.read(64)
        assert header[:2] == b"MZ", "not PE"
        source.seek(struct.unpack_from("<I", header, 60)[0])
        assert source.read(6) == b"PE\0\0\x4c\x01", "not x86 PE"


def build_stub(directory, name, definition):
    dll = directory / (name + ".dll")
    run(["cl", "/nologo", "/std:c11", "/O1", "/MT", "/W4", "/LD",
         "/Fo" + str(directory / (name + ".obj")),
         "/Fe" + str(dll), TESTS / "xinput_probe_stub.c", "/link", "/MACHINE:X86",
         "/Brepro", "/DEF:" + str(TESTS / definition),
         "/IMPLIB:" + str(directory / (name + ".lib"))])
    assert_x86(dll)
    return dll


def build_probe(directory, name, dll, report, duration=1700):
    source = directory / (name + ".c")
    source.write_text(
        f"#define DURATION_MS {duration}UL\n"
        + "#define RESULT_PATH " + json.dumps(str(report)) + "\n"
        + "#define XINPUT_DLL " + json.dumps(str(dll)) + "\n"
        + "#include " + json.dumps(str(ROOT / "tools/xinput_probe.c")) + "\n",
        encoding="ascii")
    exe = directory / (name + ".exe")
    run(["cl", "/nologo", "/std:c11", "/O1", "/MT", "/W4",
         "/D_WIN32_WINNT=0x0601", "/DWINVER=0x0601",
         "/Fo" + str(directory / (name + ".obj")), "/Fe" + str(exe), source,
         "/link", "/MACHINE:X86", "/SUBSYSTEM:WINDOWS,6.01", "/Brepro",
         "user32.lib", "gdi32.lib"])
    assert_x86(exe)
    return exe


def expected(api="ready", devices="ready", buttons="unchanged", axes="unchanged",
             controls=None, physical=None, guide=False):
    if controls is None:
        controls = dict.fromkeys(KEYS, 'not_seen' if devices == 'ready' else 'unavailable')
        if devices == 'ready' and not guide:
            controls['menu'] = 'unsupported'
    return dict(schema_version=2, api=api, devices=devices, buttons=buttons, axes=axes,
                controls=controls, physical_controls=physical or dict.fromkeys(KEYS, 'unavailable'))


def exercise(exe, report, mode, wanted, rc=0, physical=None, live=False):
    # Each test has its own report; no stale output can satisfy another case.
    assert not report.exists(), "report unexpectedly exists before test"
    step_path = report.parent / 'pd2-button-step.txt'
    physical_path = report.parent / 'pd2-button-physical.txt'
    step_path.unlink(missing_ok=True)
    physical_path.unlink(missing_ok=True)
    if physical is not None:
        physical_path.write_bytes(physical)
    env = dict(os.environ, PD2_XINPUT_TEST_CASE=mode,
               PD2_XINPUT_STEP_PATH=str(step_path))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([str(exe)], cwd=exe.parent, env=env, startupinfo=startup)
    observed = []
    replacements = 0
    try:
        if live:
            deadline = time.monotonic() + 30
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    step = int(step_path.read_text(encoding='ascii'))
                except (FileNotFoundError, ValueError, PermissionError):
                    continue
                if not observed or observed[-1] != step:
                    observed.append(step)
                # Atomic replacement while the C reader polls must remain possible.
                temporary = physical_path.with_suffix('.tmp')
                temporary.write_bytes(physical)
                try:
                    os.replace(temporary, physical_path)
                    replacements += 1
                except PermissionError:
                    # Antivirus/filesystem filters may briefly block replacement;
                    # a persistent sharing bug still fails the success-count check.
                    pass
                time.sleep(0.002)
        actual_rc = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise AssertionError("native probe exceeded live observation window plus five-second exit grace"
                             if live else "native probe exceeded five seconds") from None
    assert actual_rc == rc, (mode, "exit", actual_rc, rc)
    if rc == 0:
        assert step_path.read_bytes() == b'-1\n', 'step handshake did not terminate'
    if live:
        assert observed == list(range(17)) + [-1], observed
        assert replacements >= 17, ('atomic replacements', replacements)
    if wanted is None:
        assert not report.exists(), "failed file write produced unexpected report"
    else:
        data = report.read_bytes()
        assert len(data) <= 4096
        actual = json.loads(data)
        assert actual == wanted, (mode, actual, wanted)
    print("PASS " + mode, flush=True)


def main():
    if os.name != "nt":
        raise SystemExit("Host Windows tests only; use tools/test_xinput_probe.cmd")
    directory = ROOT / ".state" / "xinput-native-tests" / ("run-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    print("Synthetic host-only Win32 ABI/report tests; NOT Wine or handheld validation.", flush=True)
    print("Fixtures: " + str(directory), flush=True)
    stub = build_stub(directory, "pd2_xinput_test_stub", "xinput_probe_stub.def")
    noentry = build_stub(directory, "pd2_xinput_test_noentry", "xinput_probe_noentry.def")
    cases = [
        ("changing", expected(buttons="changed", axes="changed")),
        ("static", expected()),
        ("missing", expected(devices="missing", buttons="unavailable", axes="unavailable")),
        ("error", expected(devices="error", buttons="unavailable", axes="unavailable")),
        ("disconnect", expected(buttons="changed", axes="changed",
            controls={key: ('not_seen' if key == 'a' else 'unavailable') for key in KEYS})),
        ("buttons", expected(buttons="changed")),
        ("left", expected(axes="changed")),
        ("right", expected(axes="changed")),
        ("triggers", expected(axes="changed")),
        ("threshold", expected()),
    ]
    # Different report paths require separate small wrappers around the unedited source.
    for mode, wanted in cases:
        report = directory / (mode + ".json")
        exe = build_probe(directory, mode, stub, report)
        exercise(exe, report, mode, wanted)
    for mode, dll, api in (("library_missing", directory / "does-not-exist.dll", "library_missing"),
                           ("entry_missing", noentry, "entry_missing")):
        report = directory / (mode + ".json")
        exe = build_probe(directory, mode, dll, report)
        exercise(exe, report, mode, expected(api=api, devices="error",
                 buttons="unavailable", axes="unavailable"))
    # Optional Guide entry point exported by ordinal 100, without a standard entry.
    guide_def = directory / 'guide.def'
    guide_def.write_text('EXPORTS\n    XInputGetStateEx=_StubGetState@8 @100 NONAME\n', encoding='ascii')
    guide_stub = build_stub(directory, 'pd2_xinput_guide', guide_def)
    guided = [
        ('guided_cycle', 'passed', False),
        ('guided_press', 'pressed', False),
        ('guided_held', 'not_seen', False),
        ('guided_rearm', 'passed', False),
        ('guided_disconnect', 'pressed', False),
        ('guided_reconnect', 'pressed', False),
        ('guided_slot3', 'passed', False),
        ('guided_below', 'passed', False),
        ('guided_cycle', 'passed', True),
    ]
    for number, (mode, stage, guide) in enumerate(guided):
        report = directory / f'guided-{number}.json'
        exe = build_probe(directory, f'guided-{number}', guide_stub if guide else stub,
                          report, duration=3400)
        controls = dict.fromkeys(KEYS, stage)
        if not guide:
            controls['menu'] = 'unsupported'
        if mode == 'guided_below':
            controls['l2'] = controls['r2'] = 'not_seen'
        # Digital trigger threshold is 31; legacy aggregate delta needs >4000,
        # so 31*128 intentionally leaves the original axes enum unchanged.
        wanted = expected(buttons='changed', axes='unchanged', controls=controls)
        exercise(exe, report, mode, wanted)

    fallback_def = directory / 'fallback.def'
    fallback_def.write_text('EXPORTS\n    XInputGetState=_StubGetState@8\n'
                            '    XInputGetStateEx=_StubGetStateEx@8 @100 NONAME\n', encoding='ascii')
    fallback_stub = build_stub(directory, 'pd2_xinput_fallback', fallback_def)
    for mode in ('guided_notimpl', 'guided_notsupported', 'guided_ex_disconnected'):
        report = directory / (mode + '.json')
        exe = build_probe(directory, mode, fallback_stub, report, duration=3400)
        wanted = (expected(devices='missing', buttons='unavailable', axes='unavailable')
                  if mode == 'guided_ex_disconnected' else
                  expected(buttons='changed', controls={key: ('unsupported' if key == 'menu' else 'passed')
                                                       for key in KEYS}))
        exercise(exe, report, mode, wanted)

    valid = b'PD2BUTTON1\n' + b''.join(f'{i} {i % 4} {767 if i == 16 else i}\n'.encode()
                                      for i in range(17))
    physical_expected = {key: ['not_seen', 'pressed', 'passed', 'multiple'][i % 4]
                         for i, key in enumerate(KEYS)}
    malformed = [
        b'', valid[:-1], valid + b'0 0 0\n', valid.replace(b'PD2BUTTON1', b'PD2BUTTON2'),
        valid.replace(b'0 0 0\n', b'1 0 0\n'),
        valid.replace(b'0 0 0\n', b'0 4 0\n'),
        valid.replace(b'0 0 0\n', b'0 0 768\n'),
        valid.replace(b'0 0 0\n', b'0 0 -1\n'),
        valid.replace(b'0 0 0\n', b'0 0 99999999999999999999999999\n'),
        valid.replace(b'0 0 0\n', b'0 0 0\x00\n'),
        valid + b'x' * 1024,
    ]
    for number, physical in enumerate([valid] + malformed):
        report = directory / f'physical-{number}.json'
        exe = build_probe(directory, f'physical-{number}', stub, report)
        wanted = expected(physical=physical_expected if number == 0 else None)
        exercise(exe, report, 'static', wanted, physical=physical)
    report = directory / 'physical-live.json'
    # One-second prompts tolerate scheduling jitter in this external observer;
    # the C-only guided tests above deliberately retain accelerated prompts.
    exe = build_probe(directory, 'physical-live', stub, report, duration=20400)
    exercise(exe, report, 'guided_cycle',
             expected(buttons='changed', axes='unchanged',
                      controls={key: ('unsupported' if key == 'menu' else 'passed') for key in KEYS},
                      physical=physical_expected), physical=valid, live=True)

    report = directory / "uncreated-parent" / "failure.json"
    exe = build_probe(directory, "write_failure", stub, report)
    exercise(exe, report, "write_failure", None, rc=1)
    print("38 synthetic native tests passed. Production artifacts unchanged.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
