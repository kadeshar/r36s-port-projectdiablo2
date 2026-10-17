"""Fetch pinned third-party runtimes; never install system packages."""
import argparse, hashlib, io, json, os, pathlib, struct, tarfile, urllib.request, uuid
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'sdcard/ports/projectdiablo2/runtime'
ARTIFACTS = [
 ('wine-8.0-x86.tar.xz','https://github.com/Kron4ek/Wine-Builds/releases/download/8.0/wine-8.0-x86.tar.xz','sha256','d77d023bd9046547afccae5860dc6089b9d5cd9699f656b83e2f573bbf3fae6d'),
 ('box86.deb','https://raw.githubusercontent.com/Pi-Apps-Coders/box86-debs/master/debian/box86-generic-arm_0.3.9%2B20250213T063429.fa59e74-1_armhf.deb','sha256','a811475076792a1fb834afe4b137fbc3ccd5c766a8ca16d42762013c627a4d70'),
 ('weston_pkg_0.2.squashfs','https://github.com/PortsMaster/PortMaster-New/releases/download/2025-07-24_0745/weston_pkg_0.2.squashfs','md5','0a761c28877625861d9c9c4326664428'),
 ('vc_redist.x86.exe','https://download.visualstudio.microsoft.com/download/pr/8a78e61f-9368-484b-b0c1-5628ff392121/38C9437E6E9EF1DB2671B3F0C879FEBEC08521BD2C23231199F626B69AE1C65E/VC_redist.x86.exe','sha256','38c9437e6e9ef1db2671b3f0c879febec08521bd2c23231199f626b69ae1c65e'),
]
def digest(path, algorithm='sha256'):
 h=hashlib.new(algorithm)
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def ar_members(blob):
 if blob[:8] != b'!<arch>\n':raise ValueError('Invalid ar archive')
 at=8
 while at < len(blob):
  hdr=blob[at:at+60]
  if len(hdr)!=60 or hdr[58:60]!=b'`\n':raise ValueError('Invalid ar member')
  size=int(hdr[48:58]);name=hdr[:16].decode().strip().rstrip('/')
  yield name, blob[at+60:at+60+size]
  at+=60+size+(size%2)
def download_verified(path,url,algorithm,expected,locked_sha=None):
 path=path.absolute()
 if path.is_symlink() or path.exists():raise ValueError('Existing download refused')
 temporary=path.with_name(path.name+'.partial-'+uuid.uuid4().hex)
 try:
  request=urllib.request.Request(url,headers={'User-Agent':'PD2-R36S-private-port/0.1'})
  with urllib.request.urlopen(request,timeout=90) as response, temporary.open('xb') as target:
   resolved=response.url.split('?')[0]
   for chunk in iter(lambda:response.read(1048576),b''):target.write(chunk)
  if digest(temporary,algorithm)!=expected:raise ValueError('Upstream checksum mismatch')
  if locked_sha and digest(temporary)!=locked_sha:raise ValueError('Local lock mismatch')
  # Atomic no-overwrite publication: temporary content is already validated.
  os.link(temporary,path)
  return resolved
 finally:
  # Only remove the exclusive temporary regular file created by this invocation.
  if temporary.parent.resolve()==path.parent.resolve() and temporary.name.startswith(path.name+'.partial-') and not temporary.is_symlink() and temporary.is_file():temporary.unlink()

def main():
 parser=argparse.ArgumentParser();parser.parse_args()
 OUT.mkdir(parents=True,exist_ok=True);cache=ROOT/'.cache';cache.mkdir(exist_ok=True)
 lockpath=ROOT/'runtime-lock.json';lock=json.loads(lockpath.read_text()) if lockpath.exists() else {}
 records=[]
 for name,url,alg,expected in ARTIFACTS:
  path=(cache if name=='box86.deb' else OUT)/name
  if path.is_symlink():raise ValueError('Symlink artifact refused')
  if not path.exists():
   print('Downloading',name,flush=True)
   actual_url=download_verified(path,url,alg,expected,lock.get(name,{}).get('sha256'))
  else:actual_url=lock.get(name,{}).get('resolved_url',url)
  if expected and digest(path,alg)!=expected:raise ValueError('Upstream checksum mismatch: '+name)
  sha=digest(path)
  if name in lock and lock[name]['sha256']!=sha:raise ValueError('Local lock mismatch: '+name)
  record={'file':name,'url':url,'resolved_url':actual_url.split('?')[0],'sha256':sha,'size':path.stat().st_size}
  if alg:record.update(upstream_algorithm=alg,upstream_digest=expected)
  lock[name]=record;records.append(record);print('Verified',name,path.stat().st_size,flush=True)
 # Extract only the executable and documentation; do not install the .deb.
 for name,payload in ar_members((cache/'box86.deb').read_bytes()):
  if not name.startswith('data.tar'):continue
  with tarfile.open(fileobj=io.BytesIO(payload),mode='r:*') as archive:
   for member in archive.getmembers():
    normalized=member.name.removeprefix('./')
    if normalized=='usr/local/bin/box86' or normalized=='usr/bin/box86':
     target=OUT/'box86';content=archive.extractfile(member).read()
     if content[:4]!=b'\x7fELF' or content[4]!=1 or struct.unpack_from('<H',content,18)[0]!=40:raise ValueError('Box86 is not ARM32 ELF')
     if target.exists() and target.read_bytes()!=content:raise ValueError('Box86 existing content mismatch')
     if not target.exists():target.write_bytes(content)
    elif normalized.startswith('usr/share/doc/box86') and member.isfile():
     doc=ROOT/'third-party'/'box86-docs'/pathlib.PurePosixPath(normalized).name;doc.parent.mkdir(parents=True,exist_ok=True)
     if not doc.exists():doc.write_bytes(archive.extractfile(member).read())
 if not (OUT/'box86').exists():raise ValueError('Box86 executable absent')
 records=[r for r in records if r['file']!='box86.deb']+[{'file':'box86','sha256':digest(OUT/'box86'),'size':(OUT/'box86').stat().st_size,'url':ARTIFACTS[1][1],'version':'0.3.9-fa59e74'}]
 lockpath.write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
 manifest={'port_version':'0.1.7','runtime_version':'8.0','experimental':True,'artifacts':records,'microsoft_signature_required':True,'sources':{'wine':'https://dl.winehq.org/wine/source/8.0/wine-8.0.tar.xz','box86':'https://github.com/ptitSeb/box86/tree/fa59e74','weston':'https://github.com/binarycounter/Westonpack/wiki'}}
 (OUT.parent/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
