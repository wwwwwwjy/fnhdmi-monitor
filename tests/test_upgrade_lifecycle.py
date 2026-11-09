"""Exercise real old hooks, rescue and explicit fnOS operation contexts."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upgrade_rescue',ROOT/'tools/unblock_upgrade.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class UpgradeLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='fnm-upgrade-rescue-')
        self.base=Path(self.tmp.name);self.cmd=self.base/'cmd';self.cmd.mkdir()
        self.app=self.base/'target';self.app.mkdir();self.data=self.base/'var';self.data.mkdir()
        (self.base/'manifest').write_text('appname = fnmonitor\nversion = 3.0.2\ndisplay_name = 飞牛HDMI动态监控\n')
        (self.data/'monitor.db').write_bytes(b'preserve historical data')
        self.original={}
        for name in ('uninstall_init','uninstall_callback'):
            data=(ROOT/'tests/fixtures/upgrade_hooks'/name).read_bytes()
            self.original[name]=data;(self.cmd/name).write_bytes(data);(self.cmd/name).chmod(0o755)
        (self.cmd/'main').write_text('#!/bin/sh\necho stop >> "${TRIM_PKGVAR}/events"\n');(self.cmd/'main').chmod(0o755)
        (self.app/'uninstall_display.py').write_text('from pathlib import Path\nimport os\n(Path(os.environ["TRIM_PKGVAR"])/"cleanup-called").touch()\nraise SystemExit(1)\n')
        self.env={k:v for k,v in os.environ.items() if not k.startswith('TRIM_')}
        self.env.update(TRIM_APPDEST=str(self.app),TRIM_PKGVAR=str(self.data),TRIM_TEMP_LOGFILE=str(self.base/'error'),wizard_delete_data='true')
    def tearDown(self):self.tmp.cleanup()
    def run_hook(self,name,**environment):
        return subprocess.run(['bash',str(self.cmd/name)],env=dict(self.env,**environment),capture_output=True,text=True)
    def new_hooks(self):
        for name in self.original:shutil.copy2(ROOT/'cmd'/name,self.cmd/name)
    def assert_intact(self):
        self.assertEqual((self.data/'monitor.db').read_bytes(),b'preserve historical data')
    def test_old_uninstall_hook_reproduces_upgrade_block(self):
        p=self.run_hook('uninstall_init',TRIM_APP_STATUS='UPGRADE')
        self.assertEqual(p.returncode,1)
        self.assertTrue((self.data/'cleanup-called').exists())
    def test_new_hooks_preserve_environment_and_data_for_upgrade_and_unknown_contexts(self):
        self.new_hooks()
        for context in ({'TRIM_APP_STATUS':'UPGRADE'},{'TRIM_APP_STATUS':'INSTALL'},{},
                        {'TRIM_APP_STATUS':'UNINSTALL','TRIM_OLD_APPVER':'3.0.2'},
                        {'TRIM_APP_STATUS':'UNINSTALL','TRIM_TEMP_UPGRADE_FOLDER':'/tmp/upgrade'}):
            with self.subTest(context=context):
                for name in self.original:
                    p=self.run_hook(name,**context);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assert_intact()
                self.assertFalse((self.data/'events').exists())
                self.assertFalse((self.data/'cleanup-called').exists())
    def test_explicit_uninstall_still_runs_cleanup_and_honors_delete_choice(self):
        self.new_hooks()
        p=self.run_hook('uninstall_init',TRIM_APP_STATUS='UNINSTALL')
        self.assertEqual(p.returncode,1)
        self.assertTrue((self.data/'cleanup-called').exists())
        self.assert_intact()
        (self.app/'uninstall_display.py').write_text('print("fixture cleaned")\n')
        self.assertEqual(self.run_hook('uninstall_init',TRIM_APP_STATUS='UNINSTALL').returncode,0)
        self.assertEqual(self.run_hook('uninstall_callback',TRIM_APP_STATUS='UNINSTALL',wizard_delete_data='false').returncode,0)
        self.assert_intact()
        self.assertEqual(self.run_hook('uninstall_callback',TRIM_APP_STATUS='UNINSTALL').returncode,0)
        self.assertFalse((self.data/'monitor.db').exists())
    def test_rescue_backups_and_unblocks_old_hooks_without_touching_data(self):
        r.repair(self.base);r.repair(self.base)
        for name,data in self.original.items():
            self.assertEqual((self.data/'.upgrade-unblock-304'/(name+'.original')).read_bytes(),data)
            self.assertEqual(self.run_hook(name,TRIM_APP_STATUS='UPGRADE').returncode,0)
        self.assert_intact();self.assertFalse((self.data/'events').exists())
        self.assertFalse((self.data/'cleanup-called').exists())
    def test_unrecognized_script_and_symlink_refused_without_overwrite(self):
        path=self.cmd/'uninstall_init';path.write_text('custom user script')
        with self.assertRaisesRegex(RuntimeError,'不是已核对'):r.repair(self.base)
        self.assertEqual((self.cmd/'uninstall_callback').read_bytes(),self.original['uninstall_callback'])
        path.unlink();path.symlink_to(self.data/'monitor.db')
        with self.assertRaisesRegex(RuntimeError,'类型异常'):r.repair(self.base)
        self.assert_intact()
    def test_partial_write_failure_rolls_back_both_hooks(self):
        real=r.atomic
        def fail(path,data,*args):
            if path==self.cmd/'uninstall_init' and data==r.STUB:raise OSError('fixture write failure')
            return real(path,data,*args)
        with patch.object(r,'atomic',side_effect=fail):
            with self.assertRaisesRegex(OSError,'fixture write failure'):r.repair(self.base)
        for name,data in self.original.items():self.assertEqual((self.cmd/name).read_bytes(),data)
        self.assert_intact()

if __name__=='__main__':unittest.main()
