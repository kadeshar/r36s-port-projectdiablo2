#!/usr/bin/env python3
"""Nonroot, local-only X11 Setup check using one private session cookie.
Never persist reply/vendor/auth bytes; no Xlib/xdpyinfo, TCP or arbitrary files.
"""
import errno,json,os,socket,stat,struct,sys,time
sys.dont_write_bytecode=True
PATH='/tmp/.X11-unix/X0';AUTH_NAME=b'MIT-MAGIC-COOKIE-1';DISPLAY=b'0';MAX_AUTH=4096
ENDPOINTS={'filesystem':PATH,'abstract':'\0'+PATH}

def emit(**fields):
 print('PD2_EVENT '+json.dumps(dict(event='x11_probe',phase='runtime',**fields),separators=(',',':')),flush=True)

def socket_state(path=PATH):
 try:
  info=os.lstat(path)
  if not stat.S_ISSOCK(info.st_mode):return 'invalid',{}
  owner='user' if info.st_uid==os.geteuid() else 'root' if info.st_uid==0 else 'other'
  return 'ready',{'mode':stat.S_IMODE(info.st_mode),'owner':owner}
 except FileNotFoundError:return 'missing',{}
 except PermissionError:return 'denied',{}
 except OSError:return 'io_error',{}

def _auth_status():
 path=os.environ.get('PD2_XAUTHORITY','')
 expected=os.path.join(os.environ.get('PD2_RUN',''), 'xauthority')
 if not path or path!=expected or os.path.basename(path)!='xauthority':return 'invalid',None
 try:
  fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
  try:
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_AUTH:return 'invalid',None
   data=os.read(fd,MAX_AUTH+1)
  finally:os.close(fd)
  if len(data)>MAX_AUTH:return 'invalid',None
  pos=0;found=None
  while pos<len(data):
   if len(data)-pos<2:return 'invalid',None
   family=struct.unpack_from('>H',data,pos)[0];pos+=2;fields=[]
   for _ in range(4):
    if len(data)-pos<2:return 'invalid',None
    length=struct.unpack_from('>H',data,pos)[0];pos+=2
    if length>1024 or len(data)-pos<length:return 'invalid',None
    fields.append(data[pos:pos+length]);pos+=length
   address,number,name,cookie=fields
   if number==DISPLAY and name==AUTH_NAME and len(cookie)==16 and found is None:found=cookie
  return ('ready',found) if found is not None else ('missing',None)
 except FileNotFoundError:return 'missing',None
 except PermissionError:return 'denied',None
 except OSError:return 'invalid',None

def _failure_status(header,receive,client):
 units=struct.unpack_from('<H',header,6)[0]
 if units>65535:return 'setup_rejected'
 try:body=receive(client,units*4)
 except (TimeoutError,EOFError):return 'setup_rejected'
 reason_len=header[1]
 reason=body[:min(reason_len,len(body))].lower()
 if any(token in reason for token in (b'auth',b'authoriz',b'protocol specified')):return 'auth_rejected'
 return 'setup_rejected'

def check(endpoint,timeout=15,factory=socket.socket,cookie=None):
 started=time.monotonic();deadline=started+timeout;step='connect'
 def remaining():
  value=deadline-time.monotonic()
  if value<=0:raise TimeoutError()
  return value
 def receive(client,count):
  value=bytearray()
  while len(value)<count:
   client.settimeout(remaining());chunk=client.recv(count-len(value))
   if not chunk:raise EOFError()
   value.extend(chunk)
  return bytes(value)
 try:
  with factory(socket.AF_UNIX,socket.SOCK_STREAM) as client:
   client.settimeout(remaining());client.connect(ENDPOINTS[endpoint]);step='reply'
   client.settimeout(remaining())
   # Byte order little endian; X11 11.0; use the private MIT cookie.
   if cookie is None or len(cookie)!=16:return 'auth_missing'
   name=AUTH_NAME;payload=struct.pack('<BBHHHHH',ord('l'),0,11,0,len(name),len(cookie),0)+name+b'\0'*((-len(name))%4)+cookie+b'\0'*((-len(cookie))%4)
   client.sendall(payload)
   header=receive(client,8);status,_,major,minor,units=struct.unpack('<BBHHH',header)
   if status==0:return _failure_status(header,receive,client)
   if status==2:return 'auth_required'
   if status!=1 or major!=11 or minor!=0 or units<8:return 'invalid_reply'
   # Consume the bounded Setup body (max 262140 bytes), discard all fields.
   receive(client,units*4)
   return 'ready'
 except TimeoutError:return step+'_timeout'
 except EOFError:return 'disconnected'
 except OSError as exc:
  return {errno.EACCES:'denied',errno.EPERM:'denied',errno.ENOENT:'missing',errno.ECONNREFUSED:'refused',errno.ECONNRESET:'disconnected',errno.EPIPE:'disconnected'}.get(exc.errno,'io_error')

def main():
 # Fail closed if mistakenly invoked as root; this must model the game user.
 if os.geteuid()==0:
  emit(check='identity',status='root_forbidden');return 2
 emit(check='identity',status='ready')
 status,fields=socket_state();emit(check='socket',status=status,**fields)
 auth_status,cookie=_auth_status();emit(check='auth',status=auth_status)
 if auth_status!='ready':return 1
 filesystem=False
 for endpoint in ENDPOINTS:
  start=time.monotonic();status=check(endpoint,cookie=cookie)
  emit(check=endpoint,status=status,duration_ms=int((time.monotonic()-start)*1000))
  if endpoint=='filesystem':filesystem=status=='ready'
 # Pathname connection must really work; abstract readiness alone hides perms.
 return 0 if filesystem else 1

if __name__=='__main__':raise SystemExit(main())
