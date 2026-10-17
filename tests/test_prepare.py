"""Synthetic offline fixtures only; never read the user's installed game."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import unittest
from unittest import mock
import zipfile

SPEC = importlib.util.spec_from_file_location("pd2_prepare", Path(__file__).resolve().parents[1] / "tools" / "prepare.py")
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def tiny_pe(machine=0x14C):
    """Small genuine DOS/PE/COFF structure, not just a filename fixture."""
    dos = bytearray(64)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    coff = struct.pack("<HHIIIHH", machine, 0, 0, 0, 0, 0, 0x102)
    return bytes(dos) + b"PE\0\0" + coff


def tiny_mpq():
    return struct.pack("<4sIIHHIIII", b"MPQ\x1a", 32, 32, 0, 3, 32, 32, 0, 0)


def write_file(root, relative, content=b"fixture"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def tree_digest(root):
    return {p.relative_to(root).as_posix(): ("size:" + str(p.stat().st_size) if p.name.casefold() == "default.key" else hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob("*") if p.is_file()}


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.base = prepare.temporary_directory(Path(__file__).resolve().parent, ".fixture-")
        self.addCleanup(shutil.rmtree, self.base)
        self.source = self.base / "donor"
        self.root = self.base / "project"
        self.root.mkdir()
        for name in prepare.BASE_REQUIRED_MPQ | {"patch_d2.mpq"}:
            write_file(self.source, name, tiny_mpq())
        for name in prepare.BASE_DLLS:
            write_file(self.source, name, tiny_pe())
        write_file(self.source, "D2.LNG", b"ENG")
        write_file(self.source, "default.key", b"private-key-never-hashed")
        for name in prepare.PD2_DLLS:
            write_file(self.source, "ProjectD2/" + name, tiny_pe())
        for name in prepare.PD2_MPQS:
            write_file(self.source, "ProjectD2/" + name, tiny_mpq())
        for name in ("Game.exe", "Diablo II.exe"):
            write_file(self.source, "ProjectD2/" + name, tiny_pe())
        write_file(self.source, "ProjectD2/ProjectDiablo.cfg", b"offline-config")
        write_file(self.source, "ProjectD2/default.filter", b"default-filter")
        for name in ("BH-LICENSE.md", "SGD2FreeRes-COPYING", "SGD2FreeRes-LICENSE.md"):
            write_file(self.source, "ProjectD2/" + name, b"license fixture")
        write_file(self.source, "ProjectD2/licenses/dependency.txt", b"dependency license")
        for relative in (
            "Game.exe", "Diablo II.exe", "Unrelated.dll", "Save/hero.d2s", "accounts.json",
            "ProjectD2/PD2Launcher.exe", "ProjectD2/updater.exe", "ProjectD2/accounts.json",
            "ProjectD2/private.ini", "ProjectD2/private.json", "ProjectD2/launcher.exe.config",
            "ProjectD2/Live/secret.mpq", "ProjectD2/Save/hero.d2s", "ProjectD2/logs/private.log",
            "ProjectD2/screenshots/private.jpg", "ProjectD2/cache/account.json", "ProjectD2/unknown.dll",
            "ProjectD2/unknown.mpq",
        ):
            write_file(self.source, relative, b"must not import")

    def data(self):
        return self.root / prepare.DATA_REL

    def make_release(self):
        ports = self.root / "sdcard/ports"
        files = {
            "Project Diablo 2.sh": b"#!/bin/sh\nexit 0\n",
            "projectdiablo2/scripts/launch.sh": b"#!/bin/sh\n",
            "projectdiablo2/defaults/ProjectDiablo.cfg": b"offline=1\n",
            "projectdiablo2/defaults/default.filter": b"filter\n",
            "projectdiablo2/runtime/wine-runtime.tar.gz": b"not an archive; never extract",
            "projectdiablo2/runtime/box86": b"\x7fELFtiny runtime fixture",
            "projectdiablo2/licenses/runtime.txt": b"redistributable license",
            "projectdiablo2/README.md": b"offline port\n",
            "projectdiablo2/port.json": b"{}\n",
            "projectdiablo2/gameinfo.xml": b"<game/>\n",
            "projectdiablo2/runtime-manifest.json": b"{}\n",
        }
        for relative, content in files.items():
            write_file(ports, relative, content)
        (self.root / "release-files.json").write_text(json.dumps(list(files)), encoding="utf-8")
        return files

    def test_import_once_no_source_mutation_and_no_secret_hash(self):
        original = tree_digest(self.source)
        original_key = (self.source / "default.key").read_bytes()
        real_hash = prepare.sha256
        def guarded_hash(path):
            self.assertNotEqual(path.name.casefold(), "default.key")
            return real_hash(path)
        with mock.patch.object(prepare.shutil, "copy2", wraps=shutil.copy2) as copy, mock.patch.object(prepare, "sha256", side_effect=guarded_hash):
            self.assertTrue(prepare.import_data(self.source, self.root))
            copied_once = copy.call_count
            manifest = prepare.verify_data(self.root)
            self.assertEqual(copied_once, len(manifest["files"]))
            self.assertFalse(prepare.import_data(self.base / "nonexistent-donor", self.root))
            self.assertEqual(copy.call_count, copied_once)
        self.assertEqual(original, tree_digest(self.source))
        self.assertEqual((self.source / "default.key").read_bytes(), original_key)
        self.assertEqual(manifest["files"]["default.key"], {"size": len(b"private-key-never-hashed")})
        self.assertTrue((self.root / prepare.MANIFEST_REL).is_file())
        self.assertFalse((self.data() / "data-manifest.json").exists())
        self.assertFalse(any(p.name.startswith(".import-") for p in self.data().parent.iterdir()))

    def test_import_allowlist_excludes_base_exes_personal_data_and_saves(self):
        prepare.import_data(self.source, self.root)
        self.assertFalse((self.data() / "Game.exe").exists())
        self.assertFalse((self.data() / "Diablo II.exe").exists())
        self.assertTrue((self.data() / "ProjectD2/Game.exe").is_file())
        self.assertTrue((self.data() / "ProjectD2/BH-LICENSE.md").is_file())
        self.assertTrue((self.data() / "ProjectD2/SGD2FreeRes-COPYING").is_file())
        self.assertTrue((self.data() / "ProjectD2/licenses/dependency.txt").is_file())
        imported = tree_digest(self.data())
        for path in imported:
            self.assertNotIn("save", path.casefold())
            self.assertNotIn("live", path.casefold())
            self.assertNotIn("launcher", path.casefold())
            self.assertNotIn("updater", path.casefold())
            self.assertNotIn("private", path.casefold())
            self.assertNotIn("accounts", path.casefold())
            self.assertNotIn("unknown", path.casefold())
            self.assertNotIn("unrelated", path.casefold())
        self.assertNotIn("default.key", imported.values())

    def test_rerun_mismatch_stops_no_copy_no_repair(self):
        prepare.import_data(self.source, self.root)
        target = self.data() / "ProjectD2/ProjectDiablo.cfg"
        changed = b"X" * target.stat().st_size
        target.write_bytes(changed)
        before = tree_digest(self.source)
        with mock.patch.object(prepare.shutil, "copy2") as copy:
            with self.assertRaisesRegex(prepare.PrepareError, "hash mismatch"):
                prepare.import_data(self.source, self.root)
            copy.assert_not_called()
        self.assertEqual(target.read_bytes(), changed)
        self.assertEqual(before, tree_digest(self.source))

    def test_rerun_missing_file_stops_no_copy(self):
        prepare.import_data(self.source, self.root)
        target = self.data() / "d2data.mpq"
        target.unlink()
        with mock.patch.object(prepare.shutil, "copy2") as copy:
            with self.assertRaises(prepare.PrepareError):
                prepare.import_data(self.source, self.root)
            copy.assert_not_called()
        self.assertFalse(target.exists())

    def test_key_verification_size_only_and_no_secret_diagnostics(self):
        prepare.import_data(self.source, self.root)
        key = self.data() / "default.key"
        key.write_bytes(b"X" * key.stat().st_size)
        prepare.verify_data(self.root)  # intentional size-only privacy policy
        key.write_bytes(b"short")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(prepare.main(["verify-data", "--root", str(self.root)]), 1)
        self.assertNotIn("default.key", stderr.getvalue())
        self.assertNotIn("private-key", stderr.getvalue())

    def test_manifest_without_data_or_data_without_manifest_fail(self):
        self.data().mkdir(parents=True)
        with self.assertRaisesRegex(prepare.PrepareError, "without a manifest"):
            prepare.import_data(self.source, self.root)
        shutil.rmtree(self.data())
        prepare.import_data(self.source, self.root)
        shutil.rmtree(self.data())
        with mock.patch.object(prepare.shutil, "copy2") as copy:
            with self.assertRaises(prepare.PrepareError):
                prepare.import_data(self.source, self.root)
            copy.assert_not_called()

    def test_monolithic_114d_base_with_engine_only_under_projectd2(self):
        for name in prepare.BASE_DLLS - prepare.BASE_REQUIRED_DLL:
            (self.source / name).unlink()
        before = tree_digest(self.source)
        self.assertTrue(prepare.import_data(self.source, self.root))
        manifest = prepare.verify_data(self.root)
        self.assertEqual(before, tree_digest(self.source))
        for name in prepare.BASE_DLLS - prepare.BASE_REQUIRED_DLL:
            self.assertNotIn(name, manifest["files"])
            self.assertIn("ProjectD2/" + name, manifest["files"])
        self.assertFalse((self.data() / "Game.exe").exists())
        self.assertFalse((self.data() / "Diablo II.exe").exists())

    def test_required_files_and_x86_pe_checked_before_copy(self):
        for relative in ("d2exp.mpq", "ProjectD2/pd2data.mpq", "ProjectD2/Game.exe", "ProjectD2/projectdiablo.dll", "ProjectD2/d2common.dll", "binkw32.dll"):
            with self.subTest(missing=relative):
                path = self.source / relative
                original = path.read_bytes()
                path.unlink()
                with mock.patch.object(prepare.shutil, "copy2") as copy:
                    with self.assertRaises(prepare.PrepareError):
                        prepare.import_data(self.source, self.root)
                    copy.assert_not_called()
                path.write_bytes(original)
        for invalid in (b"not a PE", tiny_pe(0x8664), b"MZ" + b"\0" * 100):
            with self.subTest(invalid=invalid[:4]):
                (self.source / "ProjectD2/Game.exe").write_bytes(invalid)
                with mock.patch.object(prepare.shutil, "copy2") as copy:
                    with self.assertRaisesRegex(prepare.PrepareError, "x86 PE"):
                        prepare.import_data(self.source, self.root)
                    copy.assert_not_called()
        self.assertFalse(self.data().exists())

    def test_invalid_mpq_checked_before_copy(self):
        for invalid in (b"empty archive", b"MPQ\x1a", struct.pack("<4sIIHHIIII", b"MPQ\x1a", 32, 9999, 0, 3, 32, 32, 0, 0)):
            (self.source / "d2data.mpq").write_bytes(invalid)
            with mock.patch.object(prepare.shutil, "copy2") as copy:
                with self.assertRaisesRegex(prepare.PrepareError, "MPQ"):
                    prepare.import_data(self.source, self.root)
                copy.assert_not_called()

    def test_staging_copies_each_file_once_and_renames(self):
        real_copy = shutil.copy2
        def staging_copy(source, destination, *args, **kwargs):
            self.assertFalse(self.data().exists())
            self.assertTrue(any(part.startswith(".import-") for part in Path(destination).parts))
            return real_copy(source, destination, *args, **kwargs)
        with mock.patch.object(prepare.shutil, "copy2", side_effect=staging_copy) as copy:
            prepare.import_data(self.source, self.root)
            self.assertEqual(copy.call_count, len(prepare.verify_data(self.root)["files"]))

    def test_copy_failure_cleans_staging_without_modifying_source(self):
        before = tree_digest(self.source)
        with mock.patch.object(prepare.shutil, "copy2", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                prepare.import_data(self.source, self.root)
        self.assertFalse(self.data().exists())
        self.assertFalse((self.root / prepare.MANIFEST_REL).exists())
        self.assertFalse(any(p.name.startswith(".import-") for p in self.data().parent.iterdir()))
        self.assertEqual(before, tree_digest(self.source))

    def test_build_update_deterministic_and_excludes_secrets(self):
        prepare.import_data(self.source, self.root)
        release = self.make_release()
        ports = self.root / "sdcard/ports"
        for relative in ("projectdiablo2/config/personal.ini", "projectdiablo2/saves/hero.d2s", "projectdiablo2/logs/log.txt", "projectdiablo2/prefix/registry", "projectdiablo2/state/key"):
            write_file(ports, relative, b"not in update")
        write_file(self.root, "tools/private.py", b"tool")
        write_file(self.root, "tests/private.py", b"test")
        first_path = prepare.build_update(self.root)
        first = first_path.read_bytes()
        # Input list order and file timestamps do not affect output bytes.
        (self.root / "release-files.json").write_text(json.dumps({"files": list(reversed(release))}), encoding="utf-8")
        self.assertEqual(first, prepare.build_update(self.root).read_bytes())
        with zipfile.ZipFile(first_path) as archive:
            self.assertEqual(archive.namelist(), sorted(release))
            for name, value in release.items():
                self.assertEqual(archive.read(name), value)
            self.assertEqual(archive.getinfo("projectdiablo2/runtime/box86").external_attr >> 16, 0o100755)
            self.assertEqual(archive.getinfo("projectdiablo2/runtime/wine-runtime.tar.gz").external_attr >> 16, 0o100644)
            self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in archive.infolist()))
            self.assertFalse(any("gamedata" in name or "default.key" in name or "state" in name for name in archive.namelist()))
        self.assertEqual(first_path, self.root / "dist/projectdiablo2-port-update.zip")

    def test_apply_update_preserves_existing_settings_saves_and_data(self):
        release = self.make_release()
        archive = prepare.build_update(self.root)
        installed = self.base / "installed/ports"
        preserved = {
            "projectdiablo2/config/ProjectDiablo.cfg": b"user settings",
            "projectdiablo2/saves/hero.d2s": b"hero save bytes",
            "projectdiablo2/gamedata/Diablo II/d2data.mpq": tiny_mpq(),
            "projectdiablo2/gamedata/Diablo II/default.key": b"private existing key",
            "projectdiablo2/prefix/user.reg": b"persistent wine prefix",
            "projectdiablo2/logs/game.log": b"existing log",
        }
        for relative, content in preserved.items():
            write_file(installed, relative, content)
        write_file(installed, "projectdiablo2/scripts/launch.sh", b"old launcher")
        before = {name: (installed / name).read_bytes() for name in preserved}
        with zipfile.ZipFile(archive) as update:
            update.extractall(installed)
        for relative, content in before.items():
            self.assertEqual((installed / relative).read_bytes(), content)
        for relative, content in release.items():
            self.assertEqual((installed / relative).read_bytes(), content)

    def test_malicious_release_lists_rejected(self):
        self.make_release()
        malicious = (
            "../secret", "/tmp/secret", "C:/secret", "C:\\secret", "\\\\server\\share", "projectdiablo2/runtime/../../gamedata/key",
            "projectdiablo2/runtime//wine", "projectdiablo2/runtime/./wine", "projectdiablo2/runtime/../wine",
            "projectdiablo2/gamedata/Diablo II/default.key", "projectdiablo2/config/settings.ini", "projectdiablo2/saves/hero.d2s",
            "projectdiablo2/logs/log", "projectdiablo2/prefix/reg", "projectdiablo2/state/key", "projectdiablo2/.state/key",
            "projectdiablo2/runtime/default.key", "projectdiablo2/defaults/config/key", "projectdiablo2/runtime/SAVES/hero",
            "projectdiablo2/tools/prepare.py", "projectdiablo2/tests/test_prepare.py", "Other port.sh", "projectdiablo2/launcher.exe",
            "projectdiablo2/runtime/newline\n", "projectdiablo2/runtime/nul\0",
            "projectdiablo2/runtime/.. /secret", "projectdiablo2/runtime/state./key", "projectdiablo2/runtime/CON.txt", "projectdiablo2/runtime/aux", "projectdiablo2/runtime/file ",
            "projectdiablo2/runtime/.wine/user.reg", "projectdiablo2/licenses/.config/private", "projectdiablo2/runtime/hero.d2s", "projectdiablo2/runtime/accounts.json", "projectdiablo2/scripts/data-manifest.json",
        )
        for entry in malicious:
            with self.subTest(entry=entry):
                (self.root / "release-files.json").write_text(json.dumps(["Project Diablo 2.sh", entry]), encoding="utf-8")
                with self.assertRaises(prepare.PrepareError):
                    prepare.build_update(self.root)
                self.assertFalse((self.root / "dist/projectdiablo2-port-update.zip").exists())

    def test_duplicate_and_missing_release_entries_rejected(self):
        self.make_release()
        for entries in (["Project Diablo 2.sh", "Project Diablo 2.sh"], ["Project Diablo 2.sh", "projectdiablo2/runtime/Wine", "projectdiablo2/runtime/wine"], ["projectdiablo2/README.md"], ["Project Diablo 2.sh", "projectdiablo2/runtime/missing"]):
            (self.root / "release-files.json").write_text(json.dumps(entries), encoding="utf-8")
            with self.assertRaises(prepare.PrepareError):
                prepare.build_update(self.root)

    def test_zip_validator_rejects_traversal_and_symlink(self):
        archive = self.base / "malicious.zip"
        for entry in ("../data", "projectdiablo2/saves/hero", "projectdiablo2/runtime/../key"):
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("Project Diablo 2.sh", "launcher")
                handle.writestr(entry, "bad")
            with self.assertRaises(prepare.PrepareError):
                prepare.validate_update_zip(archive)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("Project Diablo 2.sh", "launcher")
            link = zipfile.ZipInfo("projectdiablo2/runtime/link")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            handle.writestr(link, "../../private")
        with self.assertRaises(prepare.PrepareError):
            prepare.validate_update_zip(archive)

    def test_link_and_windows_reparse_detection_without_symlink_privilege(self):
        for mode, attributes in ((0o120777, 0), (0o040755, 0x400)):
            fake_stat = mock.Mock(st_mode=mode, st_file_attributes=attributes)
            with mock.patch.object(Path, "lstat", return_value=fake_stat):
                with self.assertRaisesRegex(prepare.PrepareError, "links/junctions/reparse"):
                    prepare.reject_links(self.root)

    def test_symlink_source_release_and_manifest_rejected(self):
        outside = write_file(self.base, "outside", b"outside")
        link = self.base / "link-probe"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("OS does not permit creating symlinks")
        link.unlink()
        source_link = self.source / "ProjectD2/linked.dll"
        source_link.symlink_to(outside)
        with self.assertRaises(prepare.PrepareError):
            prepare.import_data(self.source, self.root)
        source_link.unlink()
        self.make_release()
        target = self.root / "sdcard/ports/projectdiablo2/README.md"
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(prepare.PrepareError):
            prepare.build_update(self.root)
        target.unlink()
        prepare.import_data(self.source, self.root)
        manifest = self.root / prepare.MANIFEST_REL
        manifest.unlink()
        manifest.symlink_to(outside)
        with self.assertRaises(prepare.PrepareError):
            prepare.verify_data(self.root)

    def test_manifest_path_traversal_rejected(self):
        prepare.import_data(self.source, self.root)
        path = self.root / prepare.MANIFEST_REL
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for bad in ("../outside", "/etc/passwd", "C:/secret", "ProjectD2/../default.key"):
            manifest["files"] = {bad: {"size": 0, "sha256": "0" * 64}}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(prepare.PrepareError):
                prepare.verify_data(self.root)

    def test_cli_supports_options_before_and_after_command(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(prepare.main(["--root", str(self.root), "--source", str(self.source), "import-data"]), 0)
            self.assertEqual(prepare.main(["verify-data", "--root", str(self.root)]), 0)
            self.assertEqual(prepare.main(["import-data", "--root", str(self.root), "--source", str(self.base / "absent")]), 0)
            self.make_release()
            self.assertEqual(prepare.main(["build-update", "--root", str(self.root)]), 0)
        self.assertIn("all copying skipped", stdout.getvalue())
        self.assertNotIn("default.key", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
