#!/usr/bin/env python3
"""Package authenticated GPU Runtime 1; never overwrite prior release archives."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import prepare

ROOT=Path(__file__).resolve().parents[1]
PORT=ROOT/'sdcard/ports/projectdiablo2'
sys.path.insert(0,str(PORT/'scripts'))
import gles2_renderer
import box_variant
import audio_metrics


def main():
 output=ROOT/'dist/projectdiablo2-gpu-runtime-1.zip'
 names=prepare.release_files(ROOT)
 sources=[(n,prepare.safe_file(ROOT/'sdcard/ports',n)) for n in names]
 # Independent hard pins are the runtime selectors' policy, not caller manifests.
 for relative,size,digest in (
  ('compat/gles2-renderer/ddraw.dll',gles2_renderer.RENDERER_SIZE,gles2_renderer.RENDERER_SHA256),
  ('compat/audio-metrics/libasound.so.2',audio_metrics.LIBRARY_SIZE,audio_metrics.LIBRARY_SHA256)):
  data=prepare.safe_file(PORT,relative).read_bytes()
  if not size or len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Artifact authentication failed')
 # This API authenticates source provenance, ELF ABI and independent binary pin.
 box_variant.authenticate(PORT)
 prepare.reject_links(output)
 output.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
  for name,path in sources:
   data=path.read_bytes();info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.create_system=3
   executable=name.endswith('.sh') or (name.startswith(('projectdiablo2/compat/alsa-native/','projectdiablo2/compat/graphics-probe/','projectdiablo2/compat/box86-a35/')) and data.startswith(b'\x7fELF')) or (name.startswith('projectdiablo2/runtime/') and data.startswith((b'\x7fELF',b'#!')))
   info.external_attr=(0o100755 if executable else 0o100644)<<16
   archive.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
 prepare.validate_update_zip(output)
 with zipfile.ZipFile(output) as archive:
  if archive.testzip() is not None or sorted(archive.namelist())!=sorted(names):raise ValueError('Archive verification failed')
  for name,path in sources:
   if archive.read(name)!=path.read_bytes():raise ValueError('Source verification failed')
  if not (archive.getinfo('projectdiablo2/compat/box86-a35/box86').external_attr>>16)&0o111:raise ValueError('Executable mode missing')
 # Old runtime/compat stays byte-identical; new artifacts are strictly additional.
 with zipfile.ZipFile(ROOT/'dist/projectdiablo2-diagnostics-1.zip') as old,zipfile.ZipFile(output) as new:
  # The existing working tree already contains a separately rebuilt historical
  # diagnostic renderer. Do not overwrite that pre-existing work or mistake it
  # for the preserved stock renderer/runtime. Its unused bytes are authenticated
  # by the legacy selector; GPU uses the independent GL2 companion instead.
  historical_diagnostic_changes={'projectdiablo2/compat/present-renderer/'+n for n in ('ddraw.dll','manifest.json','source.patch')}
  preserved=[n for n in old.namelist() if n.startswith(('projectdiablo2/compat/','projectdiablo2/runtime/')) and n not in historical_diagnostic_changes]
  for name in preserved:
   if old.read(name)!=new.read(name):raise ValueError('Original artifact changed')
 print(json.dumps(dict(entries=len(names),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),preserved_artifacts=len(preserved))))
 print(str(output))

if __name__=='__main__':main()
