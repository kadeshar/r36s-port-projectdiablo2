"""Security regression tests for the stdlib-only, deny-by-default logger.

Run: python -m unittest discover -s tests -p test_safe_log.py -v
Fixtures remain in the project; the POSIX mode check uses native OS temporary storage.
All created artifacts are removed by unittest.
"""

import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock
from types import SimpleNamespace
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "sdcard" / "ports" / "projectdiablo2" / "scripts" / "safe_log.py"
SPEC = importlib.util.spec_from_file_location("pd2_safe_log", SCRIPT)
safe_log = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safe_log)

SECRETS = (
    "ABCD-EFGH-IJKL-MNOP", "MY_PRIVATE_CD_KEY_123456", "hunter2-password",
    "alice@example.invalid", "AccountSecretName", "TypedCharacterName",
    "/home/private-user/DiabloII/Game.exe", "C:\\Users\\SecretUser\\Game.exe",
    "HKEY_CURRENT_USER\\Software\\PrivateAccount", "0xDEADBEEFCAFEBABE",
    "API_TOKEN=private-token-value", "memory-dump-contents",
)


def wire(value):
    return "PD2_EVENT " + json.dumps(value) + "\n"


class ObservedInput(io.BytesIO):
    """Records EOF reads, proving logger doesn't merely stop at its byte cap."""
    def __init__(self, value):
        super().__init__(value)
        self.eof_seen = False
        self.largest_request = 0

    def readline(self, size=-1):
        self.largest_request = max(self.largest_request, size)
        value = super().readline(size)
        if not value:
            self.eof_seen = True
        return value


