#!/usr/bin/env python3
"""Audit current data-free update without copying/extracting any asset."""
import hashlib,json,pathlib,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
VERSION='0.1.18'
PINNED={'wine-8.0-x86.tar.xz':(31185272,'d77d023bd9046547afccae5860dc6089b9d5cd9699f656b83e2f573bbf3fae6d'),'weston_pkg_0.2.squashfs':(55398400,'0bccaeebc11296bb1fe4278c9677cb82965c5a04bcd63745fa09d78228bc1a93'),'vc_redist.x86.exe':(13889072,'38c9437e6e9ef1db2671b3f0c879febec08521bd2c23231199f626b69ae1c65e'),'box86':(27311020,'5870bf87c45051b1eb98f461a81de88f7c3c88e399e9810c093179d91a2fd013')}
p=ROOT/'dist/projectdiablo2-port-update.zip';allow=json.loads((ROOT/'release-files.json').read_text())
with zipfile.ZipFile(p) as z:
 assert sorted(z.namelist())==sorted(allow)
 expected_launchers={'Project Diablo 2.sh','Project Diablo 2 - Performance GDI.sh','Project Diablo 2 - Performance OpenGL.sh'}
 assert {n for n in z.namelist() if '/' not in n and n.endswith('.sh')}==expected_launchers
 assert {f.name for f in (ROOT/'sdcard/ports').glob('*.sh')}==expected_launchers
 assert z.testzip() is None
 assert not any(any(x in ('gamedata','runtime','config','saves','logs','wineprefix','__pycache__') for x in n.split('/')) for n in z.namelist())
 assert '"port_version":"'+VERSION+'"' in z.read('Project Diablo 2.sh').decode()
 manifest=json.loads(z.read('projectdiablo2/runtime-manifest.json'))
 assert manifest['port_version']==VERSION
 assert {a['file']:(a['size'],a['sha256']) for a in manifest['artifacts']}==PINNED
 companion=json.loads(z.read('projectdiablo2/compat/cnc-ddraw/manifest.json'))
 dll=z.read('projectdiablo2/compat/cnc-ddraw/ddraw.dll')
 assert companion['version']=='7.1.0.0'
 assert len(dll)==companion['size']==411648
 assert hashlib.sha256(dll).hexdigest()==companion['sha256']=='85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9'
 assert sorted(n for n in z.namelist() if n.lower().endswith('.dll'))==[
  'projectdiablo2/compat/cnc-ddraw/ddraw.dll','projectdiablo2/compat/fps-renderer/ddraw.dll']
 hud=z.read('projectdiablo2/compat/fps-renderer/ddraw.dll')
 hud_manifest=json.loads(z.read('projectdiablo2/compat/fps-renderer/manifest.json'))
 hud_size=438272
 hud_sha256='acb44f73f3ee0b2aa4ac98ed860b40e0d9389162eaa7de9ec0028affc778ba5a'
 assert len(hud)==hud_manifest['size']==hud_size
 assert hashlib.sha256(hud).hexdigest()==hud_manifest['sha256']==hud_sha256
 assert hud[:2]==b'MZ' and hud_manifest['upstream']['tag']=='v7.1.0.0'
 own_exes={
  'projectdiablo2/compat/xinput-probe/xinput-probe.exe':(117760,'a29deca066455a989e5c8b81eec216d78090bccb1d76be0ee0d9b34f16df85c6'),
  'projectdiablo2/compat/audio-probe/audio-probe.exe':(114176,'0ce817af5dc0583cef4de5579be6d421ed8fb8610d2274216e35822d5490370e'),
  'projectdiablo2/compat/fps-hotkey/fps-hotkey.exe':(84480,'e6ed9a039039340479d5bedfa17f627e7b00ea43daeeb54313c814124ae0d4ca')}
 assert {n for n in z.namelist() if n.lower().endswith('.exe')}==set(own_exes)
 for name,(size,digest) in own_exes.items():
  content=z.read(name)
  assert len(content)==size and hashlib.sha256(content).hexdigest()==digest,name
 native=z.read('projectdiablo2/compat/alsa-native/alsa-native.armhf')
 assert len(native)==5540 and hashlib.sha256(native).hexdigest()=='f320169c7c596136949f2ff7210808534708a9d22a1de9014179597b05f1aa21'
 assert native[:5]==b'\x7fELF\x01' and int.from_bytes(native[18:20],'little')==40
 assert ((z.getinfo('projectdiablo2/compat/alsa-native/alsa-native.armhf').external_attr >> 16) & 0o777)==0o755
 for name,size,digest in (
  ('alsa-native.aarch64',10216,'2365cfe1eae1d19d7209d95dd92319e09f11ac75138e5cf42fa7f83341f2d9ec'),
  ('strace.aarch64',1453376,'56e1dab0112c909206e4ef9b33183c70e9fd5c084739d67d1ca9430fa2fd4ec6'),
  ('strace-6.1.tar.xz',2351272,'2579e9cec37dbb786f6ea0bebd15f40dd561ef2bde2a2a2ecdce5963b01859fd')):
  relative='projectdiablo2/compat/alsa-native/'+name
  content=z.read(relative)
  assert len(content)==size and hashlib.sha256(content).hexdigest()==digest,name
  if name.endswith('.aarch64'):
   assert content[:5]==b'\x7fELF\x02' and int.from_bytes(content[18:20],'little')==183
   assert ((z.getinfo(relative).external_attr >> 16) & 0o777)==0o755
 probe=z.read('projectdiablo2/compat/xinput-probe/xinput-probe.exe')
 for name,size,digest in (
  ('libasound.so.2',590552,'899e6f5164ab24fe2863aa22f102f3baa60dc4a0f9978e79ed4588fab57b78f8'),
  ('alsa-lib-1.2.8.tar.bz2',1091475,'1ab01b74e33425ca99c2e36c0844fd6888273193bd898240fe8f93accbcbf347')):
  content=z.read('projectdiablo2/compat/alsa-legacy-armhf/'+name)
  assert len(content)==size and hashlib.sha256(content).hexdigest()==digest,name
 assert len(probe)==117760 and hashlib.sha256(probe).hexdigest()=='a29deca066455a989e5c8b81eec216d78090bccb1d76be0ee0d9b34f16df85c6'
 for name in allow:
  assert z.read(name)==(ROOT/'sdcard/ports'/name).read_bytes(),name
 print('ZIP entries:',len(z.namelist()),'bytes:',p.stat().st_size,'SHA256:',hashlib.sha256(p.read_bytes()).hexdigest())
