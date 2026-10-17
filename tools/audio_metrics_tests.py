#!/usr/bin/env python3
"""Read-only schema/selector/source tests; POSIX child capture integration."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'sdcard/ports/projectdiablo2/scripts'
sys.path.insert(0, str(SCRIPTS))
import audio_metrics as am
spec = importlib.util.spec_from_file_location('audio_metrics_build', ROOT / 'tools/audio_metrics_build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def record(**overrides):
    value = {key: 0 for key in am.BOUNDS}
    value.update(schema=1,pid=1001,stream=1,active=1,params_valid=1,rate_hz=48000,
                 channels=2,access=3,period_frames=480,buffer_frames=1920,
                 write_calls=10,write_frames=4800)
    value.update(overrides)
    return value


def line(**overrides):
    return json.dumps(record(**overrides)).encode('ascii')


class WireTests(unittest.TestCase):
    def test_valid_numeric_stream(self):
        self.assertEqual(am.decode_line(line())['write_frames'],4800)

    def test_reject_unknown_keys_paths_and_samples(self):
        for key,value in [('name','hw:rk817'),('path','/secret'),('samples',[1,2])]:
            data=record(); data[key]=value
            with self.assertRaises(ValueError): am.decode_line(json.dumps(data).encode())

    def test_reject_duplicate_keys(self):
        with self.assertRaises(ValueError): am.decode_line(line()[:-1]+b',"pid":1002}')

    def test_reject_bool_float_string_negative(self):
        for invalid in (True,1.0,'1',-1,10**15+1,None):
            with self.assertRaises(ValueError): am.decode_line(line(write_frames=invalid))

    def test_reject_oversized_and_non_ascii(self):
        for invalid in (b'x'*2049,b'\xff',b'[]',b'{}'):
            with self.assertRaises((ValueError,UnicodeError)): am.decode_line(invalid)

    def test_reject_bad_parameters(self):
        for overrides in (dict(rate_hz=0),dict(channels=0),dict(period_frames=2000),dict(access=5)):
            with self.assertRaises(ValueError): am.decode_line(line(**overrides))
        self.assertEqual(am.decode_line(line(params_valid=0,rate_hz=0))['params_valid'],0)

    def test_counter_consistency(self):
        for overrides in (dict(error_results=1),dict(recover_successes=1),dict(short_writes=11)):
            with self.assertRaises(ValueError): am.decode_line(line(**overrides))
        self.assertEqual(am.decode_line(line(error_results=1,epipe_results=1))['epipe_results'],1)

    def test_limit_marker(self):
        self.assertIsNone(am.decode_line(b'{"schema":1,"pid":5,"limited":1}'))
        with self.assertRaises(ValueError): am.decode_line(b'{"schema":1,"pid":5,"limited":true}')

    def test_project_strips_pid_assigns_sources(self):
        events=[]; c=am.Capture(events.append,lambda:12.5)
        c.feed(line()+b'\n'+line(pid=2002)+b'\n'+line()+b'\n'); c.finish()
        samples=[e for e in events if e['event']=='audio_pcm']
        self.assertEqual([e['source'] for e in samples],[1,2,1])
        self.assertFalse(any('pid' in e for e in events))
        self.assertTrue(all(e['sample_monotonic_ms']==12500 for e in samples))

    def test_incremental_chunks_and_no_newline_bound(self):
        events=[]; c=am.Capture(events.append)
        content=line()+b'\n'
        for byte in content: c.feed(bytes([byte]))
        self.assertEqual(c.events,1)
        c.feed(b'x'*10000)
        self.assertLessEqual(len(c.buffer),am.LINE_LIMIT)
        self.assertTrue(c.invalid)
        c.feed(b'\n'+line()+b'\n')
        self.assertEqual(c.events,2)

    def test_no_raw_output_on_invalid(self):
        events=[]; c=am.Capture(events.append)
        c.feed(b'character secret-account device=/private\n'); c.finish()
        text=json.dumps(events)
        self.assertNotIn('secret',text); self.assertIn('invalid_capture',text)

    def test_input_limit_drains_without_storing(self):
        events=[]; c=am.Capture(events.append)
        c.feed(b'x'*(am.INPUT_LIMIT+20000)); c.feed(line()+b'\n')
        self.assertEqual(c.input_bytes,am.INPUT_LIMIT); self.assertEqual(c.events,0)
        self.assertEqual(sum(e.get('status')=='capture_limit' for e in events),1)

    def test_source_limit(self):
        events=[]; c=am.Capture(events.append)
        for i in range(am.SOURCE_LIMIT+1): c.feed(line(pid=i+1)+b'\n')
        self.assertEqual(c.events,am.SOURCE_LIMIT); self.assertTrue(c.limited)

    def test_event_limit(self):
        events=[]; c=am.Capture(events.append)
        with patch.object(am,'EVENT_LIMIT',2):
            for _ in range(3): c.feed(line()+b'\n')
        self.assertEqual(c.events,2); self.assertTrue(c.limited)

    def test_no_stream_is_not_zero_playback(self):
        events=[]; c=am.Capture(events.append); c.finish()
        self.assertEqual(events,[am.status('no_stream')])

    def test_incomplete_line(self):
        events=[]; c=am.Capture(events.append); c.feed(line()); c.finish()
        self.assertEqual(events,[am.status('invalid_capture')])


class ArtifactTests(unittest.TestCase):
    def test_pins_match_manifest_when_available(self):
        path=ROOT/'sdcard/ports/projectdiablo2'/am.LIBRARY_PATH
        if not path.is_file(): self.skipTest('ARM build not available yet')
        import hashlib
        self.assertEqual(path.stat().st_size,am.LIBRARY_SIZE)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),am.LIBRARY_SHA256)
        manifest=json.loads((path.parent/'manifest.json').read_text())
        self.assertEqual(manifest['sha256'],am.LIBRARY_SHA256)

    @unittest.skipUnless(os.name=='posix','secure 0700 staging is POSIX; Windows tempfile ACL fixture unsupported')
    def test_prepare_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/am.DIRECTORY; destination.mkdir()
            with patch.object(am,'LIBRARY_SIZE',1),patch.object(am,'LIBRARY_SHA256','x'),patch.object(am,'artifact_bytes',return_value=b'x'):
                with self.assertRaises(ValueError): am.prepare(ROOT,directory)

    @unittest.skipUnless(os.name=='posix','secure 0700 staging is POSIX; Windows tempfile ACL fixture unsupported')
    def test_prepare_exact_bytes_private_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(am,'LIBRARY_SIZE',1),patch.object(am,'LIBRARY_SHA256','x'),patch.object(am,'artifact_bytes',return_value=b'x'):
                target=am.prepare(ROOT,directory)/'libasound.so.2'
            self.assertEqual(target.read_bytes(),b'x')
            if os.name=='posix': self.assertEqual(target.stat().st_mode&0o777,0o400)

    def test_source_wraps_exact_definitions(self):
        original=(ROOT/'.state/audio-metrics-source/alsa-lib-1.2.8/src/pcm/pcm.c')
        if not original.is_file(): self.skipTest('read-only extracted source not present')
        text=original.read_text()
        patched=build.patch_pcm(text)
        self.assertEqual(patched.count('/* PD2 metrics: exact public ABI;'),len(build.SPECS))
        self.assertIn('static int pd2_original_snd_pcm_open(',patched)
        self.assertIn('int snd_pcm_open(',patched)
        self.assertIn('errno = pd2_errno;',patched)
        self.assertNotIn('dlsym(',patched)
        with self.assertRaises(ValueError): build.patch_pcm('unrecognized source')

    @unittest.skipUnless(os.name=='posix','pass_fds requires POSIX')
    def test_real_child_pipe_exit_status(self):
        child='import os; os.write(int(os.environ["PD2_AUDIO_METRICS_FD"]),'+repr(line()+b'\n')+'); raise SystemExit(7)'
        result=subprocess.run([sys.executable,str(SCRIPTS/'audio_metrics.py'),'run','--',sys.executable,'-c',child],capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,7,result.stderr)
        events=[json.loads(x[len('PD2_EVENT '):]) for x in result.stdout.splitlines()]
        self.assertTrue(any(e.get('event')=='audio_pcm' for e in events))
        self.assertNotIn('"pid"',result.stdout)


if __name__=='__main__': unittest.main()
