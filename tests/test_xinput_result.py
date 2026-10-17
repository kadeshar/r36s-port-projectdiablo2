"""Strict, bounded native XInput summary and privacy-safe event tests."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "xinput_result", ROOT / "sdcard/ports/projectdiablo2/scripts/xinput_result.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
READY = {"schema_version": 1, "api": "ready", "devices": "ready",
         "buttons": "changed", "axes": "unchanged"}


class XInputResultTests(unittest.TestCase):
    def setUp(self):
        if os.name == "nt":
            self.work = ROOT / "tests" / (".xinput-result-" + uuid.uuid4().hex)
            self.work.mkdir()  # Inherit workspace ACL; never Windows mkdir(0700).
            def cleanup():
                assert self.work.parent.resolve() == (ROOT / "tests").resolve()
                shutil.rmtree(self.work)
            self.addCleanup(cleanup)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="pd2-xinput-", dir="/tmp")
            self.addCleanup(temporary.cleanup)
            self.work = Path(temporary.name)
        self.path = self.work / "ProjectD2" / "pd2-xinput-result.json"
        self.path.parent.mkdir()
        self.write(READY)

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def rejected(self):
        with self.assertRaises((ValueError, OSError)):
            probe.read_summary(self.work)

    def test_valid_ready_copy(self):
        self.assertEqual(probe.read_summary(self.work), READY)
        self.assertIsNot(probe.validate(READY), READY)
        for buttons in ("changed", "unchanged"):
            for axes in ("changed", "unchanged"):
                value = dict(READY, buttons=buttons, axes=axes)
                self.assertEqual(probe.validate(value), value)

    def test_valid_absence_and_failure(self):
        for api, devices in (("ready", "missing"), ("ready", "error"),
                             ("library_missing", "error"), ("entry_missing", "error")):
            value = dict(READY, api=api, devices=devices,
                         buttons="unavailable", axes="unavailable")
            self.write(value)
            self.assertEqual(probe.read_summary(self.work), value)

    def test_strict_schema_types_and_enums(self):
        invalid = [None, [], [READY], "ready", dict(READY, unknown="SECRET"),
                   dict(READY, schema_version=True), dict(READY, schema_version=1.0),
                   dict(READY, schema_version=2)]
        for key in READY:
            invalid.append({k: v for k, v in READY.items() if k != key})
        for key in probe.FIELDS:
            for bad in (None, True, 1, [], {}, {"status": "ready"}, "SECRET", "READY"):
                invalid.append(dict(READY, **{key: bad}))
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    probe.validate(value)

    def test_consistency(self):
        invalid = []
        for api in ("library_missing", "entry_missing"):
            for devices in ("ready", "missing"):
                invalid.append(dict(READY, api=api, devices=devices))
        for devices in ("missing", "error"):
            for key in ("buttons", "axes"):
                value = dict(READY, devices=devices, buttons="unavailable", axes="unavailable")
                value[key] = "changed"
                invalid.append(value)
        for key in ("buttons", "axes"):
            invalid.append(dict(READY, **{key: "unavailable"}))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                probe.validate(value)

    def test_duplicate_json_and_invalid_encoding(self):
        samples = [b'{"schema_version":1,"schema_version":1}',
                   json.dumps(READY).replace('"api": "ready"',
                       '"api":"ready","api":"ready"').encode(),
                   b'{"x":{"a":1,"a":2}}', b'[]', b'null', b'{', b'\xff',
                   b'{"schema_version":NaN}', b'[' * 1500 + b']' * 1500]
        for sample in samples:
            with self.subTest(sample=sample[:60]):
                self.path.write_bytes(sample)
                with self.assertRaises((ValueError, RecursionError)):
                    probe.read_summary(self.work)

    def test_oversize(self):
        self.path.write_bytes(b" " * (probe.MAX_BYTES + 1))
        self.rejected()
        self.path.write_bytes(json.dumps(READY).encode().ljust(probe.MAX_BYTES, b" "))
        self.assertEqual(probe.read_summary(self.work), READY)
        # Also reject growth between the stat and the bounded read.
        real_fdopen = os.fdopen
        def grow(fd, *args):
            with self.path.open("ab") as writer:
                writer.write(b" " * 100)
            return real_fdopen(fd, *args)
        with mock.patch.object(probe.os, "fdopen", side_effect=grow):
            self.rejected()

    def test_missing_and_nonregular(self):
        self.path.unlink()
        self.rejected()
        self.path.mkdir()
        self.rejected()

    def symlink(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable to this token")

    def test_symlink_leaf(self):
        target = self.work / "target.json"
        target.write_text(json.dumps(READY), encoding="utf-8")
        self.path.unlink()
        self.symlink(target, self.path)
        self.rejected()

    def test_symlink_ancestor_and_work(self):
        alternate = self.work / "alternate"
        self.path.parent.rename(alternate)
        self.symlink(alternate, self.work / "ProjectD2", True)
        self.rejected()
        linked_work = self.work / "linked-work"
        self.symlink(alternate, linked_work, True)
        with self.assertRaises(ValueError):
            probe.read_summary(linked_work)

    def test_reparse_leaf_and_ancestor_without_link_privilege(self):
        real_lstat = os.lstat
        for target in (self.path, self.path.parent, self.work):
            def reparse(path, *args, **kwargs):
                info = real_lstat(path, *args, **kwargs)
                if Path(path) == target:
                    fake = mock.Mock()
                    fake.st_mode = info.st_mode
                    fake.st_file_attributes = 0x400
                    return fake
                return info
            with self.subTest(target=target), mock.patch.object(probe.os, "lstat", side_effect=reparse):
                self.rejected()

    def test_hardlink(self):
        try:
            os.link(self.path, self.work / "hardlink.json")
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.rejected()

    def events(self, argv=None):
        output = io.StringIO()
        rc = probe.main(["--work", str(self.work)] if argv is None else argv, stdout=output)
        lines = output.getvalue().splitlines()
        self.assertTrue(all(line.startswith("PD2_EVENT ") for line in lines))
        return rc, [json.loads(line[len("PD2_EVENT "):]) for line in lines], output.getvalue()

    def test_events_and_missing_is_success(self):
        for value in (READY, dict(READY, devices="missing", buttons="unavailable", axes="unavailable"),
                      dict(READY, api="library_missing", devices="error",
                           buttons="unavailable", axes="unavailable")):
            self.write(value)
            rc, events, text = self.events()
            self.assertEqual(rc, 0)
            self.assertEqual(events, [
                {"event": "session_probe", "phase": "launch", "check": "xinput_" + key,
                 "status": value[key]} for key in probe.FIELDS])
            self.assertNotIn(str(self.work), text)

    def test_schema2_button_results_and_closed_log_enums(self):
        value = dict(READY, schema_version=2,
                     controls={name: 'passed' for name in probe.CONTROL_NAMES},
                     physical_controls={name: 'not_seen' for name in probe.CONTROL_NAMES})
        value['controls']['menu'] = 'unsupported'
        value['physical_controls']['l3'] = 'multiple'
        self.write(value)
        self.assertEqual(probe.read_summary(self.work), value)
        fresh = probe.validate(value)
        self.assertIsNot(fresh['controls'], value['controls'])
        rc, events, text = self.events()
        self.assertEqual(rc, 0)
        self.assertEqual(len(events), 38)
        spec = importlib.util.spec_from_file_location('button_safe_log',
                    ROOT / 'sdcard/ports/projectdiablo2/scripts/safe_log.py')
        logger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(logger)
        for event in events:
            self.assertEqual(logger.validate_event(event), event)
            self.assertIsNone(logger.validate_event(dict(event, code=321)))
        self.assertNotIn('code', text)
        self.assertIsNone(logger.validate_event(dict(event='session_probe', phase='launch',
                            check='xinput_button_l3', status='unsupported')))
        self.assertIsNone(logger.validate_event(dict(event='session_probe', phase='launch',
                            check='physical_button_arbitrary', status='passed')))

    def test_schema2_rejects_unknown_missing_or_raw_button_fields(self):
        base = dict(READY, schema_version=2,
                    controls={name: 'passed' for name in probe.CONTROL_NAMES},
                    physical_controls={name: 'passed' for name in probe.CONTROL_NAMES})
        invalid = []
        for field in ('controls', 'physical_controls'):
            for bad in (None, [], 'passed', {}, dict(base[field], secret='passed'),
                        dict(base[field], a=True), dict(base[field], a=123),
                        dict(base[field], a={'code': 304}), dict(base[field], a='PRIVATE')):
                invalid.append(dict(base, **{field: bad}))
        invalid.append(dict(base, controls=dict(base['controls'], l3='unsupported')))
        invalid.append(dict(base, devices='missing', buttons='unavailable', axes='unavailable'))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                probe.validate(value)
        self.path.write_text(json.dumps(base).replace('"a": "passed"',
                            '"a":"passed","a":"pressed"', 1))
        self.rejected()

    def test_error_output_is_fixed_and_nonsecret(self):
        self.path.write_text('{"private":"SECRET-PLAYER-PATH"}', encoding="utf-8")
        for argv in (None, [], ["--arbitrary-SECRET"], ["--work", "SECRET-MISSING-PATH"]):
            rc, events, text = self.events(argv)
            self.assertEqual(rc, 1)
            self.assertEqual(events, [{"event": "runtime_error", "phase": "launch",
                                      "reason": "invalid_layout", "rc": 1}])
            self.assertNotIn("SECRET", text)
            self.assertNotIn(str(self.work), text)


if __name__ == "__main__":
    unittest.main()
