import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
from fnm_support import load_server
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('display_fit',ROOT/'app/display_fit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class FakeX(m.X11):
    def __init__(self):
        self.root=0;self.d=None;self.errors=[];self.calls=[]
        self.rects={0:(0,0,1920,1080),1:(16,16,1400,900),2:(100,100,900,700),3:(0,0,1600,1000)}
        self.x=types.SimpleNamespace(XSync=lambda *a:0,XSetWindowBorderWidth=lambda *a:0,XMoveResizeWindow=self.move)
        self.hidden={3};self.pids={1:123,2:999,3:123};self.screens=[]
    def children(self,w):return [1,2,3] if w==0 else []
    def prop(self,w,n):return [self.pids[w]]
    def geometry(self,w):return self.rects[w]
    def monitors(self):return self.screens
    def visible(self,w):return w not in self.hidden
    def move(self,d,w,x,y,width,height):self.calls.append(w);self.rects[w]=(x,y,width,height)

class FitTest(unittest.TestCase):
    def test_black_unused_desktop_filled_without_touching_other_or_hidden_windows(self):
        x=FakeX();result=x.fit(123)
        self.assertEqual(x.rects[1],(0,0,1920,1080));self.assertEqual(x.calls,[1]);self.assertTrue(result['changed'])
        self.assertEqual(x.rects[2],(100,100,900,700));self.assertEqual(x.rects[3],(0,0,1600,1000))
        self.assertFalse(x.fit(123)['changed']);self.assertEqual(x.calls,[1])
    def test_monitor_resolution_changes_and_portrait_primary(self):
        x=FakeX();x.fit(123);x.screens=[dict(x=1920,y=0,width=1080,height=1920,primary=True)]
        self.assertEqual(x.fit(123)['height'],1920);self.assertEqual(x.rects[1],(1920,0,1080,1920))
    def test_no_browser_or_failed_resize_never_claim_success(self):
        x=FakeX()
        with self.assertRaisesRegex(RuntimeError,'尚未找到'):x.fit(555)
        x.x.XMoveResizeWindow=lambda *a:None
        with self.assertRaisesRegex(RuntimeError,'尚未确认'):x.fit(123)
    def test_custom_window_manager_not_resized(self):
        x=FakeX();x.children=lambda w:[9] if w==0 else [1] if w==9 else []
        x.pids[9]=999;x.rects[9]=(0,0,1500,1000)
        with self.assertRaisesRegex(RuntimeError,'自定义窗口管理器'):x.fit(123)
        self.assertEqual(x.calls,[])
    def test_process_selection_rejects_unrelated_ports_and_remote_displays(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            def proc(pid,url,display):
                p=root/str(pid);p.mkdir();(p/'cmdline').write_bytes(('/usr/bin/chromium\0--kiosk\0'+url+'\0').encode())
                (p/'status').write_text('Uid: 1000 1000 1000 1000\n');(p/'environ').write_bytes(('DISPLAY='+display+'\0').encode())
            proc(1,'http://127.0.0.1:8777/',':0');proc(2,'http://127.0.0.1:9999/',':1');proc(3,'http://127.0.0.1:8777/','otherhost:0')
            self.assertEqual(m.sessions(8777,root)[0],1)
            proc(4,'http://127.0.0.1:8777/',':0')
            with self.assertRaisesRegex(RuntimeError,'唯一'):m.sessions(8777,root)
    def test_auto_fit_throttles_and_respects_cleanup_lock(self):
        controller=load_server().DisplayController()
        result=subprocess.CompletedProcess([],0,json.dumps(dict(ok=True,width=1920,height=1080)),'')
        with patch.object(controller,'_run_command',return_value=result) as run:
            self.assertTrue(controller.auto_fit_window()['ok']);controller.auto_fit_window();self.assertEqual(run.call_count,1)
            controller._fit_at=0;controller._action_lock.acquire()
            try:controller.auto_fit_window();self.assertEqual(run.call_count,1)
            finally:controller._action_lock.release()
    def test_timeout_or_bad_native_output_is_reported_without_breaking_scene(self):
        controller=load_server().DisplayController()
        with patch.object(controller,'_run_command',return_value=subprocess.CompletedProcess([],1,'','fixture timeout')):
            self.assertFalse(controller.auto_fit_window()['ok']);self.assertIn('fixture timeout',controller._fit_result['message'])

if __name__=='__main__':unittest.main()
