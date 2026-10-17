"""Bounded presentation and synthetic-probe telemetry. No hardware required."""
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdcard/ports/projectdiablo2/scripts'))
import safe_log
import presentation_watch as watcher
import diagnostic_capture
import graphics_artifacts

class DiagnosticPipelineTests(unittest.TestCase):
    def record(self,**overrides):
        value=dict(event=1,backend=1,frames=15,duration_ms=1000,width=640,height=480)
        value.update(overrides);return json.dumps(value).encode()

    def test_sample_is_count_only_not_fps_claim(self):
        got=watcher.decode_record(self.record())
        self.assertEqual(got,dict(event='render_sample',backend='gdi',frames=15,duration_ms=1000,width=640,height=480))
        self.assertIsNotNone(safe_log.validate_event(got))
        self.assertIsNotNone(safe_log.validate_event(watcher.decode_record(self.record(event=2,frames=0,duration_ms=0))))
        self.assertEqual(watcher.decode_record(self.record(event=3,frames=1,duration_ms=0))['status'],'first_present')

    def test_closed_capture_rejects_data_and_bad_numbers(self):
        for override in ({'event':4},{'backend':3},{'frames':True},{'frames':-1},{'duration_ms':0},{'width':0},{'extra':'private'},{'event':2}):
            self.assertIsNone(watcher.decode_record(self.record(**override)),override)
        self.assertIsNone(watcher.decode_record(b'{"event":1,"event":1}'))
        self.assertIsNone(watcher.decode_record(b'private raw'))
        self.assertIsNotNone(safe_log.validate_event(watcher.status('no_presentation')))

    def test_watch_missing_capture_warns_once_without_signalling_game(self):
        from unittest.mock import patch
        messages=[]
        with patch.object(watcher.os,'kill',side_effect=[None,None,None,ProcessLookupError()]) as kill,patch.object(watcher.Path,'lstat',side_effect=FileNotFoundError()),patch.object(watcher.time,'monotonic',side_effect=[0,31,32,33]),patch.object(watcher.time,'sleep'),patch.object(watcher,'emit',side_effect=messages.append):
            self.assertEqual(watcher.watch('virtual',12345),0)
        self.assertEqual([v['status'] for v in messages],['no_presentation'])
        self.assertTrue(all(call.args==(12345,0) for call in kill.call_args_list))

    def test_first_success_prevents_false_idle_stall(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import stat
        info=SimpleNamespace(st_mode=stat.S_IFREG,st_nlink=1,st_dev=2,st_ino=3)
        messages=[];source=io.BytesIO(self.record(event=3,frames=1,duration_ms=0)+b'\n')
        with patch.object(watcher.os,'kill',side_effect=[None,None,ProcessLookupError()]),patch.object(watcher.Path,'lstat',return_value=info),patch.object(watcher.os,'open',return_value=123),patch.object(watcher.os,'fstat',return_value=info),patch.object(watcher.os,'fdopen',return_value=source),patch.object(watcher.time,'monotonic',return_value=50),patch.object(watcher.time,'sleep'),patch.object(watcher,'emit',side_effect=messages.append):
            self.assertEqual(watcher.watch('virtual',12345),0)
        self.assertEqual([v['status'] for v in messages],['first_present'])

    def test_watch_rejects_link_before_open(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import stat
        messages=[]
        with patch.object(watcher.os,'kill'),patch.object(watcher.Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFLNK,st_nlink=1)),patch.object(watcher.os,'open') as opened,patch.object(watcher,'emit',side_effect=messages.append):
            self.assertEqual(watcher.watch('virtual',12345),1)
        opened.assert_not_called()
        self.assertEqual(messages[0]['status'],'invalid_capture')

    def event(self):
        return dict(event='graphics_layer',schema=1,probe='sdl',stage='context',status='ok',backend='kmsdrm',renderer='unknown',frame=0,code=0)

    def test_capture_drains_raw_and_limits_count(self):
        source=io.BytesIO(b'private data\n'+b'x'*5000+b'\n'+(b'PD2_EVENT '+json.dumps(self.event()).encode()+b'\n')*30)
        sink=io.StringIO();diagnostic_capture.stream(source,sink)
        self.assertEqual(source.read(),b'')
        self.assertNotIn('private',sink.getvalue())
        self.assertLessEqual(len(sink.getvalue().splitlines()),16)
        for line in sink.getvalue().splitlines():
            self.assertEqual(safe_log.parse_line(line)['event'],'graphics_layer')

    def test_schema_rejects_unknown_fields(self):
        good=self.event();self.assertIsNotNone(safe_log.validate_event(good))
        for key,value in [('probe','private'),('backend','private'),('renderer','llvmpipe detail'),('code',True),('schema',True),('frame',4)]:
            bad=dict(good);bad[key]=value
            self.assertIsNone(safe_log.validate_event(bad),(key,value))
        self.assertIsNone(safe_log.validate_event(dict(good,path='secret')))

    def test_stages_are_closed(self):
        for stage in safe_log.SETUP_STAGES:
            self.assertIsNotNone(safe_log.validate_event(dict(event='setup_stage',phase='launch',stage=stage,status='begin')))
        self.assertIsNone(safe_log.validate_event(dict(event='setup_stage',phase='launch',stage='private-path',status='begin')))

    def test_new_metrics_validate_and_reject_strings(self):
        for field in safe_log.SESSION_METRICS:
            self.assertIsNotNone(safe_log.validate_event({'event':'metrics',field:0}),field)
            self.assertIsNone(safe_log.validate_event({'event':'metrics',field:'private'}),field)
        self.assertIsNone(safe_log.validate_event({'event':'metrics','system_cpu_pct_x100':10001}))

    def test_resource_roles_remap_only_authenticated_subtree_totals(self):
        import metrics
        import contextlib
        from unittest.mock import patch
        for role in ('compositor','mapper'):
            sink=io.StringIO()
            with patch.object(metrics,'collect_snapshot',return_value={'event':'metrics','game_cpu_user_ms':42,'system_cpu_pct_x100':100}),contextlib.redirect_stdout(sink):
                metrics.snapshot('unused',role=role)
            value=safe_log.parse_line(sink.getvalue().strip())
            self.assertEqual(value[role+'_cpu_user_ms'],42)
            self.assertNotIn('game_cpu_user_ms',value)
            self.assertEqual(value['system_cpu_pct_x100'],100)

    def test_pinned_probe_artifacts_exist_and_match(self):
        for arch in graphics_artifacts.PINS:
            path,data=graphics_artifacts.authenticate(ROOT/'sdcard/ports/projectdiablo2',arch)
            self.assertEqual(len(data),graphics_artifacts.PINS[arch][1])

if __name__=='__main__': unittest.main()
