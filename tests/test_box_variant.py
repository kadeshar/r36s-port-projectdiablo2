import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'sdcard/ports/projectdiablo2/scripts/box_variant.py'
spec = importlib.util.spec_from_file_location('box_variant', SCRIPT)
box = importlib.util.module_from_spec(spec)
spec.loader.exec_module(box)


class BoxVariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.port = self.root / 'port'
        self.source = self.port / 'compat/box86-a35'
        self.source.mkdir(parents=True)
        self.session = self.root / 'session'
        self.session.mkdir(mode=0o700)
        data = bytearray(128)
        data[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HHI', data, 16, 2, 40, 1)
        struct.pack_into('<I', data, 36, 0x05000400)
        self.data = bytes(data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.source.joinpath('box86').write_bytes(self.data)
        self.manifest = {'schema': 1, 'variant': 'a35', 'file': 'box86', 'size': len(self.data), 'sha256': self.sha,
                         'source': {'commit': box.SOURCE_COMMIT, 'archive_sha256': box.SOURCE_SHA256}}
        self.save_manifest()
        self.pin = patch.multiple(box, BOX_SIZE=len(self.data), BOX_SHA256=self.sha)
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def save_manifest(self):
        self.source.joinpath('manifest.json').write_text(json.dumps(self.manifest))

    def prepare(self, variant='a35'):
        return box.prepare_variant(self.port, self.session, variant)

    def test_stock_keeps_original_and_does_not_require_a35(self):
        self.assertIsNone(box.prepare_variant('/missing', '/missing', 'stock'))
        self.assertEqual(list(self.session.iterdir()), [])

    def test_unknown_variant_fails(self):
        for value in ('', '../a35', 'A35', 'custom', None):
            with self.assertRaises(ValueError):
                self.prepare(value)

    def test_authenticate_returns_bytes_without_staging(self):
        before = sorted(self.session.iterdir())
        self.assertEqual(box.authenticate(self.port), self.data)
        self.assertEqual(sorted(self.session.iterdir()), before)

    def test_authenticate_rejects_corrupt_binary(self):
        self.source.joinpath('box86').write_bytes(b'x' * len(self.data))
        with self.assertRaises(ValueError):
            box.authenticate(self.port)
        self.assertEqual(list(self.session.iterdir()), [])

    def test_copy_independent_and_executable(self):
        target = self.prepare()
        self.assertEqual(target, self.session / 'box86-a35')
        self.assertEqual(target.read_bytes(), self.data)
        self.assertEqual(self.source.joinpath('box86').read_bytes(), self.data)
        self.assertNotEqual(target.stat().st_ino, self.source.joinpath('box86').stat().st_ino)
        if os.name != 'nt':
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_existing_destination_never_overwritten(self):
        target = self.session / 'box86-a35'
        target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(target.read_bytes(), b'keep')

    def test_binary_hash_mismatch(self):
        self.source.joinpath('box86').write_bytes(b'x' * len(self.data))
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.session.joinpath('box86-a35').exists())

    def test_manifest_source_commit_hash_size_and_file_are_pinned(self):
        for key, value in [('commit', 'wrong'), ('archive_sha256', '0' * 64)]:
            original = self.manifest['source'][key]
            self.manifest['source'][key] = value
            self.save_manifest()
            with self.assertRaises(ValueError):
                self.prepare()
            self.manifest['source'][key] = original
        for key, value in [('sha256', '0' * 64), ('size', 12), ('file', '../box86'), ('variant', 'stock')]:
            original = self.manifest[key]
            self.manifest[key] = value
            self.save_manifest()
            with self.assertRaises(ValueError):
                self.prepare()
            self.manifest[key] = original

    def test_duplicate_manifest_keys_refused(self):
        self.source.joinpath('manifest.json').write_text('{"schema":1,"schema":1}')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_manifest_cap(self):
        self.source.joinpath('manifest.json').write_bytes(b' ' * (box.MAX_MANIFEST + 1))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_hardlinked_binary_refused(self):
        try:
            os.link(self.source / 'box86', self.root / 'alias')
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_hardlinked_manifest_refused(self):
        try:
            os.link(self.source / 'manifest.json', self.root / 'alias')
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_symlink_source_refused(self):
        original = self.source / 'box86'
        alternate = self.root / 'actual'
        alternate.write_bytes(self.data)
        original.unlink()
        try:
            original.symlink_to(alternate)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_symlink_directory_refused(self):
        alternate = self.root / 'alias'
        try:
            alternate.symlink_to(self.port, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            box.prepare_variant(alternate, self.session, 'a35')

    def test_destination_symlink_refused_without_touching_target(self):
        other = self.root / 'keep'
        other.write_bytes(b'unchanged')
        try:
            self.session.joinpath('box86-a35').symlink_to(other)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(other.read_bytes(), b'unchanged')

    def test_session_symlink_refused(self):
        alias = self.root / 'session-alias'
        try:
            alias.symlink_to(self.session, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            box.prepare_variant(self.port, alias, 'a35')

    def test_traversal_refused(self):
        with self.assertRaises(ValueError):
            box.prepare_variant(self.port / '..' / 'port', self.session, 'a35')

    def test_unpinned_build_fails_closed(self):
        with patch.multiple(box, BOX_SIZE=0, BOX_SHA256=''):
            with self.assertRaises(ValueError):
                self.prepare()

    def test_binary_size_mismatch_refused(self):
        self.source.joinpath('box86').write_bytes(self.data + b'extra')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_changed_open_descriptor_refused(self):
        from types import SimpleNamespace
        original = os.fstat
        def changed(fd):
            info = original(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mtime_ns=info.st_mtime_ns + 1,
                                   st_mode=info.st_mode, st_nlink=info.st_nlink)
        with patch.object(box.os, 'fstat', side_effect=changed):
            with self.assertRaises(ValueError):
                self.prepare()

    def test_elf_wrong_machine_and_softfloat_refused(self):
        for offset, fmt, value in [(18, '<H', 183), (36, '<I', 0x05000200), (36, '<I', 0x04000400)]:
            data = bytearray(self.data)
            struct.pack_into(fmt, data, offset, value)
            with self.assertRaises(ValueError):
                box._elf(data)

    def test_unsafe_session_permissions_refused(self):
        if os.name == 'nt':
            self.skipTest('POSIX mode check')
        self.session.chmod(0o777)
        with self.assertRaises(ValueError):
            self.prepare()

    def test_cli_has_fixed_output_and_no_paths(self):
        stream = io.StringIO()
        rc = box.main(['--port', str(self.port), '--session', str(self.session), '--variant', '../../secret'], stream)
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(stream.getvalue()), {'variant': 'unknown', 'status': 'unavailable'})
        self.assertNotIn('secret', stream.getvalue())

    def test_real_artifact_pin_and_manifest(self):
        self.pin.stop()
        folder = ROOT / 'sdcard/ports/projectdiablo2/compat/box86-a35'
        if not folder.joinpath('box86').exists():
            self.skipTest('cross-build not yet available')
        manifest = json.loads(folder.joinpath('manifest.json').read_text())
        data = folder.joinpath('box86').read_bytes()
        self.assertGreater(box.BOX_SIZE, 0)
        self.assertEqual(len(data), box.BOX_SIZE)
        self.assertEqual(hashlib.sha256(data).hexdigest(), box.BOX_SHA256)
        self.assertEqual(manifest['source']['commit'], box.SOURCE_COMMIT)
        self.assertEqual(manifest['source']['archive_sha256'], box.SOURCE_SHA256)
        box._elf(data)
        self.assertEqual(box.authenticate(ROOT / 'sdcard/ports/projectdiablo2'), data)
        self.assertEqual(list(self.session.iterdir()), [])
        target = box.prepare_variant(ROOT / 'sdcard/ports/projectdiablo2', self.session, 'a35')
        self.assertEqual(target.read_bytes(), data)


class BuildRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recipe_spec = importlib.util.spec_from_file_location('build_box86_a35', ROOT / 'tools/build_box86_a35.py')
        cls.recipe = importlib.util.module_from_spec(recipe_spec)
        recipe_spec.loader.exec_module(cls.recipe)

    def test_source_identity_matches_selector(self):
        self.assertEqual(self.recipe.COMMIT, box.SOURCE_COMMIT)
        self.assertEqual(self.recipe.SOURCE_SHA256, box.SOURCE_SHA256)
        self.assertEqual(len(self.recipe.COMMIT), 40)
        self.assertEqual(len(self.recipe.SOURCE_SHA256), 64)

    def test_no_optional_isa_requested(self):
        self.assertIn('-mtune=cortex-a35', self.recipe.FLAGS)
        self.assertNotIn('-mcpu=', self.recipe.FLAGS)
        self.assertIn('-march=armv8-a ', self.recipe.FLAGS)
        self.assertIn('-mfloat-abi=hard', self.recipe.FLAGS)
        self.assertIn('-mfpu=neon-fp-armv8', self.recipe.FLAGS)
        self.assertNotIn('+crc', self.recipe.FLAGS)
        self.assertNotIn('+crypto', self.recipe.FLAGS)


if __name__ == '__main__':
    unittest.main()
