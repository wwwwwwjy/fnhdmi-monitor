import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from fnm_support import load_server

class PreferenceTest(unittest.TestCase):
    def setUp(self):
        self.m=load_server();self.c=self.m.DisplayController()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.c.cleanup_data_dir=self.tmp.name
    def result(self,ok=True):
        return subprocess.CompletedProcess([],0 if ok else 1,json.dumps(dict(ok=ok,width=1920,height=1080,message='unsupported')), '')
    def test_success_persists_and_reuses_mode_but_failed_mode_preserves_choice(self):
        with patch.object(self.c,'_run_command',return_value=self.result()) as run:
            self.assertTrue(self.c._fit_window('1280x720')[0])
            self.assertEqual(self.c._read_display_mode(),'1280x720')
            self.c._fit_window();self.assertEqual(run.call_args.args[0][-1],'1280x720')
            run.return_value=self.result(False)
            self.assertFalse(self.c._fit_window('1920x1080')[0])
            self.assertEqual(self.c._read_display_mode(),'1280x720')
        p=Path(self.tmp.name)/'display-output.json';self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_corrupt_or_linked_preference_does_not_overwrite_other_file(self):
        p=Path(self.tmp.name)/'display-output.json';p.write_text('broken')
        self.assertEqual(self.c._read_display_mode(),'auto');p.unlink()
        other=Path(self.tmp.name)/'other';other.write_text('keep');p.symlink_to(other)
        with patch.object(self.c,'_run_command',return_value=self.result()):
            self.assertFalse(self.c._fit_window('1920x1080')[0])
        self.assertEqual(other.read_text(),'keep')
    def test_startup_retries_until_browser_ready_and_then_stops(self):
        with patch.object(self.c,'_fit_window',side_effect=[(False,'not ready'),(True,'ready')]) as fit,patch.object(self.m.time,'sleep'):
            self.c._startup_fit();self.assertEqual(fit.call_count,2)
        self.c._job={'action':'prepare_uninstall','state':'done'}
        with patch.object(self.c,'_fit_window') as fit:
            self.c._startup_fit();fit.assert_not_called()
    def test_startup_is_bounded_and_not_scheduled_on_test_or_mac(self):
        with patch.object(self.m.sys,'platform','darwin'),patch.object(self.m.threading,'Thread') as thread:
            self.c.schedule_startup_fit();thread.assert_not_called()
        with patch.object(self.m.time,'monotonic',side_effect=[0,0,31]),patch.object(self.m.time,'sleep'),patch.object(self.c,'_fit_window',return_value=(False,'not ready')) as fit:
            self.c._startup_fit();self.assertEqual(fit.call_count,1)

if __name__=='__main__':unittest.main()
