"""The browser cleanup action must run independently of app-store hooks."""
import json
import subprocess
import sys
import tempfile
import secrets
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from fnm_support import load_server, ServerProcess


class PrepareUninstallTest(unittest.TestCase):
    def setUp(self):
        self.m = load_server()
        self.tmp = tempfile.TemporaryDirectory(prefix='fnm-prepare-')
        self.controller = self.m.DisplayController(system_root=self.tmp.name)
        self.controller.cleanup_data_dir = self.tmp.name
        self.controller.port = 18877
        self.controller._describe = lambda: {'control_requires_login': False}
        self.child = Path(self.tmp.name)/'cleanup.py'
        self.real_popen = subprocess.Popen
        self.spawned = []

    def tearDown(self):
        self.tmp.cleanup()

    def spawn(self, argv, **kwargs):
        self.spawned.append((argv, kwargs))
        return self.real_popen([sys.executable, '-u', str(self.child), *argv[-2:]], **kwargs)

    def wait_job(self):
        for _ in range(200):
            if self.controller.job()['state'] != 'running':
                return self.controller.job()
            time.sleep(.01)
        self.fail('cleanup job did not finish')

    def test_background_cleanup_streams_progress_keeps_server_alive_and_allows_retry(self):
        self.child.write_text('import os,sys,time\nassert os.environ["TRIM_PKGVAR"] == '+repr(self.tmp.name)+'\nassert sys.argv[-2:]==["--port","18877"]\nprint("[阶段] 清除显示自启",flush=True)\ntime.sleep(.3)\nprint("fixture cleanup complete",flush=True)\n')
        history=Path(self.tmp.name)/'monitor.db';history.write_text('keep history')
        with patch.object(self.m.subprocess,'Popen',side_effect=self.spawn):
            self.assertTrue(self.controller.start_job('prepare_uninstall')[0])
            for _ in range(100):
                if self.controller.job()['lines']:break
                time.sleep(.01)
            self.assertEqual(self.controller.job()['state'],'running')
            self.assertEqual(self.controller.job()['stage'],'清除显示自启')
            self.assertFalse(self.controller.start_job('install_hdmi')[0])
            result=self.wait_job()
            self.assertEqual(result['state'],'done')
            self.assertIn('现在请到飞牛应用商店卸载',result['message'])
            self.assertEqual(history.read_text(),'keep history')
            self.assertTrue(self.spawned[0][0][3].endswith('/uninstall_display.py'))
            self.assertTrue(self.spawned[0][1]['start_new_session'])
            self.assertNotIn('stop', self.spawned[0][0])
            self.assertTrue(self.controller.start_job('prepare_uninstall')[0])
            self.assertEqual(self.wait_job()['state'],'done')

    def test_failure_is_not_reported_as_done_and_retains_diagnostics(self):
        self.child.write_text('import sys\nprint("[阶段] 返回命令行",flush=True)\nprint("fixture chvt failed",flush=True)\nsys.exit(1)\n')
        with patch.object(self.m.subprocess,'Popen',side_effect=self.spawn):
            self.assertTrue(self.controller.start_job('prepare_uninstall')[0])
            result=self.wait_job()
        self.assertEqual(result['state'],'error')
        self.assertIn('请勿继续在应用商店卸载',result['message'])
        self.assertIn('fixture chvt failed',result['lines'])
        self.assertFalse(self.controller._action_lock.locked())

    def test_synchronous_request_cannot_block_http_worker(self):
        app=types.SimpleNamespace(display_controller=self.controller)
        self.assertFalse(self.m.MonitorApp.api_display_action(app,'prepare_uninstall',False)[0])
        self.assertIsNone(self.controller.job())


class CleanupHttpTest(unittest.TestCase):
    def test_no_auth_no_csrf_no_sync_execution(self):
        server=ServerProcess()
        try:
            server.start()
            headers={'Content-Type':'application/json','X-FNM-Request':'1'}
            body=json.dumps({'action':'prepare_uninstall','background':True})
            status, *rest=server.request('POST','/api/display/action',body,headers)
            self.assertEqual(status,403)  # Password protection must be enabled first.
            generated = dict(zip(['password'], [secrets.token_urlsafe(24)]))
            status, _, response, _=server.request('POST','/api/auth/setup',json.dumps(generated),headers)
            self.assertEqual(status,200)
            cookie=response.getheader('Set-Cookie').split(';')[0]
            status, *rest=server.request('POST','/api/display/action',body,headers)
            self.assertEqual(status,401)  # No authenticated cookie.
            status, *rest=server.request('POST','/api/display/action',body,{'Content-Type':'application/json'})
            self.assertEqual(status,403)
            # Exercise the real HTTP route + controller + child process, with an
            # inert cleanup fixture in the disposable package (never host cleanup).
            fixture=Path(server.pkg)/'app/uninstall_display.py'
            fixture.write_text('import os,time\nassert os.environ["TRIM_PKGVAR"] == '+repr(server.data)+'\nprint("[阶段] fixture cleanup",flush=True)\ntime.sleep(.2)\nprint("fixture complete",flush=True)\n')
            authenticated=dict(headers,Cookie=cookie)
            status, *rest=server.request('POST','/api/display/action',json.dumps({'action':'prepare_uninstall'}),authenticated)
            self.assertEqual(status,400)
            status, j, *_=server.request('POST','/api/display/action',body,authenticated)
            self.assertEqual(status,200)
            self.assertTrue(j['ok'])
            for _ in range(100):
                status, j, *_=server.request('GET','/api/display/status',headers=authenticated)
                if j['job']['state']!='running':break
                time.sleep(.02)
            self.assertEqual(j['job']['state'],'done')
            self.assertIn('fixture complete',j['job']['lines'])
            self.assertEqual(server.request('GET','/launcher.html',headers=authenticated)[0],200)
            self.assertTrue((Path(server.data)/'config.json').exists())
        finally:
            server.stop()


if __name__=='__main__':unittest.main()
