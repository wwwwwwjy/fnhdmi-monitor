import subprocess
import re
from pathlib import Path
import unittest
from unittest.mock import patch
from test_display_fit import m

RAW=(Path(__file__).parent/'fixtures/randr-dp3.txt').read_text()
class ModesTest(unittest.TestCase):
    def setUp(self):self.mode='1366x768';self.size='1366 x 768';self.calls=[];self.reject=False
    def query(self):
        raw=RAW.replace('current 1366 x 768','current '+self.size).replace('DP-3 connected 1366x768+0+0','DP-3 connected '+self.mode+'+0+0').replace('59.96*+','59.96+')
        if self.mode=='1366x768':raw=raw.replace('59.96+','59.96*+')
        else:raw=re.sub(r'(?m)^(\s+'+re.escape(self.mode)+r'\s+60[.]00)',lambda match:match[1]+'*',raw)
        return raw
    def command(self,args,**kw):
        self.calls.append(args)
        if args[-1]=='--query':return subprocess.CompletedProcess(args,0,self.query(),'')
        mode=args[args.index('--mode')+1]
        if self.reject and mode=='1920x1080':return subprocess.CompletedProcess(args,1,'','fixture mode rejected')
        self.mode=mode;self.size=args[-1].replace('x',' x ')
        return subprocess.CompletedProcess(args,0,'','')
    def apply(self,choice='auto'):
        with patch.object(m.shutil,'which',return_value='/usr/bin/xrandr'):return m.change_mode(choice,self.command)
    def test_real_report_disconnected_primary_ignored_and_dp3_1080p_selected(self):
        state=m.randr_state(RAW);self.assertEqual(len(state['outputs']),1)
        self.assertEqual(state['outputs'][0]['name'],'DP-3')
        result,restore=self.apply();self.assertEqual(result['mode'],'1920x1080');self.assertEqual(self.size,'1920 x 1080')
        self.assertTrue(all('DP-1' not in c for c in self.calls))
        restore();self.assertEqual(self.mode,'1366x768');self.assertEqual(self.size,'1366 x 768')
    def test_automatic_fallback_after_1080_failure(self):
        self.reject=True;result,_=self.apply();self.assertEqual(result['mode'],'1280x720')
        self.assertTrue(any('1366x768' in c for c in self.calls))
    def test_explicit_720_and_no_repeated_mode_changes(self):
        self.apply('1280x720');self.calls=[];result,_=self.apply('1280x720');self.assertFalse(result['mode_changed'])
        self.assertFalse(any('--output' in c for c in self.calls))
    def test_explicit_1080_failure_restores_original_without_silent_fallback(self):
        self.reject=True
        with self.assertRaisesRegex(RuntimeError,'fixture mode rejected'):self.apply('1920x1080')
        self.assertEqual(self.mode,'1366x768')
    def test_multimonitor_and_unsupported_modes_do_not_mutate(self):
        for raw in (RAW+'HDMI-2 connected 1280x720+1366+0\n   1280x720 60.00*\n',RAW.replace('1920x1080','1920x1200').replace('1280x720','1280x800')):
            with self.subTest(raw=raw[:30]),patch.object(m.shutil,'which',return_value='/usr/bin/xrandr'):
                calls=[]
                def run(args,**kw):calls.append(args);return subprocess.CompletedProcess(args,0,raw,'')
                with self.assertRaises(RuntimeError):m.change_mode('auto',run)
                self.assertTrue(all(c[-1]=='--query' for c in calls))

if __name__=='__main__':unittest.main()
