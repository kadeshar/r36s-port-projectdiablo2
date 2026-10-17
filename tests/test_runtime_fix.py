"""Regression for hardware-report failure; no real game or ARM executable runs."""
import importlib.util,json,os,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'sdcard/ports/projectdiablo2/scripts'
s=importlib.util.spec_from_file_location('fix_logger',SCRIPTS/'safe_log.py');logger=importlib.util.module_from_spec(s);s.loader.exec_module(logger)
class RuntimeFixTests(unittest.TestCase):
 def test_stage_schema_is_closed_not_raw_text(self):
  for stage in logger.STAGES:
   self.assertIsNotNone(logger.validate_event({'event':'runtime_stage','phase':'runtime','stage':stage}))
  for stage in ['private-user','/home/account','CD-KEY-SECRET',{},None]:
   self.assertIsNone(logger.validate_event({'event':'runtime_stage','stage':stage}))
  self.assertIsNone(logger.validate_event({'event':'runtime_stage','stage':'seatd_start','message':'secret'}))
  self.assertIsNone(logger.validate_event({'event':'runtime_stage'}))
 def test_detailed_failure_codes_are_allowlisted(self):
  for reason in ['run_isolation_failed','alias_setup_failed','tmp_isolation_failed','volatile_work_failed','seatd_failed','seatd_timeout','x11_probe_failed','xauth_prepare_failed','namespace_isolation_required']:
   self.assertIsNotNone(logger.validate_event({'event':'runtime_error','phase':'runtime','reason':reason}))
 def test_seatd_invocation_matches_pinned_binary_help(self):
  source=(SCRIPTS/'weston-session.sh').read_text()
  command=next(l for l in source.splitlines() if '"$W/seatd"' in l)
  self.assertNotIn(' -s ',command);self.assertIn(' -g "$group"',command);self.assertIn('LD_PRELOAD="$preload"',command)
  self.assertIn('SEATD_SOCK=/run/seatd.sock',source)
  p=ROOT/'.inspection/seatd/seatd'
  if p.exists():
   data=p.read_bytes();self.assertIn(b'vhn:g:u:l:z\0',data);self.assertNotIn(b'SEATD_SOCK\0',data)
 def test_pm_cleanup_uses_unique_name_and_rearms_trap(self):
  source=(ROOT/'sdcard/ports/Project Diablo 2.sh').read_text()
  self.assertIn('pd2_port_cleanup() {',source);self.assertNotIn('\ncleanup() {',source)
  self.assertIn('&& ( pm_finish )',source)
  self.assertLess(source.index('get_controls ||'),source.rindex('trap pd2_port_cleanup EXIT'))
  self.assertIn('PD2_PARENT_MNT_NS="$PD2_PARENT_MNT_NS"',source)
 @unittest.skipUnless(sys.platform.startswith('linux'),'Bash needed for namespace syscall mocks')
 def test_namespace_refuses_host_context_before_any_mount(self):
  result=self.run_mock(same_namespace=True)
  self.assertEqual(result.returncode,2,result.stdout+result.stderr);self.assertIn('namespace_isolation_required',result.stdout);self.assertNotIn('MOUNT ',result.stdout)
 @unittest.skipUnless(sys.platform.startswith('linux'),'Bash needed for namespace syscall mocks')
 def test_namespace_setup_preserves_host_socket_and_close_order(self):
  result=self.run_mock();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  lines=result.stdout.splitlines();self.assertTrue(any('MOUNT --rbind /run ' in l for l in lines))
  self.assertFalse(any('LINK ' in l and 'seatd.sock' in l for l in lines))
  self.assertTrue(any('LINK ' in l and '/host-run/udev ' in l for l in lines))
  unmount=[l for l in lines if l.startswith('UNMOUNT ')]
  self.assertEqual(unmount[0],'UNMOUNT /tmp');self.assertTrue(unmount[1].startswith('UNMOUNT -R /run/pd2-r36s-'))
  self.assertEqual(unmount[2],'UNMOUNT /run');self.assertIn('/host-run',unmount[3])
 def run_mock(self,same_namespace=False):
  with tempfile.TemporaryDirectory(prefix='pd2-r36s.') as d:
   origin=pathlib.Path(d);(origin/'host-run').mkdir();(origin/'host-run/seatd.sock').write_text('host-owned-marker');(origin/'host-run/udev').mkdir()
   program=r'''
set -u
ORIGINAL_RUN=$1;ALIAS="/run/pd2-r36s-$BASHPID";PD2_PARENT_MNT_NS=host
alias_mounted=0;alias_created=0;tmp_mounted=0;run_mounted=0;host_run_mounted=0
error() { echo "ERROR $1"; }
readlink() { if [[ "$SAME_NAMESPACE" == 1 ]];then echo host;else echo private;fi; }
mkdir() { echo "MKDIR $*"; }
mount() { echo "MOUNT $*"; }
ln() { echo "LINK $*"; }
umount() { echo "UNMOUNT $*"; }
mountpoint() { return 1; }
rmdir() { echo "RMDIR $*"; }
source "$HELPER"
pd2_namespace_open || exit $?
pd2_namespace_close
'''
   env=dict(os.environ,HELPER=str(SCRIPTS/'private-namespace.sh'),SAME_NAMESPACE='1' if same_namespace else '0')
   return subprocess.run(['bash','-c',program,'mock',d],env=env,capture_output=True,text=True,timeout=10)
if __name__=='__main__':unittest.main()
