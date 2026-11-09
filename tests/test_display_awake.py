import ctypes as C
import types
import unittest
from unittest.mock import patch
from test_display_fit import m

class Function:
    def __init__(self,call):self.call=call
    def __call__(self,*args):return self.call(*args)

class Native:
    def __init__(self,extension=True,capable=True,ignore_disable=False):
        self.saver=600;self.cycle=600;self.blanked=True;self.enabled=True;self.level=3;self.timers=[600,600,600]
        self.extension=extension;self.capable=capable;self.ignore_disable=ignore_disable
        for name in ('XForceScreenSaver','XSetScreenSaver','XGetScreenSaver','XQueryExtension','XSync','DPMSCapable','DPMSDisable','DPMSSetTimeouts','DPMSInfo','DPMSGetTimeouts'):
            setattr(self,name,Function(getattr(self,name)))
    def XForceScreenSaver(self,d,mode):
        assert mode==0;self.blanked=False;return 1
    def XSetScreenSaver(self,d,timeout,interval,blank,exposures):self.saver=timeout;self.cycle=interval;return 1
    def XGetScreenSaver(self,d,timeout,interval,blank,exposures):timeout._obj.value=self.saver;interval._obj.value=self.cycle;return 1
    def XQueryExtension(self,*args):return self.extension
    def XSync(self,*args):return 1
    def DPMSCapable(self,d):return self.capable
    def DPMSDisable(self,d):
        if not self.ignore_disable:self.enabled=False;self.level=0
        return 1
    def DPMSSetTimeouts(self,d,*values):self.timers=list(values);return 1
    def DPMSInfo(self,d,level,enabled):level._obj.value=self.level;enabled._obj.value=self.enabled;return 1
    def DPMSGetTimeouts(self,d,*values):
        for ptr,v in zip(values,self.timers):ptr._obj.value=v
        return 1

class AwakeTest(unittest.TestCase):
    def make(self,**kwargs):
        n=Native(**kwargs);x=object.__new__(m.X11);x.x=n;x.d=None;x.errors=[];return x,n
    def test_wakes_blanked_display_disables_saver_and_dpms_idempotently(self):
        x,n=self.make()
        with patch.object(m.C,'CDLL',return_value=n):
            for _ in range(2):self.assertEqual(x.keep_awake(),{'screen_saver_timeout':0,'dpms':'disabled'})
        self.assertFalse(n.blanked);self.assertFalse(n.enabled);self.assertEqual(n.level,0);self.assertEqual(n.timers,[0,0,0]);self.assertEqual(n.saver,0)
    def test_no_dpms_extension_or_incapable_server_still_disables_saver(self):
        for kw in ({'extension':False},{'capable':False}):
            x,n=self.make(**kw)
            with patch.object(m.C,'CDLL',return_value=n) as library:
                self.assertEqual(x.keep_awake()['dpms'],'unsupported')
                if not n.extension:library.assert_not_called()
            self.assertEqual(n.saver,0);self.assertFalse(n.blanked)
    def test_readback_failure_does_not_claim_display_is_awake(self):
        x,n=self.make(ignore_disable=True)
        with patch.object(m.C,'CDLL',return_value=n):
            with self.assertRaisesRegex(RuntimeError,'显示休眠关闭未确认'):x.keep_awake()
        x,n=self.make();x.errors=['fixture protocol error']
        with self.assertRaisesRegex(RuntimeError,'屏保关闭未确认'):x.keep_awake()
    def test_keep_awake_runs_before_resolution_change_and_closes_session(self):
        x,n=self.make(extension=False);x.close=types.SimpleNamespace() # replaced below
        from unittest.mock import Mock
        x.close=Mock()
        with patch.object(m,'sessions',return_value=(123,1000,{'DISPLAY':':0'})),patch.object(m.os,'geteuid',return_value=1000),patch.object(m.pwd,'getpwuid',return_value=types.SimpleNamespace(pw_dir='/tmp',pw_gid=1000)),patch.dict(m.os.environ),patch.object(m,'X11',return_value=x),patch.object(m,'change_mode',side_effect=RuntimeError('unsupported mode')):
            with self.assertRaisesRegex(RuntimeError,'unsupported mode'):m.main(8777)
        self.assertEqual(n.saver,0);x.close.assert_called_once()

if __name__=='__main__':unittest.main()
