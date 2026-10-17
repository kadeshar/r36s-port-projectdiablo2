"""Static ELF/Wine audit without running any downloaded executable."""
import json,pathlib,struct,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
def elf_needed(data):
 if data[:4]!=b'\x7fELF':return None
 bits=data[4];endian='<' if data[5]==1 else '>';machine=struct.unpack_from(endian+'H',data,18)[0]
 if bits==1:
  phoff=struct.unpack_from(endian+'I',data,28)[0];ents,num=struct.unpack_from(endian+'HH',data,42);fmt=endian+'IIIIIIII';dynfmt=endian+'II'
 else:
  phoff=struct.unpack_from(endian+'Q',data,32)[0];ents,num=struct.unpack_from(endian+'HH',data,54);fmt=endian+'IIQQQQQQ';dynfmt=endian+'QQ'
 segments=[];dynamic=None
 for i in range(num):
  v=struct.unpack_from(fmt,data,phoff+i*ents)
  typ=v[0];offset=v[1] if bits==1 else v[2];addr=v[2] if bits==1 else v[3];size=v[4] if bits==1 else v[5]
  if typ==1:segments.append((addr,size,offset))
  if typ==2:dynamic=(offset,size)
 needed=[];straddr=None
 if dynamic:
  step=struct.calcsize(dynfmt)
  for off in range(dynamic[0],sum(dynamic),step):
   tag,value=struct.unpack_from(dynfmt,data,off)
   if tag==0:break
   if tag==1:needed.append(value)
   if tag==5:straddr=value
 result=[]
 if straddr:
  for addr,size,off in segments:
   if addr<=straddr<addr+size:
    base=off+straddr-addr
    for n in needed:result.append(data[base+n:data.index(b'\0',base+n)].decode())
 return {'machine':machine,'bits':32 if bits==1 else 64,'needed':result}
def main():
 runtime=ROOT/'sdcard/ports/projectdiablo2/runtime';report={}
 with tarfile.open(runtime/'wine-8.0-x86.tar.xz','r:xz') as archive:
  for member in archive.getmembers():
   if member.isfile():
    data=archive.extractfile(member).read();info=elf_needed(data)
    if info:report[member.name]=info
 report['box86']=elf_needed((runtime/'box86').read_bytes())
 out=ROOT/'runtime-audit.json';out.write_text(json.dumps(report,indent=2)+'\n')
 print('ELF files:',len(report),'Wine machines:',sorted({v['machine'] for k,v in report.items() if k!='box86'}))
 print('Box86:',report['box86'])
 for name,v in report.items():
  if '/bin/' in name or name.endswith(('winex11.drv.so','winealsa.drv.so','ntdll.so')):print(name,v)
 print('All DT_NEEDED:',','.join(sorted({n for v in report.values() for n in v['needed']})))
if __name__=='__main__':main()
