"""Only synthetic X11 peers, never Xwayland/ARM/Wine/game execution."""
import contextlib,errno,importlib.util,io,json,os,pathlib,shutil,socket,struct,subprocess,sys,tempfile,threading,unittest
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0,str(SCRIPTS));import safe_log
spec=importlib.util.spec_from_file_location('x11_test',SCRIPTS/'x11_probe.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
HEADER=struct.pack('<BBHHH',1,0,11,0,8)
class FakeSocket:
 def __init__(self,reply=HEADER+bytes(32),error=None):self.reply=reply;self.error=error;self.sent=b''
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def settimeout(self,value):assert 0<value<=15
 def connect(self,path):
  if self.error:raise self.error
 def sendall(self,data):self.sent=data
 def recv(self,count):value=self.reply[:min(count,3)];self.reply=self.reply[len(value):];return value
class X11Tests(unittest.TestCase):
 def setUp(self):
  if not hasattr(socket,'AF_UNIX'):
   patch=mock.patch.object(socket,'AF_UNIX',1,create=True);patch.start();self.addCleanup(patch.stop)
 def test_valid_fragmented_setup_and_fixed_endpoints(self):
  peer=FakeSocket();self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),'ready')
  self.assertEqual(peer.sent,struct.pack('<BBHHHHH',108,0,11,0,len(probe.AUTH_NAME),16,0)+probe.AUTH_NAME+b'\0'*((-len(probe.AUTH_NAME))%4)+b'x'*16)
  self.assertEqual(set(probe.ENDPOINTS),{'filesystem','abstract'});self.assertTrue(probe.ENDPOINTS['abstract'].startswith('\0'))
 def test_full_advertised_body_consumed_without_vendor_output(self):
  peer=FakeSocket(struct.pack('<BBHHH',1,0,11,0,64)+(b'private-vendor-token'+bytes(256))[:256])
  self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),'ready');self.assertEqual(peer.reply,b'')
 def test_drip_feed_uses_one_deadline_not_per_read(self):
  peer=FakeSocket()
  with mock.patch.object(probe.time,'monotonic',side_effect=[0,0,0,14,16]):
   self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),'reply_timeout')
 def test_transport_errors_have_only_enum(self):
  for code,status in [(errno.EACCES,'denied'),(errno.ENOENT,'missing'),(errno.ECONNREFUSED,'refused'),(errno.ECONNRESET,'disconnected'),(errno.EIO,'io_error')]:
   peer=FakeSocket(error=OSError(code,'/home/private-CD-KEY'));self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),status)
 def test_timeout_distinguishes_connect_and_reply(self):
  peer=FakeSocket(error=TimeoutError('secret'));self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),'connect_timeout')
  class Slow(FakeSocket):
   def recv(self,count):raise TimeoutError('private')
  self.assertEqual(probe.check('abstract',cookie=b'x'*16,factory=lambda *a:Slow()),'reply_timeout')
 def test_auth_status_never_reads_or_echoes_reason(self):
  for code,status in [(0,'setup_rejected'),(2,'auth_required')]:
   peer=FakeSocket(struct.pack('<BBHHH',code,99,11,0,100)+b'account-secret')
   self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:peer),status)
 def test_bad_protocol_short_setup_and_eof(self):
  for reply,status in [(b'','disconnected'),(HEADER,'disconnected'),(struct.pack('<BBHHH',1,0,12,0,8),'invalid_reply'),(struct.pack('<BBHHH',1,0,11,0,7),'invalid_reply'),(struct.pack('<BBHHH',3,0,11,0,8),'invalid_reply')]:
   self.assertEqual(probe.check('filesystem',cookie=b'x'*16,factory=lambda *a:FakeSocket(reply)),status)
 def test_closed_schema_rejects_raw_fields_invalid_combinations(self):
  self.assertIsNotNone(safe_log.validate_event({'event':'x11_probe','phase':'runtime','check':'auth','status':'ready'}))
  event={'event':'x11_probe','phase':'runtime','check':'filesystem','status':'reply_timeout','duration_ms':15000}
  self.assertIsNotNone(safe_log.validate_event(event))
  for key,value in [('path','/private'),('status','private'),('duration_ms',True),('duration_ms',-1),('duration_ms',120001),('check',[]),('owner','root')]:
   changed=dict(event);changed[key]=value;self.assertIsNone(safe_log.validate_event(changed))
  good={'event':'x11_probe','phase':'runtime','check':'socket','status':'ready','mode':0o660,'owner':'root'}
  self.assertIsNotNone(safe_log.validate_event(good));good['owner']='private-user';self.assertIsNone(safe_log.validate_event(good))
 def test_main_root_is_fail_closed(self):
  output=io.StringIO()
  with mock.patch.object(probe.os,'geteuid',return_value=0,create=True),mock.patch.object(probe,'check') as check,contextlib.redirect_stdout(output):self.assertEqual(probe.main(),2)
  check.assert_not_called();self.assertIn('root_forbidden',output.getvalue())
 def test_main_records_both_transports_and_requires_filesystem(self):
  for filesystem,abstract,rc in [('ready','refused',0),('denied','ready',1)]:
   output=io.StringIO()
   with mock.patch.object(probe.os,'geteuid',return_value=1000,create=True),mock.patch.object(probe,'socket_state',return_value=('ready',{'mode':0o660,'owner':'root'})),mock.patch.object(probe,'_auth_status',return_value=('ready',b'x'*16)),mock.patch.object(probe,'check',side_effect=[filesystem,abstract]),contextlib.redirect_stdout(output):self.assertEqual(probe.main(),rc)
   rows=[json.loads(x[len('PD2_EVENT '):]) for x in output.getvalue().splitlines()];self.assertEqual(len(rows),5)
   for row in rows:self.assertIsNotNone(safe_log.validate_event(row))
 def test_scoped_socket_fix_and_nonroot_probe_in_adapter(self):
  source=(SCRIPTS/'weston-session.sh').read_text()
  self.assertIn('$(stat -c %u /tmp/.X11-unix/X0) == 0',source)
  self.assertIn('! -L /tmp/.X11-unix/X0',source);self.assertIn('chmod 660 /tmp/.X11-unix/X0',source)
  self.assertIn('python3 -B "$PD2_PORT/scripts/x11_probe.py"',source);self.assertIn('PD2_XAUTHORITY',source)
  self.assertNotIn('"$W/tools/xdpyinfo"',source);self.assertIn('timeout --kill-after=5 35 runuser',source)
 @unittest.skipUnless(sys.platform.startswith('linux'),'Linux Unix sockets')
 def test_real_unix_peer_fragmented_setup(self):
  with tempfile.TemporaryDirectory(prefix='pd2-x11-test-') as d:
   path=str(pathlib.Path(d)/'sock');server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(path);server.listen(1)
   errors=[]
   def respond():
    try:
     with server.accept()[0] as client:
      client.settimeout(3);data=bytearray()
      while len(data)<48:data.extend(client.recv(48-len(data)))
      if bytes(data)!=struct.pack('<BBHHHHH',108,0,11,0,len(probe.AUTH_NAME),16,0)+probe.AUTH_NAME+b'\0'*((-len(probe.AUTH_NAME))%4)+b'x'*16:errors.append('bad request')
      client.sendall(HEADER+bytes(32))
    finally:server.close()
   thread=threading.Thread(target=respond,daemon=True);thread.start()
   with mock.patch.dict(probe.ENDPOINTS,filesystem=path):self.assertEqual(probe.check('filesystem',timeout=3,cookie=b'x'*16),'ready')
   thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
 @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os,'geteuid') and os.geteuid()==0,'Root Linux permission smoke')
 def test_real_root_socket_denied_then_group_access(self):
  import pwd
  if not shutil.which('runuser'):self.skipTest('runuser unavailable')
  try:user=pwd.getpwnam('nobody')
  except KeyError:self.skipTest('test-only nobody unavailable')
  with tempfile.TemporaryDirectory(prefix='pd2-x11-perms-') as d:
   os.chown(d,0,user.pw_gid);os.chmod(d,0o750);path=str(pathlib.Path(d)/'sock')
   server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.addCleanup(server.close);server.bind(path);server.listen(1);server.settimeout(5);os.chmod(path,0o700)
   code="import sys;sys.path.insert(0,sys.argv[1]);import x11_probe as p;p.ENDPOINTS['filesystem']=sys.argv[2];print(p.check('filesystem',timeout=3,cookie=b'x'*16))"
   command=['runuser','-u','nobody','--','python3','-B','-c',code,str(SCRIPTS),path]
   before=subprocess.run(command,capture_output=True,text=True,timeout=5);self.assertEqual(before.returncode,0,before.stderr);self.assertEqual(before.stdout.strip(),'denied')
   os.chown(path,0,user.pw_gid);os.chmod(path,0o660)
   def respond():
    with server.accept()[0] as client:
     client.settimeout(3);data=bytearray()
     while len(data)<48:
      chunk=client.recv(48-len(data))
      if not chunk:return
      data.extend(chunk)
     client.sendall(HEADER+bytes(32))
   thread=threading.Thread(target=respond,daemon=True);thread.start()
   after=subprocess.run(command,capture_output=True,text=True,timeout=5);self.assertEqual(after.returncode,0,after.stderr);self.assertEqual(after.stdout.strip(),'ready');thread.join(5);self.assertFalse(thread.is_alive())
if __name__=='__main__':unittest.main()
