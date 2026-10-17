import argparse
import hashlib
from pathlib import Path
import zipfile
import prepare

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT/'dist/projectdiablo2-diagnostics-2.zip'))
    args = parser.parse_args()
    output = Path(args.output)
    paths=prepare.release_files(ROOT)
    sources=[(name,prepare.safe_file(ROOT/'sdcard/ports',name)) for name in paths]
    for arch in ('armhf','win32'):
        import sys
        sys.path.insert(0,str(ROOT/'sdcard/ports/projectdiablo2/scripts'))
        import graphics_artifacts
        graphics_artifacts.authenticate(ROOT/'sdcard/ports/projectdiablo2',arch)
    prepare.reject_links(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,path in sources:
            data=path.read_bytes()
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.create_system=3
            executable=name.endswith('.sh') or (name.startswith(('projectdiablo2/compat/alsa-native/','projectdiablo2/compat/graphics-probe/')) and data.startswith(b'\x7fELF')) or (name.startswith('projectdiablo2/runtime/') and data.startswith((b'\x7fELF',b'#!')))
            info.external_attr=(0o100755 if executable else 0o100644)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    prepare.validate_update_zip(output)
    with zipfile.ZipFile(output) as archive:
        if sorted(archive.namelist())!=sorted(paths):raise RuntimeError('Entry mismatch')
        for name,path in sources:
            if archive.read(name)!=path.read_bytes():raise RuntimeError('Source mismatch')
        arm=archive.getinfo('projectdiablo2/compat/graphics-probe/graphics-layers.armhf')
        if not (arm.external_attr>>16)&0o111:raise RuntimeError('Native helper is not executable')
    print('entries='+str(len(paths)))
    print('bytes='+str(output.stat().st_size))
    print('sha256='+hashlib.sha256(output.read_bytes()).hexdigest())
    print(str(output))

if __name__=='__main__':main()
