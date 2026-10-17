#!/usr/bin/env python3
"""Offline PD2 preparation. No downloads, runtime extraction, or save imports.

--root is the project directory (containing sdcard, release-files.json and dist).
The donor is read-only; private verification state never enters the update ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import sys
import tempfile
import uuid
import zipfile

DEFAULT_SOURCE = Path(r"C:\Program Files (x86)\Diablo II")
DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DATA_REL = Path("sdcard/ports/projectdiablo2/gamedata/Diablo II")
MANIFEST_REL = Path(".state/data-manifest.json")
BASE_REQUIRED_MPQ = frozenset({"d2data.mpq", "d2exp.mpq", "d2char.mpq", "d2sfx.mpq", "d2music.mpq", "d2speech.mpq", "d2video.mpq", "d2xmusic.mpq", "d2xvideo.mpq", "d2xtalk.mpq"})
BASE_DLLS = frozenset({"bnclient.dll", "binkw32.dll", "d2client.dll", "d2cmp.dll", "d2common.dll", "d2ddraw.dll", "d2direct3d.dll", "d2game.dll", "d2gdi.dll", "d2gfx.dll", "d2glide.dll", "d2lang.dll", "d2launch.dll", "d2mcpclient.dll", "d2multi.dll", "d2net.dll", "d2sound.dll", "d2win.dll", "fog.dll", "ijl11.dll", "smackw32.dll", "storm.dll"})
# 1.14d base is monolithic: its engine lives in EXEs we deliberately exclude.
BASE_REQUIRED_DLL = frozenset({"binkw32.dll", "ijl11.dll", "smackw32.dll"})
PD2_DLLS = BASE_DLLS | frozenset({"bh.dll", "libcrypto-1_1.dll", "pd2_ext.dll", "sgd2freedisplayfix.dll", "projectdiablo.dll", "sgd2freeres.dll", "glide3x.dll", "ddraw.dll"})
PD2_MPQS = frozenset({"patch_d2.mpq", "pd2data.mpq", "pd2assets.mpq", "pd2maps.mpq", "pd2monchars.mpq", "d2gl.mpq", "d2multires.mpq", "sgd2freeres.mpq", "ver-ix86-1.mpq"})
PD2_REQUIRED_DLL = BASE_DLLS | frozenset({"projectdiablo.dll", "bh.dll", "pd2_ext.dll", "sgd2freeres.dll", "sgd2freedisplayfix.dll", "ddraw.dll", "libcrypto-1_1.dll"})
PD2_REQUIRED_MPQ = frozenset({"patch_d2.mpq", "pd2data.mpq", "pd2assets.mpq", "pd2maps.mpq", "pd2monchars.mpq", "sgd2freeres.mpq"})
PD2_REQUIRED = frozenset({"game.exe", "diablo ii.exe", "projectdiablo.cfg", "default.filter", "patch_d2.mpq"})
LICENSE_FILES = frozenset({"license", "license.txt", "license.md", "licence", "licence.txt", "licence.md", "copying", "copying.txt", "copying.md", "copyright", "copyright.txt", "third-party-notices.txt", "third_party_licenses.txt", "bh-license.md", "sgd2freeres-copying", "sgd2freeres-license.md"})
RELEASE_DIRS = frozenset({"scripts", "defaults", "runtime", "licenses"})
RELEASE_METADATA = frozenset({"DIAGNOSTICS-1.md", "README.md", "README", "README.txt", "port.json", "gameinfo.xml", "runtime-manifest.json"})
FORBIDDEN_PARTS = frozenset({"data", "gamedata", "config", "configs", ".config", "save", "saves", ".saves", "log", "logs", ".logs", "prefix", "prefixes", ".prefix", ".wine", "state", ".state", "tools", "tests", "cache", ".cache", "screenshots", "live"})
FORBIDDEN_RELEASE_FILES = frozenset({"default.key", "data-manifest.json", "account.json", "accounts.json", "credentials.json", "settings.ini"})
FORBIDDEN_RELEASE_SUFFIXES = frozenset({".key", ".d2s", ".d2x", ".ma0", ".log", ".exe"})


class PrepareError(Exception):
    """Safe, user-facing preparation failure."""


def relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise PrepareError("Invalid relative path")
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {prefix + str(n) for prefix in ("com", "lpt") for n in range(1, 10)}
    if any(part in ("", ".", "..") or part.endswith((".", " ")) or any(c in part for c in '<>"|?*') or part.split(".")[0].casefold() in reserved for part in parts) or value.startswith("/"):
        raise PrepareError("Invalid relative path")
    return PurePosixPath(value)


def reject_links(path: Path) -> None:
    # Check every ancestor too: resolve() alone would silently follow links.
    for part in (path, *path.parents):
        try:
            attributes = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 0x400:
            raise PrepareError("Symbolic links/junctions/reparse points are not allowed")


def safe_file(base: Path, relative: str) -> Path:
    rel = relative_path(relative)
    path = base.joinpath(*rel.parts)
    reject_links(path)
    if not path.is_file():
        raise PrepareError("Required file is missing")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pe_x86(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise PrepareError("Invalid x86 PE: " + path.name)
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset < 64 or offset > path.stat().st_size - 24:
            raise PrepareError("Invalid x86 PE: " + path.name)
        stream.seek(offset)
        pe = stream.read(24)
        if pe[:4] != b"PE\x00\x00" or struct.unpack_from("<H", pe, 4)[0] != 0x14C:
            raise PrepareError("Invalid x86 PE: " + path.name)


def validate_mpq(path: Path) -> None:
    # MPQ header may follow a user-data header or sit at a 512-byte boundary.
    size = path.stat().st_size
    with path.open("rb") as stream:
        magic = stream.read(4)
        if magic == b"MPQ\x1b":
            fields = stream.read(12)
            if len(fields) != 12:
                raise PrepareError("Invalid MPQ: " + path.name)
            offset = struct.unpack_from("<I", fields, 4)[0]
            if offset < 16 or offset > size - 32:
                raise PrepareError("Invalid MPQ: " + path.name)
            stream.seek(offset)
            magic = stream.read(4)
        else:
            offset = 0
        if magic != b"MPQ\x1a":
            for offset in range(512, min(size, 1024 * 1024), 512):
                stream.seek(offset)
                if stream.read(4) == b"MPQ\x1a":
                    break
            else:
                raise PrepareError("Invalid MPQ: " + path.name)
        stream.seek(offset)
        header = stream.read(32)
        if len(header) != 32:
            raise PrepareError("Invalid MPQ: " + path.name)
        header_size, archive_size, version = struct.unpack_from("<IIH", header, 4)
        if header_size < 32 or header_size > size - offset or version > 4 or (version == 0 and (archive_size < header_size or archive_size > size - offset)):
            raise PrepareError("Invalid MPQ: " + path.name)


def directory_files(folder: Path) -> dict[str, Path]:
    reject_links(folder)
    if not folder.is_dir():
        raise PrepareError("Required donor directory is missing")
    result = {}
    for path in folder.iterdir():
        reject_links(path)
        if path.is_file():
            key = path.name.casefold()
            if key in result:
                raise PrepareError("Case-insensitive donor filename collision")
            relative_path(path.name)
            result[key] = path
    return result


def collect_donor(source: Path) -> list[tuple[str, Path]]:
    base = directory_files(source)
    pd2_dirs = [p for p in source.iterdir() if p.name.casefold() == "projectd2"]
    if len(pd2_dirs) != 1:
        raise PrepareError("Required ProjectD2 directory is missing or ambiguous")
    mod = directory_files(pd2_dirs[0])
    missing = (BASE_REQUIRED_MPQ | BASE_REQUIRED_DLL | {"d2.lng", "default.key"}) - base.keys()
    missing_mod = (PD2_REQUIRED | PD2_REQUIRED_DLL | PD2_REQUIRED_MPQ) - mod.keys()
    if missing or missing_mod:
        # Never mention the key, hash it, or include its contents in diagnostics.
        public_missing = sorted((missing | missing_mod) - {"default.key"})
        raise PrepareError("Required donor files are missing" + (": " + ", ".join(public_missing) if public_missing else ""))
    selected = []
    for name, path in base.items():
        if name.endswith(".mpq") or name in BASE_DLLS or name in {"d2.lng", "default.key"} or name in LICENSE_FILES:
            selected.append((path.name, path))
    for name, path in mod.items():
        if name in PD2_REQUIRED or name in PD2_DLLS or name in PD2_MPQS or name in LICENSE_FILES:
            selected.append(("ProjectD2/" + path.name, path))
    # Licenses are allowed only in dedicated license folders, never recursively
    # through arbitrary donor trees (Live/accounts/saves remain out of scope).
    for folder in (source, pd2_dirs[0]):
        for child in folder.iterdir():
            if child.name.casefold() not in {"licenses", "license"}:
                continue
            reject_links(child)
            if not child.is_dir():
                continue
            for path in sorted(child.rglob("*")):
                reject_links(path)
                if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".html", ".rst", ""}:
                    rel = path.relative_to(folder).as_posix()
                    if folder != source:
                        rel = "ProjectD2/" + rel
                    relative_path(rel)
                    selected.append((rel, path))
    if len({relative.casefold() for relative, _ in selected}) != len(selected):
        raise PrepareError("Case-insensitive import path collision")
    for _, path in selected:
        if path.suffix.casefold() in {".exe", ".dll"}:
            validate_pe_x86(path)
        elif path.suffix.casefold() == ".mpq":
            validate_mpq(path)
    return sorted(selected, key=lambda entry: (entry[0].casefold(), entry[0]))


def temporary_directory(parent: Path, prefix: str) -> Path:
    """Create same-filesystem staging without Python 3.13+ Windows 0700 ACLs.

    Windows inherits its workspace permissions; POSIX staging stays owner-only.
    mkdir is exclusive, and no permissions of existing directories are changed.
    """
    if os.name != "nt":
        return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    for _ in range(10):
        path = parent / (prefix + uuid.uuid4().hex)
        try:
            path.mkdir(mode=0o755)
        except FileExistsError:
            continue
        return path
    raise PrepareError("Unable to allocate staging directory")


def manifest_path(root: Path) -> Path:
    path = root / MANIFEST_REL
    reject_links(path)
    return path


def verify_data(root: Path) -> dict:
    reject_links(root)
    path = manifest_path(root)
    if not path.is_file():
        raise PrepareError("Data manifest is missing; import-data is required")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PrepareError("Invalid data manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("data_path") != DATA_REL.as_posix() or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise PrepareError("Invalid data manifest")
    data = root / DATA_REL
    reject_links(data)
    seen = set()
    for relative, expected in manifest["files"].items():
        rel = relative_path(relative)
        normalized = relative.casefold()
        if normalized in seen:
            raise PrepareError("Duplicate manifest path")
        seen.add(normalized)
        if not isinstance(expected, dict) or type(expected.get("size")) is not int or expected["size"] < 0:
            raise PrepareError("Invalid data manifest entry")
        secret = rel.name.casefold() == "default.key"
        if set(expected) != ({"size"} if secret else {"size", "sha256"}):
            raise PrepareError("Invalid data manifest entry")
        file = safe_file(data, relative)
        if file.stat().st_size != expected["size"]:
            raise PrepareError("Imported data size mismatch")
        if not secret and (not isinstance(expected["sha256"], str) or len(expected["sha256"]) != 64 or sha256(file) != expected["sha256"]):
            raise PrepareError("Imported data hash mismatch")
    return manifest


def import_data(source: Path, root: Path) -> bool:
    """Return True for one import, False for a verified no-copy rerun."""
    reject_links(root)
    manifest = manifest_path(root)
    if manifest.exists():
        verify_data(root)
        return False
    data = root / DATA_REL
    reject_links(data)
    if data.exists():
        raise PrepareError("Data exists without a manifest; refusing replacement")
    # Validate the entire donor before creating staging or copying anything.
    files = collect_donor(source)
    source_resolved = source.resolve()
    data_resolved = data.resolve()
    if source_resolved == data_resolved or source_resolved in data_resolved.parents or data_resolved in source_resolved.parents:
        raise PrepareError("Donor and destination must not overlap")
    data.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(mode=0o755 if os.name == "nt" else 0o700, parents=True, exist_ok=True)
    staging = temporary_directory(data.parent, ".import-")
    temporary_manifest = None
    try:
        records = {}
        for relative, donor in files:
            destination = staging.joinpath(*relative_path(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(donor, destination)
            entry = {"size": destination.stat().st_size}
            if destination.name.casefold() != "default.key":
                entry["sha256"] = sha256(destination)
            records[relative] = entry
        content = {"version": 1, "data_path": DATA_REL.as_posix(), "files": records}
        fd, name = tempfile.mkstemp(prefix=".manifest-", suffix=".json", dir=manifest.parent)
        temporary_manifest = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(content, stream, sort_keys=True, indent=2)
            stream.write("\n")
        # Rename staging, not a second copy. Refuse a raced destination.
        if data.exists() or manifest.exists():
            raise PrepareError("Import destination appeared concurrently")
        staging.rename(data)
        temporary_manifest.rename(manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary_manifest is not None and temporary_manifest.exists():
            temporary_manifest.unlink()
    return True


def validate_release_path(value: object) -> PurePosixPath:
    path = relative_path(value)
    parts = path.parts
    # Only our own hash-pinned diagnostics/helpers, never imported game executables.
    if value in ('projectdiablo2/compat/graphics-probe/graphics-layers.exe',
                 'projectdiablo2/compat/xinput-probe/xinput-probe.exe',
                 'projectdiablo2/compat/audio-probe/audio-probe.exe',
                  'projectdiablo2/compat/fps-hotkey/fps-hotkey.exe',
                  'projectdiablo2/compat/alsa-native/alsa-native.armhf',
                  'projectdiablo2/compat/alsa-native/alsa-native.aarch64',
                  'projectdiablo2/compat/alsa-native/strace.aarch64',
                  'projectdiablo2/compat/alsa-native/strace-6.1.tar.xz'):
        return path
    if any(part.casefold() in FORBIDDEN_PARTS for part in parts) or path.name.casefold() in FORBIDDEN_RELEASE_FILES or path.suffix.casefold() in FORBIDDEN_RELEASE_SUFFIXES:
        raise PrepareError("Forbidden update path")
    if value in ("Project Diablo 2.sh", "Project Diablo 2 - Performance GDI.sh", "Project Diablo 2 - Performance OpenGL.sh",
                 "Project Diablo 2 - Test 1 GDI Baseline.sh", "Project Diablo 2 - Test 2 GDI Forward512.sh",
                 "Project Diablo 2 - Test 3 GDI CallRet RISK.sh", "Project Diablo 2 - Test 4 GDI FastFlags RISK.sh",
                 "Project Diablo 2 - Test 5 OpenGL KMS.sh", "Project Diablo 2 - Test 6 OpenGL Auto.sh",
                 "Project Diablo 2 - Diag A GDI Stock.sh", "Project Diablo 2 - Diag B GDI Measure.sh",
                 "Project Diablo 2 - Diag C SDL RGB.sh", "Project Diablo 2 - Diag D GLX RGB.sh",
                 "Project Diablo 2 - Diag E Wine RGB.sh", "Project Diablo 2 - Diag F OpenGL Measure.sh"):
        return path
    if len(parts) < 2 or parts[0] != "projectdiablo2":
        raise PrepareError("Update path is outside the static allowlist")
    if len(parts) == 2 and parts[1] in RELEASE_METADATA:
        return path
    # Only the pinned, redistributable companion; never arbitrary game DLLs.
    if value in ('projectdiablo2/compat/present-renderer/ddraw.dll',
                 'projectdiablo2/compat/present-renderer/manifest.json',
                 'projectdiablo2/compat/present-renderer/source.patch',
                 'projectdiablo2/compat/present-renderer/LICENSE.txt',
                 'projectdiablo2/compat/present-renderer/README.md',
                 'projectdiablo2/compat/graphics-probe/graphics-layers.armhf',
                 'projectdiablo2/compat/graphics-probe/manifest.json',
                 'projectdiablo2/compat/graphics-probe/LICENSE.txt',
                 'projectdiablo2/compat/graphics-probe/README.md',
                 'projectdiablo2/compat/cnc-ddraw/ddraw.dll', 'projectdiablo2/compat/cnc-ddraw/manifest.json',
                 'projectdiablo2/compat/fps-renderer/ddraw.dll',
                 'projectdiablo2/compat/fps-renderer/manifest.json',
                 'projectdiablo2/compat/fps-renderer/README.md',
                 'projectdiablo2/compat/fps-renderer/LICENSE.txt',
                 'projectdiablo2/compat/fps-renderer/source.patch',
                 'projectdiablo2/compat/alsa-legacy-armhf/libasound.so.2',
                 'projectdiablo2/compat/alsa-legacy-armhf/alsa-lib-1.2.8.tar.bz2'):
        return path
    if len(parts) >= 3 and parts[1] in RELEASE_DIRS:
        return path
    raise PrepareError("Update path is outside the static allowlist")


def release_files(root: Path) -> list[str]:
    allowlist = root / "release-files.json"
    reject_links(allowlist)
    try:
        payload = json.loads(allowlist.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PrepareError("Invalid release-files.json") from exc
    if isinstance(payload, dict) and set(payload) == {"files"}:
        payload = payload["files"]
    if not isinstance(payload, list) or not payload:
        raise PrepareError("Release list must be a nonempty list of relative files")
    seen = set()
    for value in payload:
        validate_release_path(value)
        folded = value.casefold()
        if folded in seen:
            raise PrepareError("Duplicate update path")
        seen.add(folded)
    if "Project Diablo 2.sh" not in payload:
        raise PrepareError("Release list must include Project Diablo 2.sh")
    return sorted(payload)


def validate_update_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        seen = set()
        for info in archive.infolist():
            validate_release_path(info.filename)
            normalized = info.filename.casefold()
            if normalized in seen or info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PrepareError("Invalid or duplicate update ZIP entry")
            seen.add(normalized)
        if "project diablo 2.sh" not in seen:
            raise PrepareError("Update ZIP lacks entrypoint")
        if archive.testzip() is not None:
            raise PrepareError("Corrupt update ZIP")


def build_update(root: Path) -> Path:
    reject_links(root)
    paths = release_files(root)
    ports = root / "sdcard/ports"
    # Preflight every entry before creating the archive.
    files = [(name, safe_file(ports, name)) for name in paths]
    output = root / "dist/projectdiablo2-port-update.zip"
    reject_links(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".update-", suffix=".zip", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, file in files:
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                # Content/path-derived modes make Windows/Linux output identical.
                with file.open("rb") as stream:
                    magic = stream.read(4)
                executable = relative.endswith(".sh") or (relative.startswith(('projectdiablo2/compat/alsa-native/', 'projectdiablo2/compat/graphics-probe/')) and magic == b'\x7fELF') or (relative.startswith("projectdiablo2/runtime/") and (magic == b"\x7fELF" or magic.startswith(b"#!")))
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with file.open("rb") as source_stream, archive.open(info, "w", force_zip64=True) as target_stream:
                    shutil.copyfileobj(source_stream, target_stream, 1024 * 1024)
        validate_update_zip(temporary)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Read-only Diablo II donor containing ProjectD2")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Project root containing sdcard and release-files.json")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("import-data", "verify-data", "build-update"):
        # Also accept the common command-first spelling of these options.
        sub = commands.add_parser(command)
        sub.add_argument("--source", type=Path, default=argparse.SUPPRESS)
        sub.add_argument("--root", type=Path, default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        root = args.root.absolute()
        if args.command == "import-data":
            imported = import_data(args.source.absolute(), root)
            print("Data imported once." if imported else "Existing data verified; all copying skipped.")
        elif args.command == "verify-data":
            verify_data(root)
            print("Existing data verified.")
        else:
            print("Update ZIP built: " + str(build_update(root)))
    except PrepareError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, zipfile.BadZipFile) as exc:
        # OS diagnostics can reveal the private key path; never print them.
        print("Error: filesystem/archive operation failed (" + type(exc).__name__ + ").", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
