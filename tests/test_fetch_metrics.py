import contextlib,hashlib,importlib.util,io,json,pathlib,re,shutil,subprocess,sys,unittest,uuid
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
fetch=load('fetch_runtime_tests',ROOT/'tools/fetch_runtime.py')
metrics=load('metrics_tests',ROOT/'sdcard/ports/projectdiablo2/scripts/metrics.py')
logger=load('metrics_logger_tests',ROOT/'sdcard/ports/projectdiablo2/scripts/safe_log.py')
class Response(io.BytesIO):
 url='https://example.invalid/runtime?private-token=omitted'
class FetchMetricsTests(unittest.TestCase):
 def setUp(self):
  self.base=ROOT/'tests'/('fetch-fixture-'+uuid.uuid4().hex);self.base.mkdir(mode=0o755);self.path=self.base/'artifact.bin';self.content=b'synthetic-runtime';self.hash=hashlib.sha256(self.content).hexdigest()
 def tearDown(self):
  assert self.base.absolute().parent==ROOT/'tests' and self.base.name.startswith('fetch-fixture-')
  shutil.rmtree(self.base)
 def fetch(self,response=None,expected=None,locked=None):
  with patch.object(fetch.urllib.request,'urlopen',return_value=response or Response(self.content)):
   return fetch.download_verified(self.path,'https://example.invalid/runtime','sha256',expected or self.hash,locked)
 def test_verified_atomic_publication_removes_temp_and_url_secret(self):
  url=self.fetch();self.assertEqual(self.path.read_bytes(),self.content);self.assertNotIn('?',url);self.assertEqual(list(self.base.iterdir()),[self.path]);self.assertEqual(self.path.stat().st_nlink,1)
 def test_checksum_mismatch_never_publishes(self):
  with self.assertRaises(ValueError):self.fetch(expected='0'*64)
  self.assertEqual(list(self.base.iterdir()),[])
 def test_lock_mismatch_never_publishes(self):
  with self.assertRaises(ValueError):self.fetch(locked='0'*64)
  self.assertFalse(self.path.exists())
 def test_partial_failure_retries_without_deleting_unowned_legacy_partial(self):
  legacy=self.path.with_suffix('.bin.partial');legacy.write_bytes(b'keep')
  class Failed(Response):
   def read(self,*args):raise OSError('synthetic transfer failure')
  with self.assertRaises(OSError):self.fetch(response=Failed(self.content))
  self.assertEqual(list(self.base.iterdir()),[legacy]);self.fetch();self.assertEqual(legacy.read_bytes(),b'keep')
 def test_existing_artifact_never_overwritten(self):
  self.path.write_bytes(b'keep')
  with patch.object(fetch.urllib.request,'urlopen') as net:
   with self.assertRaises(ValueError):fetch.download_verified(self.path,'https://example.invalid','sha256',self.hash)
   net.assert_not_called()
  self.assertEqual(self.path.read_bytes(),b'keep')
 def test_racing_publication_preserves_other_final(self):
  def race(source,target):pathlib.Path(target).write_bytes(b'other');raise FileExistsError()
  with patch.object(fetch.os,'link',side_effect=race):
   with self.assertRaises(FileExistsError):self.fetch()
  self.assertEqual(self.path.read_bytes(),b'other');self.assertEqual(list(self.base.iterdir()),[self.path])
 def test_actual_launcher_preflight_only_hashes_four_pinned_runtimes(self):
  port=ROOT/'sdcard/ports/projectdiablo2'
  if not (port/'runtime-manifest.json').exists():self.skipTest('Pinned runtime not prepared')
  source=(ROOT/'sdcard/ports/Project Diablo 2.sh').read_text()
  program=re.search(r'python3 - "\$PD2_PORT" <<\'PY\'\n(.*?)\nPY',source,re.S).group(1)
  result=subprocess.run([sys.executable,'-B','-',str(port)],input=program,text=True,capture_output=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  self.assertEqual(result.stdout,'')
 def test_metrics_snapshot_only_schema_numbers(self):
  out=io.StringIO()
  with contextlib.redirect_stdout(out):metrics.snapshot(self.base)
  event=logger.parse_line(out.getvalue().strip());self.assertIsNotNone(event);self.assertEqual(event['event'],'metrics')
  self.assertTrue(all(type(v) is int for k,v in event.items() if k!='event'));self.assertNotIn(str(self.base),out.getvalue())
 def test_metrics_enable_only_explicit_boolean(self):
  port=self.base/'port';(port/'config').mkdir(parents=True);f=port/'config/settings.json'
  for value,wanted in [(True,'1'),(False,'0'),('private-player','0'),(1,'0')]:
   f.write_text(json.dumps({'metrics':value,'account':'secret'}));out=io.StringIO()
   with patch('sys.argv',['metrics','--port',str(port),'--enabled']),contextlib.redirect_stdout(out):self.assertEqual(metrics.main(),0)
   self.assertEqual(out.getvalue().strip(),wanted)
if __name__=='__main__':unittest.main()