class SafeLogTests(unittest.TestCase):
    def test_dynarec_statuses_are_closed(self):
        for check, statuses in (('dynarec_bigblock', ('1', '2')),):
            for status in statuses:
                value = dict(event='session_probe', phase='launch', check=check, status=status)
                self.assertEqual(safe_log.validate_event(value), value)
                self.assertIsNone(safe_log.validate_event(dict(value, raw='secret')))
            self.assertIsNone(safe_log.validate_event(dict(value, status='arbitrary')))

    def test_retired_variant_events_are_rejected(self):
        for check, status in (('performance_profile', 'opengl'), ('renderer_variant', 'gles2'),
                              ('box_variant', 'a35'), ('tuning_profile', 'gl-kms'),
                              ('client_drm_access', 'ready')):
            self.assertIsNone(safe_log.validate_event(dict(
                event='session_probe', phase='launch', check=check, status=status)))

    def test_controller_mapper_closed_schema(self):
        for status in ('ready', 'missing', 'denied', 'invalid', 'fallback'):
            value = dict(event='session_probe', phase='launch', check='controller_mapper', status=status)
            self.assertEqual(safe_log.validate_event(value), value)
            self.assertIsNone(safe_log.validate_event(dict(value, raw_buttons=123)))
            self.assertIsNone(safe_log.validate_event(dict(value, count=1)))
        value = dict(event='session_probe', phase='launch', check='mapper_layout', status='standard')
        self.assertEqual(safe_log.validate_event(value), value)
        self.assertIsNone(safe_log.validate_event(dict(value, status='arbitrary pad name')))
        self.assertIsNone(safe_log.validate_event(dict(value, phase='game')))

    def setUp(self):
        if os.name == "nt":
            # Python 3.13+ TemporaryDirectory's special 0700 DACL blocks the
            # restricted Windows test token. Ordinary mkdir inherits workspace
            # access instead; POSIX still uses a private TemporaryDirectory.
            self.root = PROJECT / ("safe-log-test-" + uuid.uuid4().hex)
            self.root.mkdir()
            self.addCleanup(shutil.rmtree, self.root)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="safe-log-test-", dir=PROJECT)
            self.addCleanup(self.temporary.cleanup)
            self.root = Path(self.temporary.name)
        self.logs = self.root / "logs"

    def stream(self, text, session="test", maxbytes=safe_log.MAX_BYTES, retain=10):
        source = ObservedInput(text.encode("utf-8") if isinstance(text, str) else text)
        rc = safe_log.stream_log(self.logs, session, source, maxbytes, retain)
        self.assertTrue(source.eof_seen, "stdin was not drained to EOF")
        return rc, source

    def rows(self, session="test"):
        path = self.logs / ("pd2-session-" + session + ".jsonl")
        return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]

    def assertNoSecrets(self, contents):
        if isinstance(contents, bytes):
            contents = contents.decode("utf-8", "replace")
        for secret in SECRETS:
            self.assertNotIn(secret, contents)

    def symlink(self, target, link, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest("OS does not permit symlink creation: %s" % type(error).__name__)

    def zip_contents(self):
        with zipfile.ZipFile(self.logs / "diagnostic-export.zip") as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_structured_events_and_technical_metrics(self):
        events = [
            {"event": "phase", "phase": "preflight", "profile": "gdi", "port_version": "1.2.3", "runtime_version": "v8.0-rc1", "machine": "armv7l"},
            {"event": "runtime_error", "phase": "runtime", "reason": "missing_library", "library": "libGL.so.1"},
            {"event": "metrics", "available_ram_mb": 512, "disk_mb": 8192, "temperature_mc": 42000, "duration_ms": 200},
            {"event": "runtime_exit", "phase": "shutdown", "rc": 0, "duration_ms": 456},
        ]
        rc, _source = self.stream("".join(wire(event) for event in events))
        self.assertEqual(rc, 0)
        rows = self.rows()
        self.assertEqual(rows[:-1], events)
        self.assertEqual(rows[-1]["event"], "summary")
        self.assertEqual(rows[-1]["counts"]["input_lines"], len(events))
        self.assertEqual(rows[-1]["counts"]["written_events"], len(events))
        self.assertEqual(set(rows[-1]["counts"]), safe_log.COUNTS)

    def test_secrets_raw_lines_registry_env_memory_and_input_are_omitted(self):
        raw = "\n".join(SECRETS) + "\n"
        raw += "username: SecretUser\npassword: hunter2-password\nCDKEY=ABCD-EFGH-IJKL-MNOP\n"
        raw += "export WINEPREFIX=/home/private-user\nREGISTRY DUMP\nTyped name: TypedCharacterName\n"
        raw += "wine: Unhandled page fault at 0xDEADBEEFCAFEBABE memory-dump-contents\n"
        self.assertEqual(self.stream(raw)[0], 0)
        data = (self.logs / "pd2-session-test.jsonl").read_bytes()
        self.assertNoSecrets(data)
        self.assertEqual(len(self.rows()), 1)
        self.assertGreater(self.rows()[0]["counts"]["omitted_lines"], 10)

    def test_unknown_fields_and_dynamic_values_reject_entire_event(self):
        bad = [
            {"event": "phase", "phase": "preflight", "message": SECRETS[0]},
            {"event": "phase", "phase": "TypedCharacterName"},
            {"event": "phase", "phase": "runtime", "profile": "my-private-profile"},
            {"event": "phase", "phase": "runtime", "machine": "SecretUser"},
            {"event": "phase", "phase": "runtime", "port_version": "/home/private-user"},
            {"event": "phase", "phase": "runtime", "runtime_version": "AccountSecretName"},
            {"event": "runtime_error", "reason": "hunter2-password"},
            {"event": "runtime_error", "reason": "fault", "library": "libGL.so.1"},
            {"event": "runtime_error", "reason": "missing_library", "library": "/home/private-user/libGL.so.1"},
            {"event": "runtime_error", "reason": "missing_library", "library": "libGL.so.1 private-key"},
            {"event": "runtime_exit", "rc": "0", "phase": "shutdown"},
            {"event": "runtime_exit", "rc": True},
            {"event": "runtime_exit", "rc": 999999999},
            {"event": "runtime_exit"},
            {"event": "metrics", "available_ram_mb": -1},
            {"event": "metrics", "disk_mb": 1.5},
            {"event": "metrics", "duration_ms": True},
            {"event": "metrics", "temperature_mc": 999999},
            {"event": "metrics"},
            {"event": "summary", "counts": {"omitted_lines": 1}},
            {"event": "player_name", "name": "TypedCharacterName"},
            {"event": ["phase"]},
            {"event": "phase", "phase": ["runtime"]},
            [], "ABCD-EFGH-IJKL-MNOP", None,
        ]
        self.assertEqual(self.stream("".join(wire(value) for value in bad))[0], 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["counts"]["omitted_lines"], len(bad))
        self.assertNoSecrets((self.logs / "pd2-session-test.jsonl").read_bytes())

    def test_json_duplicates_nan_malformed_and_deep_objects_are_omitted(self):
        lines = [
            'PD2_EVENT {"event":"phase","phase":"runtime","phase":"game"}\n',
            'PD2_EVENT {"event":"metrics","duration_ms":NaN}\n',
            'PD2_EVENT {"event":"metrics","duration_ms":Infinity}\n',
            'PD2_EVENT {not json}\n',
            'PD2_EVENT ' + '[' * 1100 + '0' + ']' * 1100 + '\n',
            '\x00PD2_EVENT {"event":"phase","phase":"runtime"}\n',
        ]
        self.assertEqual(self.stream("".join(lines))[0], 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["counts"]["omitted_lines"], len(lines))

    def test_generic_errors_only_capture_anchored_safe_technical_fields(self):
        text = "/home/private-user/DiabloII/Game.exe: error while loading shared libraries: libGL.so.1: cannot open shared object file: No such file or directory\n"
        text += '0024:err:module:import_dll Library ddraw.dll (which is needed by "C:\\Users\\SecretUser\\Game.exe") not found\n'
        text += "Segmentation fault (core dumped)\nBus error\nIllegal instruction\nProcess exited with code 7\n"
        text += "error while loading shared libraries: /home/private-user/libGL.so: cannot open shared object file: No such file or directory\n"
        text += "Segmentation fault memory-dump-contents at 0xDEADBEEFCAFEBABE\n"
        text += "Process exited with code 7 AccountSecretName\nexit 99999\n"
        self.assertEqual(self.stream(text)[0], 0)
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0], {"event": "runtime_error", "reason": "missing_library", "library": "libGL.so.1"})
        self.assertEqual(rows[1]["library"], "ddraw.dll")
        self.assertEqual(rows[-2], {"event": "runtime_exit", "rc": 7})
        self.assertEqual(rows[-1]["counts"]["omitted_lines"], 4)
        self.assertNoSecrets((self.logs / "pd2-session-test.jsonl").read_bytes())

    def test_library_names_are_fullmatch_only(self):
        for name in ("libstdc++.so.6", "foo bar.dll", "../ddraw.dll", "foo.dll\nsecret", "libGL.so.x", "libGL.so.1/private", ".secret.dll", "foo.so\x00"):
            with self.subTest(name=name):
                self.assertIsNone(safe_log.validate_event({"event": "runtime_error", "reason": "missing_library", "library": name}))
        for name in ("libGL.so", "libc.so.6", "libfoo-bar.so.1.2", "DDRAW.dll", "wine_d3d.dll"):
            self.assertIsNotNone(safe_log.validate_event({"event": "runtime_error", "reason": "missing_library", "library": name}))

    def test_flood_obeys_byte_limit_and_drains_to_eof(self):
        count = 20000
        rc, source = self.stream(wire({"event": "phase", "phase": "game"}) * count + SECRETS[0] + "\n", maxbytes=1024)
        self.assertEqual(rc, 0)
        self.assertEqual(source.tell(), len(source.getvalue()))
        path = self.logs / "pd2-session-test.jsonl"
        self.assertLessEqual(path.stat().st_size, 1024)
        summary = self.rows()[-1]
        self.assertEqual(summary["counts"]["input_lines"], count + 1)
        self.assertEqual(summary["counts"]["accepted_events"], count)
        self.assertGreater(summary["counts"]["limited_events"], 0)
        self.assertEqual(summary["counts"]["omitted_lines"], 1)
        self.assertNoSecrets(path.read_bytes())

    def test_oversized_lines_are_drained_using_bounded_reads(self):
        text = (SECRETS[0] + "X" * 500000 + "\n").encode() + b"\xff\xfe\n" + wire({"event": "runtime_exit", "rc": 0}).encode()
        rc, source = self.stream(text)
        self.assertEqual(rc, 0)
        self.assertLessEqual(source.largest_request, safe_log.MAX_LINE + 1)
        self.assertEqual(self.rows()[0], {"event": "runtime_exit", "rc": 0})
        self.assertEqual(self.rows()[-1]["counts"]["input_lines"], 3)
        self.assertEqual(self.rows()[-1]["counts"]["oversized_lines"], 2)
        self.assertNoSecrets((self.logs / "pd2-session-test.jsonl").read_bytes())

    def test_exact_minimum_budget_still_contains_summary(self):
        rc, _source = self.stream(wire({"event": "phase", "phase": "runtime"}), maxbytes=512)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertLessEqual((self.logs / "pd2-session-test.jsonl").stat().st_size, 512)

    def test_invalid_limits_sessions_and_traversal_fail_but_drain(self):
        for index, session in enumerate(("../escape", "../../escape", "a/b", "a\\b", "", "/tmp/escape", "..", "a" * 65)):
            with self.subTest(session=session):
                self.assertEqual(self.stream(SECRETS[0] + "\n", session=session)[0], 1)
        for maxbytes in (0, 511, safe_log.MAX_BYTES + 1, True):
            self.assertEqual(self.stream("secret\n", session="limit", maxbytes=maxbytes)[0], 1)
        for retain in (0, 11, True):
            self.assertEqual(self.stream("secret\n", session="retain", retain=retain)[0], 1)
        self.assertFalse((self.root / "escape").exists())

    def test_existing_session_is_never_overwritten(self):
        self.logs.mkdir()
        path = self.logs / "pd2-session-test.jsonl"
        path.write_text("existing content", encoding="utf-8")
        self.assertEqual(self.stream(SECRETS[0] + "\n")[0], 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "existing content")

    def test_open_read_only_failure_is_mocked_and_still_drains(self):
        with mock.patch.object(safe_log.os, "open", side_effect=PermissionError("READ ONLY " + SECRETS[0])):
            self.assertEqual(self.stream(wire({"event": "phase", "phase": "runtime"}) * 30)[0], 1)

    def test_write_failure_is_mocked_and_still_drains(self):
        writer = mock.MagicMock()
        writer.write.side_effect = OSError("disk failure " + SECRETS[0])
        self.logs.mkdir()
        # Mock the file descriptor acquisition as well, avoiding leaked descriptors.
        with mock.patch.object(safe_log, "_open", return_value=999), mock.patch.object(safe_log.os, "fdopen", return_value=writer):
            self.assertEqual(self.stream(wire({"event": "phase", "phase": "runtime"}) * 100)[0], 1)
        writer.close.assert_called()
        self.assertEqual(writer.write.call_count, 1)

    def test_short_write_is_failure_and_still_drains(self):
        writer = mock.MagicMock()
        writer.write.return_value = 1
        self.logs.mkdir()
        with mock.patch.object(safe_log, "_open", return_value=999), mock.patch.object(safe_log.os, "fdopen", return_value=writer):
            self.assertEqual(self.stream(wire({"event": "phase", "phase": "runtime"}) * 30)[0], 1)

    def test_cli_failures_never_dump_raw_exception_or_arguments(self):
        source = ObservedInput((SECRETS[0] + "\n").encode())
        stderr = io.StringIO()
        with mock.patch.object(safe_log.os, "open", side_effect=PermissionError("sensitive " + SECRETS[0])):
            rc = safe_log.main(["stream", "--dir", str(self.logs), "--session", "cli"], source, stderr)
        self.assertEqual(rc, 1)
        self.assertTrue(source.eof_seen)
        self.assertEqual(stderr.getvalue(), "safe_log: operation failed\n")
        source = ObservedInput(b"secret\n")
        stderr = io.StringIO()
        rc = safe_log.main(["stream", "--dir", str(self.logs), "--session", "cli", "--password", SECRETS[0]], source, stderr)
        self.assertEqual(rc, 2)
        self.assertTrue(source.eof_seen)
        self.assertEqual(stderr.getvalue(), "safe_log: invalid arguments\n")

    def test_retention_keeps_at_most_ten_only_own_session_names(self):
        self.logs.mkdir()
        unrelated = ("notes.jsonl", "saves", "config.json", "gamedata.bin", "wineprefix", "private.key", "pd2-session-evil.extra.jsonl", "pd2-session-..jsonl")
        for name in unrelated:
            (self.logs / name).write_text(SECRETS[0], encoding="utf-8")
        for index in range(15):
            self.assertEqual(self.stream(wire({"event": "phase", "phase": "runtime"}), session="s%02d" % index)[0], 0)
        own = [path for path in self.logs.iterdir() if safe_log.LOG_RE.fullmatch(path.name)]
        self.assertEqual(len(own), 10)
        for name in unrelated:
            self.assertEqual((self.logs / name).read_text(encoding="utf-8"), SECRETS[0])
        self.assertTrue((self.logs / "pd2-session-s14.jsonl").exists())

    def test_retain_custom_count(self):
        for index in range(5):
            self.assertEqual(self.stream("unknown\n", session="s%d" % index, retain=2)[0], 0)
        self.assertEqual(len(list(self.logs.iterdir())), 2)

    def test_private_permissions_and_umask_restoration(self):
        if os.name == "nt":
            self.skipTest("Windows chmod does not implement POSIX permission bits")
        # WSL /mnt/c (NTFS without metadata) cannot represent Unix modes, just
        # like exFAT. Test POSIX privacy on the native Linux filesystem instead.
        with tempfile.TemporaryDirectory(prefix="pd2-posix-mode-test-") as native:
            original_logs = self.logs
            self.logs = Path(native) / "logs"
            previous = os.umask(0o022)
            try:
                self.assertEqual(self.stream("unknown\n")[0], 0)
                restored = os.umask(0o022)
                self.assertEqual(restored, 0o022)
                self.assertEqual(stat.S_IMODE(self.logs.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE((self.logs / "pd2-session-test.jsonl").stat().st_mode), 0o600)
                self.assertEqual(safe_log.export_logs(self.logs), 0)
                self.assertEqual(stat.S_IMODE((self.logs / "diagnostic-export.zip").stat().st_mode), 0o600)
            finally:
                os.umask(previous)
                self.logs = original_logs

    def test_symlink_log_file_refused_and_target_unchanged(self):
        self.logs.mkdir()
        target = self.root / "target"
        target.write_text(SECRETS[0], encoding="utf-8")
        self.symlink(target, self.logs / "pd2-session-test.jsonl")
        self.assertEqual(self.stream("unknown\n")[0], 1)
        self.assertEqual(target.read_text(encoding="utf-8"), SECRETS[0])

    def test_symlink_directory_and_ancestor_refused(self):
        target = self.root / "target"
        target.mkdir()
        self.symlink(target, self.logs, directory=True)
        self.assertEqual(self.stream("unknown\n")[0], 1)
        source = ObservedInput(b"unknown\n")
        self.assertEqual(safe_log.stream_log(self.logs / "nested", "test", source), 1)
        self.assertTrue(source.eof_seen)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(safe_log.export_logs(self.logs), 1)

    def test_export_reparses_malicious_jsonl_and_only_safe_projection(self):
        self.logs.mkdir()
        good = {"event": "phase", "phase": "runtime", "profile": "opengl", "runtime_version": "8.0", "machine": "armv7l"}
        rows = [json.dumps(good), json.dumps({"event": "phase", "phase": "game", "message": SECRETS[0]}), json.dumps({"event": "runtime_error", "reason": "TypedCharacterName"}), json.dumps({"event": "phase", "phase": SECRETS[4]})]
        rows.extend(SECRETS)
        # A hostile session filename is not disclosed by archive entry names.
        (self.logs / "pd2-session-AccountSecretName.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        for name in ("private.jsonl", "saves", "config", "gamedata", "wineprefix", "private.key"):
            (self.logs / name).write_text(SECRETS[0], encoding="utf-8")
        manifest = self.root / "runtime-manifest.json"
        manifest.write_text(json.dumps({"port_version": "1.4.0", "runtime_version": "8.0", "profile": "gdi", "machine": "armv7l", "donor_paths": [SECRETS[6], SECRETS[7]], "account": SECRETS[4], "credentials": SECRETS[2], "environment": SECRETS[10], "files": {"Game.exe": SECRETS[7]}, "key": SECRETS[0]}), encoding="utf-8")
        self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 0)
        contents = self.zip_contents()
        self.assertEqual(set(contents), {"logs/session-001.jsonl", "runtime-manifest.json"})
        self.assertEqual([json.loads(row) for row in contents["logs/session-001.jsonl"].splitlines()], [good])
        self.assertEqual(json.loads(contents["runtime-manifest.json"]), {"port_version": "1.4.0", "runtime_version": "8.0", "profile": "gdi", "machine": "armv7l"})
        for name, data in contents.items():
            self.assertNoSecrets(name)
            self.assertNoSecrets(data)

    def test_export_invalid_manifest_allowed_fields_are_omitted(self):
        self.logs.mkdir()
        manifest = self.root / "runtime-manifest.json"
        manifest.write_text(json.dumps({"port_version": SECRETS[0], "runtime_version": SECRETS[7], "machine": SECRETS[4], "profile": SECRETS[5], "message": SECRETS[2]}), encoding="utf-8")
        self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 0)
        self.assertEqual(json.loads(self.zip_contents()["runtime-manifest.json"]), {})

    def test_export_strict_summary_schema_and_duplicate_fields(self):
        self.logs.mkdir()
        counts = dict.fromkeys(safe_log.COUNTS, 0)
        valid = {"event": "summary", "counts": counts}
        bad = {"event": "summary", "counts": dict(counts, typed_name=SECRETS[5])}
        bool_bad = {"event": "summary", "counts": dict(counts, input_lines=True)}
        duplicate = '{"event":"phase","phase":"runtime","phase":"game"}'
        text = "\n".join([json.dumps(valid), json.dumps(bad), json.dumps(bool_bad), duplicate]) + "\n"
        (self.logs / "pd2-session-malicious.jsonl").write_text(text, encoding="utf-8")
        self.assertEqual(safe_log.export_logs(self.logs), 0)
        contents = self.zip_contents()
        self.assertEqual(json.loads(contents["logs/session-001.jsonl"]), valid)

    def test_export_bounds_files_count_and_size(self):
        self.logs.mkdir()
        for index in range(12):
            path = self.logs / ("pd2-session-%d.jsonl" % index)
            path.write_text(json.dumps({"event": "runtime_exit", "rc": index}) + "\n", encoding="ascii")
        self.assertEqual(safe_log.export_logs(self.logs), 0)
        self.assertEqual(len(self.zip_contents()), 10)
        huge = self.logs / "pd2-session-huge.jsonl"
        huge.write_bytes(b"X" * (safe_log.MAX_BYTES + 1))
        for path in self.logs.iterdir():
            if safe_log.LOG_RE.fullmatch(path.name) and path != huge:
                path.unlink()
        self.assertEqual(safe_log.export_logs(self.logs), 0)
        self.assertEqual(self.zip_contents(), {})

    def test_export_never_follows_symlink_logs_or_manifest(self):
        self.logs.mkdir()
        target = self.root / "outside.jsonl"
        target.write_text(json.dumps({"event": "phase", "phase": "runtime"}) + "\n" + SECRETS[0], encoding="utf-8")
        self.symlink(target, self.logs / "pd2-session-external.jsonl")
        self.assertEqual(safe_log.export_logs(self.logs), 0)
        self.assertEqual(self.zip_contents(), {})
        manifest = self.root / "runtime-manifest.json"
        self.symlink(target, manifest)
        self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 1)

    def test_export_refuses_symlink_zip_and_output_directory(self):
        self.logs.mkdir()
        target = self.root / "target"
        target.write_text(SECRETS[0], encoding="utf-8")
        self.symlink(target, self.logs / "diagnostic-export.zip")
        self.assertEqual(safe_log.export_logs(self.logs), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), SECRETS[0])
        output_target = self.root / "target-dir"
        output_target.mkdir()
        output = self.root / "output"
        self.symlink(output_target, output, directory=True)
        self.assertEqual(safe_log.export_logs(self.logs, output_directory=output), 1)
        self.assertEqual(list(output_target.iterdir()), [])

    def test_manifest_never_read_from_forbidden_components_or_key(self):
        self.logs.mkdir()
        for name in ("saves", "config", "gamedata", "wineprefix"):
            directory = self.root / name
            directory.mkdir()
            manifest = directory / "runtime-manifest.json"
            manifest.write_text('{"port_version":"1.0"}', encoding="ascii")
            self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 1)
        manifest = self.root / "runtime.key"
        manifest.write_text(SECRETS[0], encoding="utf-8")
        self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 1)

    def test_export_manifest_size_and_io_failure_are_safe(self):
        self.logs.mkdir()
        manifest = self.root / "runtime-manifest.json"
        manifest.write_bytes(b"X" * 65537)
        self.assertEqual(safe_log.export_logs(self.logs, manifest=manifest), 1)
        with mock.patch.object(safe_log.os, "open", side_effect=OSError(SECRETS[0])):
            self.assertEqual(safe_log.export_logs(self.logs), 1)
        self.assertFalse((self.logs / "diagnostic-export.zip").exists())
        self.assertEqual(list(self.logs.iterdir()), [])

    def test_mocked_symlink_directory_and_file_are_refused_without_open(self):
        self.logs.mkdir()
        original = safe_log.os.lstat
        for unsafe in (self.logs, self.logs / "pd2-session-test.jsonl"):
            def lstat(path, *args, **kwargs):
                if Path(path) == unsafe:
                    return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
                return original(path, *args, **kwargs)
            with self.subTest(path=unsafe.name), mock.patch.object(safe_log.os, "lstat", side_effect=lstat), mock.patch.object(safe_log.os, "open") as opener:
                self.assertEqual(self.stream(wire({"event": "phase", "phase": "runtime"}) * 10)[0], 1)
                opener.assert_not_called()

    def test_mocked_windows_reparse_directory_is_refused(self):
        self.logs.mkdir()
        original = safe_log.os.lstat
        def lstat(path, *args, **kwargs):
            if Path(path) == self.logs:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_file_attributes=0x400)
            return original(path, *args, **kwargs)
        with mock.patch.object(safe_log.os, "lstat", side_effect=lstat), mock.patch.object(safe_log.os, "open") as opener:
            self.assertEqual(self.stream("unknown\n")[0], 1)
            self.assertEqual(safe_log.export_logs(self.logs), 1)
            opener.assert_not_called()

    def test_mocked_hardlink_log_is_neither_opened_exported_nor_deleted(self):
        self.logs.mkdir()
        suspicious = self.logs / "pd2-session-hardlink.jsonl"
        suspicious.write_text(SECRETS[0], encoding="utf-8")
        original = safe_log.os.lstat
        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if Path(path) == suspicious:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0, st_nlink=2)
            return info
        with mock.patch.object(safe_log.os, "lstat", side_effect=lstat):
            self.assertEqual(self.stream("unknown\n", session="hardlink")[0], 1)
            self.assertEqual(self.stream("unknown\n", retain=1)[0], 0)
            self.assertEqual(safe_log.export_logs(self.logs), 0)
        self.assertEqual(suspicious.read_text(encoding="utf-8"), SECRETS[0])
        for data in self.zip_contents().values():
            self.assertNoSecrets(data)

    def test_mocked_symlink_manifest_and_destination_refused(self):
        self.logs.mkdir()
        manifest = self.root / "runtime-manifest.json"
        destination = self.logs / "diagnostic-export.zip"
        original = safe_log.os.lstat
        for unsafe, argument in ((manifest, {"manifest": manifest}), (destination, {})):
            def lstat(path, *args, **kwargs):
                if Path(path) == unsafe:
                    return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
                return original(path, *args, **kwargs)
            with self.subTest(path=unsafe.name), mock.patch.object(safe_log.os, "lstat", side_effect=lstat), mock.patch.object(safe_log.os, "open") as opener:
                self.assertEqual(safe_log.export_logs(self.logs, **argument), 1)
                opener.assert_not_called()

    def test_version_fields_cannot_carry_arbitrary_alphabetic_names(self):
        for version in ("1.TypedName", "1-Password", "1.AccountSecretName", "1.2.SecretUser", "1+privatekey", "v1.foo"):
            with self.subTest(version=version):
                self.assertIsNone(safe_log.validate_event({"event": "phase", "phase": "runtime", "port_version": version}))
        for version in ("1", "1.2.3", "v8.0-rc1", "0.3.6+git123", "2.0-beta2"):
            self.assertIsNotNone(safe_log.validate_event({"event": "phase", "phase": "runtime", "runtime_version": version}))

    def test_default_two_mib_budget_drains_large_stream(self):
        count = 70000
        rc, source = self.stream(wire({"event": "phase", "phase": "game"}) * count)
        self.assertEqual(rc, 0)
        self.assertEqual(source.tell(), len(source.getvalue()))
        self.assertLessEqual((self.logs / "pd2-session-test.jsonl").stat().st_size, 2 * 1024 * 1024)
        summary = self.rows()[-1]
        self.assertEqual(summary["counts"]["accepted_events"], count)
        self.assertGreater(summary["counts"]["limited_events"], 0)

    def test_empty_input_logs_only_zero_summary(self):
        self.assertEqual(self.stream(b"")[0], 0)
        self.assertEqual(self.rows(), [{"event": "summary", "counts": dict.fromkeys(safe_log.COUNTS, 0)}])

    def test_real_cli_stream_then_export_without_raw_stdout_stderr(self):
        raw = ("\n".join(SECRETS) + "\n" + wire({"event": "phase", "phase": "runtime"})).encode()
        input_path = self.root / "stdin.txt"
        stdout_path = self.root / "stdout.txt"
        stderr_path = self.root / "stderr.txt"
        input_path.write_bytes(raw)
        # File-backed handles deliberately avoid named-pipe restrictions in DSH.
        with input_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "stream", "--dir", str(self.logs), "--session", "cli", "--maxbytes", "1024"], stdin=stdin, stdout=stdout, stderr=stderr, timeout=15, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(stdout_path.read_bytes(), b"")
        self.assertEqual(stderr_path.read_bytes(), b"")
        self.assertNoSecrets((self.logs / "pd2-session-cli.jsonl").read_bytes())
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "export", "--dir", str(self.logs)], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=15, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(stdout_path.read_bytes(), b"")
        self.assertEqual(stderr_path.read_bytes(), b"")
        contents = self.zip_contents()
        self.assertEqual(set(contents), {"logs/session-001.jsonl"})
        self.assertNoSecrets(contents["logs/session-001.jsonl"])


if __name__ == "__main__":
    unittest.main()
