"""Private-prefix metrics scope, without reading real process environments."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'sdcard/ports/projectdiablo2/scripts/metrics.py'
SPEC=importlib.util.spec_from_file_location('pd2_scope_metrics',SCRIPT)
metrics=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class ScopeTests(unittest.TestCase):
 def setUp(self):
  self.root=Path('PRIVATE_PROC')
  self.files={};self.binary={};self.reads=[];self.executable_identities={}
  def executable_stat(path,*args,**kwargs):
   identity=self.executable_identities.get(str(path),(1,123))
   if isinstance(identity,Exception):raise identity
   return metrics.os.stat_result((metrics.stat.S_IFREG|0o755,identity[1],identity[0],1,1000,1000,0,0,0,0))
  mock=patch.object(metrics.os,'stat',executable_stat);mock.start();self.addCleanup(mock.stop)
  def open_text(path,*args,**kwargs):
   value=self.files.get(path)
   if value is None:raise FileNotFoundError()
   return io.StringIO(value)
  def read_binary(path,limit):
   self.reads.append((path,limit))
   value=self.binary.get(path)
   if isinstance(value,Exception) or value is None or len(value)>limit:return None
   return value
  def iterdir(path):
   return iter(sorted({self.root/p.relative_to(self.root).parts[0] for p in self.files}))
  for target,name,value in [(Path,'open',open_text),(Path,'iterdir',iterdir),(metrics,'_bounded_bytes',read_binary)]:
   mock=patch.object(target,name,value);mock.start();self.addCleanup(mock.stop)
  self.sampler=metrics.MetricsSampler(20,clock_ticks=100,wine_prefix='/private/session',uid=1000,wine_exe='/private/box86')
  self.process(20,start=100)

 def process(self,pid,parent=1,start=101,uid=1000,prefix=b'/private/session',user=10):
  fields=['S']+['0']*21
  for index,value in ((1,parent),(9,2),(11,user),(12,5),(19,start)):fields[index]=str(value)
  self.files[self.root/str(pid)/'stat']=str(pid)+' (PRIVATE NAME) '+' '.join(fields)
  self.binary[self.root/str(pid)/'status']=('Name:\tSECRET\nUid:\t'+(' '.join([str(uid)]*4))+'\nVmRSS: 100 kB\nVmSwap: 3 kB\n').encode()
  self.binary[self.root/str(pid)/'environ']=b'SECRET=NEVER_EXPORT\0WINEPREFIX='+prefix+b'\0'

 def collect(self,now=1000):return self.sampler.collect(self.root,now)
 def remove(self,pid):
  for files in (self.files,self.binary):
   for key in list(files):
    if key.parent.name==str(pid):del files[key]

 def test_reparented_process_is_authorized_independently(self):
  self.process(21,parent=20,start=101)
  self.assertEqual(self.collect()['game_processes'],2)
  self.process(21,parent=1,start=101,user=60)
  result=self.collect(2000)
  self.assertEqual(result['game_processes'],2)
  self.assertEqual(result['game_cpu_pct_x100'],5000)
  self.assertEqual(result['game_scope'],'verified_subset')

 def test_non_wine_helpers_with_inherited_prefix_are_excluded(self):
  self.process(21)
  self.executable_identities[str(self.root/'21'/'exe')]=(1,999)
  self.assertEqual(self.collect()['game_processes'],1)

 def test_wrapper_anchor_can_authorize_but_is_not_aggregated(self):
  self.process(21)
  self.executable_identities[str(self.root/'20'/'exe')]=(1,999)
  result=self.collect()
  self.assertEqual(result['game_processes'],1)
  self.assertEqual(self.sampler.session_bound,100)

 def test_executable_denied_and_racing_are_partial(self):
  self.process(21)
  self.executable_identities[str(self.root/'21'/'exe')]=PermissionError()
  self.assertEqual(self.collect()['game_scope'],'partial')
  self.assertEqual(self.collect()['game_processes'],1)
  original=metrics.os.stat
  count=0
  def racing(path,*args,**kwargs):
   nonlocal count
   if str(path)==str(self.root/'21'/'exe'):
    count+=1
    return SimpleNamespace(st_mode=metrics.stat.S_IFREG,st_dev=1,st_ino=123 if count==1 else 999)
   return original(path,*args,**kwargs)
  with patch.object(metrics.os,'stat',racing):result=self.collect()
  self.assertEqual(result['game_scope'],'partial')
  self.assertEqual(result['game_processes'],1)

 def test_anchor_exit_does_not_end_session(self):
  self.process(21,start=101)
  self.collect();self.remove(20)
  result=self.collect(2000)
  self.assertEqual(result['game_processes'],1)
  self.assertFalse(self.sampler.anchor_ended)
  self.assertEqual(self.sampler.session_bound,100)
  self.assertNotIn('game_cpu_pct_x100',result)

 def test_anchor_reuse_cannot_reset_session_bound(self):
  self.process(21,start=101)
  self.collect()
  self.process(20,start=500,uid=0,prefix=b'/other')
  result=self.collect(2000)
  self.assertEqual(result['game_processes'],1)
  self.assertEqual(self.sampler.session_bound,100)

 def test_stale_same_prefix_wrong_uid_and_prefix_are_rejected(self):
  self.process(21,start=99)
  self.process(22,uid=0)
  self.process(23,prefix=b'/private/session-other')
  result=self.collect()
  self.assertEqual(result['game_processes'],1)
  self.assertNotIn((self.root/'21'/'environ',16384),self.reads)
  self.assertNotIn((self.root/'22'/'environ',16384),self.reads)

 def test_same_tick_non_anchor_is_ambiguous_not_owned(self):
  self.process(21,start=100)
  result=self.collect()
  self.assertEqual(result['game_processes'],1)
  self.assertEqual(result['game_scope'],'partial')

 def test_oversized_uid_does_not_raise_or_authorize(self):
  self.process(21)
  self.binary[self.root/'21'/'status']=b'Uid: '+b'9'*5000+b' 1000 1000 1000\n'
  result=self.collect()
  self.assertEqual(result['game_processes'],1)
  self.assertEqual(result['game_scope'],'partial')

 def test_candidate_pid_reuse_suppresses_cpu_delta(self):
  self.process(21,start=101)
  self.collect()
  self.process(21,start=200,user=900)
  result=self.collect(2000)
  self.assertEqual(result['game_processes'],2)
  self.assertNotIn('game_cpu_pct_x100',result)

 def test_denied_environment_is_partial_not_zero(self):
  self.process(21)
  self.binary[self.root/'21'/'environ']=PermissionError()
  result=self.collect()
  self.assertEqual(result['game_scope'],'partial')
  self.assertEqual(result['game_processes'],1)
  self.assertNotIn('game_cpu_pct_x100',result)

 def test_all_inaccessible_is_unavailable_without_numeric_game_fields(self):
  self.collect();self.remove(20)
  self.process(21)
  self.binary[self.root/'21'/'status']=PermissionError()
  result=self.collect(2000)
  self.assertEqual(result,{'game_scope':'unavailable'})

 def test_anchor_must_be_authenticated_once_and_never_rebound(self):
  self.binary[self.root/'20'/'environ']=PermissionError()
  self.assertEqual(self.collect(),{'game_scope':'unavailable'})
  self.process(20,start=900)
  self.assertEqual(self.collect(2000),{'game_scope':'unavailable'})

 def test_anchor_wrong_uid_or_prefix(self):
  for changes in ({'uid':0},{'prefix':b'/other'}):
   self.sampler=metrics.MetricsSampler(20,wine_prefix='/private/session',uid=1000,wine_exe='/private/box86')
   self.process(20,start=100,**changes)
   self.assertEqual(self.collect(),{'game_scope':'unavailable'})

 def test_duplicate_prefix_and_unterminated_environment_rejected(self):
  self.process(21)
  for value in (b'WINEPREFIX=/private/session\0WINEPREFIX=/private/session\0',b'WINEPREFIX=/private/session'):
   self.binary[self.root/'21'/'environ']=value
   result=self.collect()
   self.assertEqual(result['game_processes'],1)

 def test_oversized_environment_and_status_do_not_authorize(self):
  self.process(21);self.process(22)
  self.binary[self.root/'21'/'environ']=b'X'*16385
  self.binary[self.root/'22'/'status']=b'X'*16385
  result=self.collect()
  self.assertEqual(result['game_scope'],'partial')
  self.assertEqual(result['game_processes'],1)

 def test_uid_effective_saved_fs_must_all_match(self):
  self.process(21)
  self.binary[self.root/'21'/'status']=b'Uid: 1000 0 1000 1000\n'
  self.assertEqual(self.collect()['game_processes'],1)

 def test_identity_race_is_omitted(self):
  self.process(21)
  original=metrics._process
  count=0
  def racing(root,pid):
   nonlocal count
   if pid==21:
    count+=1
    if count>=2:self.process(21,start=999)
   return original(root,pid)
  with patch.object(metrics,'_process',racing):result=self.collect()
  self.assertEqual(result['game_scope'],'partial')
  self.assertEqual(result['game_processes'],1)

 def test_ownership_race_is_omitted(self):
  self.process(21)
  original=metrics._bounded_bytes
  count=0
  def racing(path,limit):
   nonlocal count
   if path==self.root/'21'/'environ':
    count+=1
    if count==1:self.binary[self.root/'21'/'status']=b'Uid: 0 0 0 0\n'
   return original(path,limit)
  with patch.object(metrics,'_bounded_bytes',racing):result=self.collect()
  self.assertEqual(result['game_scope'],'partial')
  self.assertEqual(result['game_processes'],1)

 def test_directory_cap_is_unavailable(self):
  with patch.object(Path,'iterdir',lambda _:iter([Path(str(i)) for i in range(4097)])):
   self.assertEqual(self.collect(),{'game_scope':'unavailable'})

 def test_scan_access_denied_is_unavailable(self):
  with patch.object(Path,'iterdir',side_effect=PermissionError()):
   self.assertEqual(self.collect(),{'game_scope':'unavailable'})

 def test_candidate_read_cap_marks_partial(self):
  self.collect()
  for pid in range(100,1130):self.process(pid)
  result=self.collect(2000)
  self.assertEqual(result['game_scope'],'partial')
  self.assertLessEqual(result['game_processes'],1024)
  self.assertLessEqual(len(self.reads),2+4*1024+8)

 def test_data_never_exported(self):
  self.process(21)
  value=json.dumps(self.collect())
  for private in ('SECRET','PRIVATE','session','WINEPREFIX','uid','environ','pid'):self.assertNotIn(private,value)
  self.assertTrue(all(type(v) is int for k,v in self.collect().items() if k!='game_scope'))

 def test_constructor_rejects_unpaired_or_invalid_scope(self):
  for kwargs in ({'uid':1000},{'wine_prefix':'/p'},{'wine_prefix':'relative','uid':1},{'wine_prefix':'/p','uid':-1}):
   with self.assertRaises(ValueError):metrics.MetricsSampler(20,**kwargs)

 def test_main_session_mode_survives_anchor_exit(self):
  calls=[]
  def snapshot(*args,**kwargs):
   calls.append(kwargs)
   if len(calls)==1:kwargs['sampler'].collect(self.root,1000);self.remove(20)
   else:raise KeyboardInterrupt()
  with patch('sys.argv',['metrics','--port','PRIVATE','--pid','20','--wine-prefix','/private/session','--uid','1000','--wine-exe','/private/box86']),patch.object(metrics,'snapshot',snapshot),patch.object(metrics.time,'sleep'):
   self.assertEqual(metrics.main(),1)
  self.assertEqual(len(calls),2)

 def test_main_rejects_scope_for_mapper(self):
  with patch('sys.argv',['metrics','--port','PRIVATE','--pid','20','--wine-prefix','/p','--uid','1000','--role','mapper']):
   self.assertEqual(metrics.main(),1)


class BoundedReadTests(unittest.TestCase):
 def test_binary_read_rejects_oversized_and_denied(self):
  for size,expected in ((16,b'X'*16),(17,None)):
   with patch.object(metrics.os,'open',return_value=123),patch.object(metrics.os,'fdopen',return_value=io.BytesIO(b'X'*size)):
    self.assertEqual(metrics._bounded_bytes(Path('PRIVATE'),16),expected)
  with patch.object(metrics.os,'open',side_effect=PermissionError()):
   self.assertIsNone(metrics._bounded_bytes(Path('PRIVATE'),16))


if __name__=='__main__':unittest.main()
