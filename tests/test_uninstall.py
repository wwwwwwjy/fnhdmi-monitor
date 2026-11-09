"""Exercise uninstall against a disposable NAS filesystem and command ledger."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FNM_UNINSTALL_PACKAGE_ROOT') or Path(__file__).resolve().parents[1])
spec = importlib.util.spec_from_file_location('uninstall_display', ROOT/'app/uninstall_display.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fnm-uninstall-')
        self.root = Path(self.tmp.name)
        self.calls = []
        self.packages = {'python3', 'other-app', 'xinit', 'chromium', 'x11vnc', 'libshared'}
        self.shared = False
        self.fail_purge = False
        self.fail_stop = False
        self.reuse = False
        self.put('/etc/passwd', 'fixtureuser:x:1000:1000::/home/fixtureuser:/bin/bash\n')
        self.put('/sys/class/tty/tty0/active', 'tty4\n')
        self.put('/home/fixtureuser/.bash_profile', 'export KEEP=yes\n'+m.START+'\nstartx -- :0 vt4\n'+m.END+'\n')
        self.put('/home/fixtureuser/.xinitrc', '#!/bin/sh\nexec chromium --kiosk http://127.0.0.1:8777/\n')
        self.put('/home/fixtureuser/.bash_profile.fnmonitor-control.bak', 'old kiosk setup')
        self.put('/home/fixtureuser/.xinitrc.fnmonitor-uninstall.bak.1', 'old kiosk setup')
        self.put('/home/fixtureuser/.vnc/passwd', 'existing personal password')
        self.put('/etc/systemd/system/getty@tty1.service.d/override.conf', '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin fixtureuser --noclear %I $TERM\n')
        self.put('/etc/systemd/system/fnmonitor-browser-vnc@.service', 'app vnc template')
        self.put('/etc/systemd/system/fnmonitor-browser-vnc@.service.d/custom.conf', '[Service]\nRestart=no\n')
        self.put('/etc/systemd/system/getty@tty2.service.d/other.conf', '[Service]\nEnvironment=KEEP=1\n')
        for name in ('/etc/fnmonitor-hdmi.enabled', '/etc/fnmonitor-hdmi.uninstalled', '/run/fnmonitor-hdmi.on', '/run/fnmonitor-hdmi.off'):
            self.put(name, '')
        (self.root/'run/fnmonitor-browser-vnc').mkdir()
        self.process(10, 1, ['/usr/bin/xinit', '/home/fixtureuser/.xinitrc'])
        self.process(11, 10, ['/usr/lib/xorg/Xorg', ':0', 'vt4'])
        self.process(12, 10, ['/usr/bin/chromium', '--kiosk', 'http://127.0.0.1:8777/'])
        self.process(13, 12, ['/usr/bin/chromium', '--type=renderer'])
        self.process(90, 1, ['/usr/sbin/sshd', 'fixtureuser'])
        self.process(91, 90, ['/bin/bash'])
        self.process(92, 1, ['/usr/bin/chromium', '--kiosk', 'http://127.0.0.1:9999/'])
        self.put('/proc/92/environ','DISPLAY=:1\0')
        self.process(93, 1, ['/usr/lib/xorg/Xorg', ':1', 'vt5'])
        self.cleaner = m.Cleanup(self.root, self.command, sleep=lambda _: None)
        self.cleaner.resources.write('hdmi', {'packages': ['xinit', 'chromium', 'libshared'], 'account_preexisting': True})
        self.cleaner.resources.write('vnc', {'packages': ['x11vnc']})

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        p = self.root/name.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def process(self, pid, ppid, args, birth='123'):
        fields = ['S', str(ppid)] + ['0']*17 + [birth]
        self.put('/proc/%d/stat'%pid, '%d (process) '%pid+' '.join(fields))
        self.put('/proc/%d/status'%pid, 'Uid:\t1000\t1000\t1000\t1000\n')
        self.put('/proc/%d/cmdline'%pid, '\0'.join(args)+'\0')
        self.put('/proc/%d/environ'%pid, 'DISPLAY=:0\0')

    def command(self, args, **kwargs):
        self.calls.append(list(args))
        out, code = '', 0
        if args[0] == 'kill':
            pid=int(args[-1])
            if self.reuse and pid == 12:
                self.process(12, 1, ['/usr/sbin/unrelated'], birth='456')
            elif not self.fail_stop:
                shutil.rmtree(self.root/'proc'/str(pid), ignore_errors=True)
        elif args[:2] in (['systemctl', 'list-units'], ['systemctl', 'list-unit-files']):
            out='fnmonitor-browser-vnc@fixtureuser.service enabled\nfnmonitor-x11vnc@fixtureuser.service disabled\nssh.service enabled\n'
        elif args[:2] == ['systemctl', 'is-active']:
            code=3;out='inactive\n'
        elif args[0] == 'chvt':
            self.put('/sys/class/tty/tty0/active', 'tty1\n')
        elif args[0] == 'dpkg-query':
            out=''.join(p+' installed\n' for p in self.packages)
        elif args[0] == 'apt-get':
            packages=set(args[args.index('purge')+1:])
            if '-s' in args:
                removed=packages | ({'other-app'} if self.shared and 'libshared' in packages else set())
                out=''.join('Purg '+p+'\n' for p in removed)
            elif self.fail_purge:
                code=1;out='package manager busy'
            else:
                self.packages-=packages
        return subprocess.CompletedProcess(args, code, out, '')

    def test_full_uninstall_stops_tty4_and_preserves_ssh_data_and_other_display(self):
        database=self.put('/data/monitor.db', 'history stays')
        self.cleaner.run()
        for pid in (10, 11, 12, 13):self.assertFalse((self.root/'proc'/str(pid)).exists())
        for pid in (90, 91, 92, 93):self.assertTrue((self.root/'proc'/str(pid)).exists())
        self.assertEqual((self.root/'home/fixtureuser/.bash_profile').read_text(), 'export KEEP=yes\n')
        self.assertTrue((self.root/'home/fixtureuser/.vnc/passwd').exists())
        self.assertTrue((self.root/'etc/systemd/system/getty@tty2.service.d/other.conf').exists())
        self.assertEqual(database.read_text(), 'history stays')
        self.assertFalse((self.root/'home/fixtureuser/.xinitrc').exists())
        self.assertFalse(list((self.root/'home/fixtureuser').glob('*.fnmonitor-*')))
        self.assertFalse((self.root/'etc/systemd/system/getty@tty1.service.d').exists())
        self.assertFalse(self.cleaner.resources.ROOT.exists())
        self.assertFalse((self.root/'etc/systemd/system/fnmonitor-browser-vnc@.service.d').exists())
        self.assertEqual(self.packages, {'python3', 'other-app'})
        self.assertEqual((self.root/'sys/class/tty/tty0/active').read_text().strip(), 'tty1')
        purge=next(i for i,c in enumerate(self.calls) if c[0]=='apt-get' and '-s' not in c)
        self.assertLess(self.calls.index(['chvt', '1']), purge)
        self.assertFalse(any(c[0] in ('pkill', 'loginctl') or 'autoremove' in c for c in self.calls))
        self.cleaner.run()  # Safe to retry after a completed pre-uninstall hook.

    def test_shared_dependency_retained_without_retaining_independent_packages(self):
        self.shared=True
        self.cleaner.run()
        self.assertEqual(self.packages, {'python3', 'other-app', 'libshared'})
        self.assertFalse(self.cleaner.resources.ROOT.exists())

    def test_fnOS_unit_file_enumeration_failure_is_avoided(self):
        original=self.command
        def command(args,**kw):
            if args[:2]==['systemctl','list-unit-files']:
                raise AssertionError('fnOS list-unit-files exits 1 without output')
            return original(args,**kw)
        self.cleaner.runner=command
        self.cleaner.run()
        self.assertIn(['systemctl','stop','fnmonitor-browser-vnc@fixtureuser.service'],self.calls)
        self.assertFalse(self.cleaner.resources.ROOT.exists())

    def test_unloaded_and_dangling_enablement_links_in_etc_and_run_are_removed(self):
        original=self.command
        # The running list is empty; these instances exist only on disk.
        def command(args,**kw):
            if args[:2]==['systemctl','list-units']:
                self.calls.append(args)
                return subprocess.CompletedProcess(args,0,'','')
            if args[:2]==['systemctl','is-active']:
                self.calls.append(args)
                return subprocess.CompletedProcess(args,4,'unknown\n','')
            if args[:2] in (['systemctl','disable'],['systemctl','stop']):
                raise AssertionError('already missing instance must not require stop/disable')
            return original(args,**kw)
        self.cleaner.runner=command
        owned=[];unrelated=[]
        for base in ('etc','run'):
            for suffix in ('wants','requires','upholds'):
                folder=self.root/base/'systemd/system'/('multi-user.target.'+suffix)
                folder.mkdir(parents=True,exist_ok=True)
                link=folder/'fnmonitor-browser-vnc@stale.service';link.symlink_to('../fnmonitor-browser-vnc@.service');owned.append(link)
                link=folder/'other-app.service';link.symlink_to('../other-app.service');unrelated.append(link)
        self.put('/run/systemd/system/fnmonitor-x11vnc@.service','old runtime template')
        self.cleaner.run()
        self.assertTrue(all(not p.is_symlink() for p in owned))
        self.assertTrue(all(p.is_symlink() for p in unrelated))
        self.assertFalse((self.root/'run/systemd/system/fnmonitor-x11vnc@.service').exists())

    def test_systemd_bus_failure_is_not_ignored_and_preserves_receipts(self):
        original=self.command
        def command(args,**kw):
            if args[:2]==['systemctl','list-units']:
                return subprocess.CompletedProcess(args,1,'','Failed to connect to bus')
            return original(args,**kw)
        self.cleaner.runner=command
        with self.assertRaisesRegex(RuntimeError,'退出码 1.*Failed to connect to bus'):
            self.cleaner.run()
        self.assertTrue(self.cleaner.resources.read('hdmi'))
        self.assertTrue((self.root/'etc/systemd/system/fnmonitor-browser-vnc@.service').exists())
        # Like the user's failed run, other stages have already removed the
        # login block and stopped the desktop. Retry must finish from that state.
        self.cleaner.runner=original
        self.cleaner.errors=[]
        self.cleaner.run()
        self.assertFalse(self.cleaner.resources.ROOT.exists())
        self.assertFalse((self.root/'etc/systemd/system/fnmonitor-browser-vnc@.service').exists())

    def test_service_still_active_blocks_file_and_dependency_removal(self):
        original=self.command
        def command(args,**kw):
            if args[:2]==['systemctl','is-active']:
                return subprocess.CompletedProcess(args,0,'active\n','')
            return original(args,**kw)
        self.cleaner.runner=command
        with self.assertRaisesRegex(RuntimeError,'is-active.*退出码 0.*active'):
            self.cleaner.run()
        self.assertTrue(self.cleaner.resources.read('vnc'))
        self.assertTrue((self.root/'etc/systemd/system/fnmonitor-browser-vnc@.service').exists())

    def test_empty_command_failure_includes_full_command_and_exit_code(self):
        self.cleaner.runner=lambda args,**kw:subprocess.CompletedProcess(args,7,'','')
        with self.assertRaisesRegex(RuntimeError,'list-units --all --no-pager.*退出码 7.*无标准输出'):
            self.cleaner.command(['systemctl','list-units','--all','--no-pager'])

    def test_app_store_retry_after_button_does_not_require_purged_chvt(self):
        self.cleaner.run()
        original=self.command
        def command(args,**kw):
            if args[0]=='chvt':raise FileNotFoundError('chvt was purged with owned kbd')
            return original(args,**kw)
        self.cleaner.runner=command
        self.cleaner.run()
        self.assertEqual((self.root/'sys/class/tty/tty0/active').read_text().strip(),'tty1')

    def test_purge_failure_keeps_receipts_and_retry_completes(self):
        self.fail_purge=True
        with self.assertRaises(RuntimeError):self.cleaner.run()
        self.assertTrue(self.cleaner.resources.read('hdmi'))
        self.fail_purge=False
        self.cleaner.run()
        self.assertFalse(self.cleaner.resources.ROOT.exists())

    def test_live_graphics_failure_blocks_dependency_removal(self):
        self.fail_stop=True
        with self.assertRaisesRegex(RuntimeError, '图形进程仍在运行'):self.cleaner.run()
        self.assertTrue(self.cleaner.resources.read('hdmi'))
        self.assertFalse(any(c[0]=='apt-get' for c in self.calls))

    def test_pid_reuse_does_not_kill_replacement_process(self):
        self.reuse=True
        self.cleaner.run()
        self.assertTrue((self.root/'proc/12').exists())
        self.assertNotIn(['kill', '-KILL', '12'], self.calls)

    def test_old_uninstall_without_receipts_still_removes_live_graphics(self):
        shutil.rmtree(self.cleaner.resources.ROOT)
        self.put('/home/fixtureuser/.bash_profile', 'export KEEP=yes\n')
        self.cleaner.run()
        self.assertFalse((self.root/'proc/11').exists())
        self.assertFalse((self.root/'etc/systemd/system/getty@tty1.service.d/override.conf').exists())
        self.assertIn('chromium', self.packages)  # No ownership record: not blindly purged.

    def test_broken_marker_and_symlink_leave_app_installed(self):
        self.put('/home/fixtureuser/.bash_profile', m.START+'\nstartx\n')
        with self.assertRaisesRegex(RuntimeError, '标记不完整'):self.cleaner.run()
        self.assertTrue(self.cleaner.resources.read('hdmi'))

    def test_symlink_does_not_delete_target(self):
        p=self.root/'home/fixtureuser/.xinitrc'
        p.unlink()
        target=self.put('/unrelated-script', 'keep me')
        p.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, '符号链接'):self.cleaner.run()
        self.assertEqual(target.read_text(), 'keep me')

    def test_dedicated_account_and_owned_home_removed(self):
        self.cleaner.resources.write('hdmi', {'packages': [], 'account_preexisting': False})
        home=self.put('/var/lib/fnmonitor-kiosk/.config/chromium/cache', 'owned browser cache').parents[2]
        record=types.SimpleNamespace(pw_dir='/var/lib/fnmonitor-kiosk', pw_uid=999)
        with patch.object(self.cleaner.resources.pwd,'getpwnam',return_value=record):self.cleaner.run()
        self.assertIn(['userdel','--remove','fnmkiosk'], self.calls)
        self.assertFalse((self.root/'var/lib/fnmonitor-kiosk').exists())

    def test_invalid_receipt_package_cannot_be_an_apt_option(self):
        self.cleaner.resources.write('vnc', {'packages': ['--allow-remove-essential']})
        with self.assertRaisesRegex(RuntimeError, '无效包名'):self.cleaner.resources.uninstall_all()
        self.assertFalse(any(c[0]=='apt-get' for c in self.calls))

    def test_owned_stale_x_socket_and_lock_removed(self):
        self.put('/tmp/.X0-lock','11\n')
        folder=self.root/'tmp/.X11-unix';folder.mkdir()
        # Bind without listening: a leftover X socket cannot accept clients.
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            sock.bind(str(folder/'X0'))
            self.cleaner.run()
            self.assertFalse((folder/'X0').exists())
            self.assertFalse((self.root/'tmp/.X0-lock').exists())
            self.assertTrue((self.root/'proc/93').exists())
        finally:sock.close()

    def test_configuration_only_packages_are_purged(self):
        original=self.command
        def command(args,**kw):
            result=original(args,**kw)
            if args[0]=='dpkg-query':
                result.stdout=result.stdout.replace('x11vnc installed','x11vnc config-files')
            return result
        self.cleaner.runner=command
        self.cleaner.run()
        self.assertNotIn('x11vnc',self.packages)

    def test_unrelated_users_symlinked_profile_is_not_touched(self):
        with (self.root/'etc/passwd').open('a') as f:f.write('other:x:1001:1001::/home/other:/bin/bash\n')
        target=self.put('/other-login','export OTHER=yes\n')
        home=self.root/'home/other';home.mkdir()
        (home/'.bash_profile').symlink_to(target)
        self.cleaner.run()
        self.assertEqual(target.read_text(),'export OTHER=yes\n')


class HookTest(unittest.TestCase):
    def test_actual_hook_surfaces_failure_and_allows_retry_without_data_loss(self):
        with tempfile.TemporaryDirectory(prefix='fnm-hook-') as td:
            root=Path(td);cmd=root/'cmd';cmd.mkdir();app=root/'app';app.mkdir();data=root/'data';data.mkdir()
            shutil.copy2(ROOT/'cmd/uninstall_init',cmd/'uninstall_init')
            (cmd/'main').write_text('#!/bin/sh\nexit 0\n');(cmd/'main').chmod(0o755)
            (data/'monitor.db').write_text('preserve history')
            env={k:v for k,v in os.environ.items() if not k.startswith('TRIM_')}
            env.update(TRIM_APPDEST=str(app),TRIM_PKGVAR=str(data),TRIM_TEMP_LOGFILE=str(root/'error'),TRIM_APP_STATUS='UNINSTALL')
            script=app/'uninstall_display.py'
            script.write_text('raise RuntimeError("fixture cleanup failure")\n')
            p=subprocess.run(['bash',str(cmd/'uninstall_init')],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,1)
            self.assertIn('fixture cleanup failure',(root/'error').read_text())
            self.assertTrue(list(data.glob('.display-uninstall.*')))
            script.write_text('print("fixture cleanup done")\n')
            p=subprocess.run(['bash',str(cmd/'uninstall_init')],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertFalse(list(data.glob('.display-uninstall.*')))
            self.assertEqual((data/'monitor.db').read_text(),'preserve history')


if __name__ == '__main__':unittest.main()
