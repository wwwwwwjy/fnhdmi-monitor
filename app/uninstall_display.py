"""Remove the application's display integration BEFORE fnOS deletes its files.

Never kill a whole user/TTY, run a login script, or run global apt autoremove.
Fixtures inject a filesystem root and command runner; the CLI only uses /.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

START = '# >>> FNMONITOR KIOSK AUTOSTART >>>'
END = '# <<< FNMONITOR KIOSK AUTOSTART <<<'
UNIT = re.compile(r'fnmonitor-(?:browser-vnc|x11vnc|hdmi|kiosk|display)(?:@[A-Za-z0-9_.-]*)?\.service')
BACKUP = re.compile(r'\.fnmonitor-(?:control|uninstall)\.bak(?:\.\d+)?$')


class Cleanup:
    def __init__(self, root='/', runner=subprocess.run, port=8777, sleep=time.sleep):
        self.root = Path(root).resolve()
        self.runner, self.port, self.sleep = runner, int(port), sleep
        self.errors = []
        self.app = Path(__file__).parent
        spec = importlib.util.spec_from_file_location('uninstall_resources', self.app/'display_resources.py')
        self.resources = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.resources)
        self.resources.ROOT = self.path('/var/lib/fnmonitor-display')
        self.resources.run = self.package_command

    def path(self, name):
        return self.root / str(name).lstrip('/')

    def command(self, args, allowed=(0,), timeout=30):
        p = self.runner(args, capture_output=True, text=True, check=False, timeout=timeout, stdin=subprocess.DEVNULL)
        if p.returncode not in allowed:
            detail = '\n'.join(s.strip() for s in (p.stderr or '', p.stdout or '') if s.strip())
            raise RuntimeError('%s（退出码 %s）：%s' % (shlex.join(args), p.returncode,
                               detail[-1000:] or '无标准输出或错误输出'))
        return p.stdout or ''

    def package_command(self, args, capture=False):
        return self.command(args, timeout=300)

    def attempt(self, label, action):
        print('[阶段] '+label, flush=True)
        try:
            action()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            self.errors.append(label+'：'+str(e))
            print('[未完成] '+self.errors[-1], flush=True)

    def safe_parents(self, p):
        for parent in [p.parent, *p.parents]:
            if parent == self.root:
                return
            if parent.is_symlink():
                raise RuntimeError('路径的父目录是链接，未修改：'+str(p))
        raise RuntimeError('路径超出清理范围：'+str(p))

    def read(self, p):
        self.safe_parents(p)
        if p.is_symlink():
            raise RuntimeError('配置是符号链接，未读取或修改：'+str(p))
        if not p.exists():
            return ''
        if not p.is_file():
            raise RuntimeError('配置不是普通文件：'+str(p))
        return p.read_text()

    def remove(self, p):
        self.safe_parents(p)
        if p.is_symlink() or p.is_file() or (p.exists() and stat.S_ISSOCK(p.lstat().st_mode)):
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)  # Only called for fixed, application-owned directories.

    def replace(self, p, text):
        self.read(p)
        st = p.stat()
        fd, name = tempfile.mkstemp(prefix='.fnmonitor-clean-', dir=p.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
                os.fchmod(f.fileno(), stat.S_IMODE(st.st_mode))
                if hasattr(os, 'fchown'):
                    os.fchown(f.fileno(), st.st_uid, st.st_gid)
            os.replace(name, p)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def app_url(self, value):
        try:
            u = urlsplit(value)
            return u.scheme in ('http', 'https') and u.hostname in ('127.0.0.1', 'localhost', '::1') and u.port == self.port
        except ValueError:
            return False

    def kiosk_file(self, text):
        urls = re.findall(r'https?://[^\s\x22\x27<>]+', text)
        return 'chromium' in text.lower() and '--kiosk' in text and bool(urls) and all(self.app_url(u) for u in urls)

    def accounts(self):
        result = []
        for line in self.read(self.path('/etc/passwd')).splitlines():
            f = line.split(':')
            if len(f) == 7 and f[2].isdigit() and f[5].startswith('/') and f[5] != '/':
                if int(f[2]) >= 1000 or f[0] in ('fnmkiosk', 'root'):
                    result.append((f[0], int(f[2]), self.path(f[5])))
        return result

    def processes(self):
        result = {}
        for p in self.path('/proc').glob('[0-9]*'):
            try:
                args = (p/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
                args = [x.decode(errors='replace') for x in args if x]
                fields = (p/'stat').read_text().rsplit(')', 1)[1].split()
                uid = int(re.search(r'(?m)^Uid:\s+(\d+)', (p/'status').read_text()).group(1))
                result[int(p.name)] = dict(args=args, ppid=int(fields[1]), start=fields[19], state=fields[0], uid=uid)
            except (OSError, ValueError, IndexError, AttributeError):
                continue
        return result

    def display_targets(self, procs):
        browsers = {pid for pid, p in procs.items() if p['args'] and
                    re.fullmatch(r'(?:chromium(?:-browser)?|chrome|google-chrome)', Path(p['args'][0]).name) and
                    '--kiosk' in p['args'] and any(self.app_url(a) for a in p['args'])}
        targets = set(browsers)
        displays = set()
        for pid in browsers:
            try:
                env = (self.path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
                display = next((x[8:].decode() for x in env if x.startswith(b'DISPLAY=')), ':0')
            except OSError:
                display = ':0'
            if re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', display):
                displays.add(display.split('.')[0])
            # xinit/startx can be ancestors; a login shell or SSH daemon never is a target.
            parent = procs[pid]['ppid']
            visited = set()
            while parent in procs and parent not in visited:
                visited.add(parent)
                args = procs[parent]['args']
                if any(Path(a).name in ('xinit', 'startx') for a in args[:2]):
                    targets.add(parent)
                parent = procs[parent]['ppid']
        browser_uids = {procs[pid]['uid'] for pid in browsers}
        for pid, p in procs.items():
            if p['args'] and Path(p['args'][0]).name in ('Xorg', 'X') and p['uid'] in browser_uids | {0}:
                if any(d in p['args'] for d in displays):
                    targets.add(pid)
        # All children of an identified kiosk launcher are part of that session.
        while True:
            children = {pid for pid, p in procs.items() if p['ppid'] in targets}
            if children <= targets:
                break
            targets |= children
        return {pid: procs[pid] for pid in targets}, browsers

    def stop_processes(self, targets):
        def remaining():
            now = self.processes()
            return {pid for pid, old in targets.items() if pid in now and now[pid]['start'] == old['start'] and now[pid]['state'] != 'Z'}
        for signal in ('-TERM', '-KILL'):
            for pid in remaining():
                # Recheck birth time immediately before signalling: never trust a stale PID.
                if pid not in remaining():
                    continue
                self.command(['kill', signal, str(pid)], allowed=(0, 1), timeout=5)
            for _ in range(20):
                if not remaining():
                    return
                self.sleep(.1)
        if remaining():
            raise RuntimeError('图形进程仍在运行：'+','.join(map(str, sorted(remaining()))))

    def clean_x_runtime(self, targets):
        now = self.processes()
        for pid, old in targets.items():
            if not old['args'] or Path(old['args'][0]).name not in ('Xorg', 'X'):
                continue
            for display in old['args']:
                if not re.fullmatch(r':[0-9]+', display):
                    continue
                if any(p['args'] and Path(p['args'][0]).name in ('Xorg', 'X') and display in p['args'] for p in now.values()):
                    raise RuntimeError('图形服务器仍占用 '+display+'，保留其运行文件')
                number=display[1:]
                lock=self.path('/tmp/.X'+number+'-lock')
                if self.read(lock).strip()!=str(pid):
                    continue  # Do not unlink another server's lock/socket.
                sock=self.path('/tmp/.X11-unix/X'+number)
                self.safe_parents(sock)
                if sock.exists():
                    if not stat.S_ISSOCK(sock.lstat().st_mode):
                        raise RuntimeError('X11 运行文件类型异常，未删除：'+str(sock))
                    alive=False
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                        probe.settimeout(.2)
                        try:probe.connect(str(sock));alive=True
                        except OSError:pass
                    if alive:raise RuntimeError('X11 仍接受连接，未删除其运行文件')
                    sock.unlink()
                self.remove(lock)

    def clean_home(self, home):
        for name in ('.bash_profile', '.bash_login', '.profile'):
            p = home/name
            raw = self.read(p)
            if START in raw or END in raw:
                pattern = r'(?ms)^'+re.escape(START)+r'\r?\n.*?^'+re.escape(END)+r'(?:\r?\n|$)'
                cleaned, count = re.subn(pattern, '', raw)
                if not count or START in cleaned or END in cleaned:
                    raise RuntimeError('启动标记不完整，未改写：'+str(p))
                self.replace(p, cleaned)  # Preserve all unrelated shell setup.
        p = home/'.xinitrc'
        if self.kiosk_file(self.read(p)):
            self.remove(p)
        for name in ('.bash_profile', '.bash_login', '.profile', '.xinitrc'):
            for p in home.glob(name+'.fnmonitor-*.bak*'):
                if BACKUP.fullmatch(p.name[len(name):]):
                    self.remove(p)
        if (home/'.vnc/passwd').exists():
            print('[保留既有文件] 用户个人 VNC 密码没有本应用创建记录：'+str(home/'.vnc/passwd'),flush=True)

    def stop_units(self):
        # fnOS can fail list-unit-files without any diagnostic output. Avoid that
        # global file enumeration entirely: query live units, then enumerate only
        # the directories where this app installs its units/enablement links.
        out = self.command(['systemctl', 'list-units', '--all', '--no-legend', '--plain', '--no-pager', 'fnmonitor-*.service'])
        loaded = {line.split()[0] for line in out.splitlines()
                  if line.split() and UNIT.fullmatch(line.split()[0])}
        names = set(loaded)
        bases = [self.path('/etc/systemd/system'), self.path('/run/systemd/system')]
        files, links, dropins = [], [], []
        for base in bases:
            self.safe_parents(base/'placeholder')
            for p in base.glob('fnmonitor-*.service'):
                if UNIT.fullmatch(p.name):
                    files.append(p)
                    names.add(p.name)
            for folder in base.glob('fnmonitor-*.service.d'):
                if UNIT.fullmatch(folder.name[:-2]):
                    dropins.append(folder)
            for suffix in ('.wants', '.requires', '.upholds'):
                for folder in base.glob('*'+suffix):
                    self.safe_parents(folder/'placeholder')
                    for p in folder.iterdir():
                        if p.is_symlink() and UNIT.fullmatch(p.name):
                            links.append(p)
                            names.add(p.name)
        print('[检查] 发现 %d 项本应用服务配置；直接检查服务与自启链接。' % len(names), flush=True)
        for name in sorted(names):
            if '@.' not in name:
                # An enabled instance may have no loaded unit, and a dangling
                # old enablement link may have no unit file at all. Do not ask
                # disable --now to act on an already absent template.
                state = self.command(['systemctl', 'is-active', name], allowed=(0, 3, 4)).strip()
                if (name in loaded and state != 'unknown') or state not in ('inactive', 'failed', 'unknown'):
                    self.command(['systemctl', 'stop', name])
                    state = self.command(['systemctl', 'is-active', name], allowed=(3, 4)).strip()
                if state not in ('inactive', 'failed', 'unknown'):
                    raise RuntimeError('服务停止状态无法确认：'+name+'：'+repr(state))
                self.command(['systemctl', 'reset-failed', name], allowed=(0, 1))
        for p in links + files + dropins:
            self.remove(p)
        # No global disable/enumeration: only app-owned enablement links removed.
        self.command(['systemctl', 'daemon-reload'])

    def clean_getty(self, owned_users):
        changed = set()
        for folder in self.path('/etc/systemd/system').glob('getty@tty[0-9]*.service.d'):
            for p in folder.glob('*.conf'):
                raw = self.read(p)
                match = re.search(r'--autologin(?:=|\s+)([A-Za-z0-9_.-]+)', raw)
                if p.name == 'zz-fnmonitor-kiosk.conf':
                    self.remove(p)
                    changed.add(folder.name[:-2])
                elif match and match.group(1) in owned_users:
                    # Earlier manual setups used override.conf. Remove only autologin,
                    # preserving other getty options/directives in the same file.
                    cleaned = re.sub(r'--autologin(?:=|\s+)'+re.escape(match.group(1))+r'(?=\s|$)\s*', '', raw)
                    meaningful = [s.strip() for s in cleaned.splitlines() if s.strip() and not s.lstrip().startswith('#')]
                    if len(meaningful) == 3 and meaningful[:2] == ['[Service]', 'ExecStart='] and re.fullmatch(r'ExecStart=-/sbin/agetty\s+--noclear %I(?: \$TERM)?', meaningful[2]):
                        self.remove(p)
                    else:
                        self.replace(p, cleaned)
                    changed.add(folder.name[:-2])
            for p in folder.glob('*.fnmonitor-*.bak*'):
                if re.search(r'\.conf'+BACKUP.pattern, p.name):
                    self.remove(p)
            try:
                folder.rmdir()
            except OSError:
                pass
        return changed

    def console(self, changed, targets):
        self.command(['systemctl', 'daemon-reload'])
        if 'getty@tty1.service' in changed or any('vt1' in p['args'] for p in targets.values()):
            self.command(['systemctl', 'restart', 'getty@tty1.service'])
        else:
            self.command(['systemctl', 'start', 'getty@tty1.service'])
        # The console switch must happen BEFORE purging the package providing chvt.
        active = self.path('/sys/class/tty/tty0/active')
        if active.exists():
            # A second cleanup (app-store hook after the browser button) may run
            # after kbd/chvt was purged. An already active tty1 needs no switch.
            if active.read_text().strip() != 'tty1':
                self.command(['chvt', '1'])
            if active.read_text().strip() != 'tty1':
                raise RuntimeError('显示器尚未切回飞牛命令行界面')

    def run(self):
        print('[阶段] 检查 HDMI / VNC 配置与进程', flush=True)
        accounts = self.accounts()
        procs = self.processes()
        if any(str(self.app/'display_resources.py') in p['args'] and 'install' in p['args'] for p in procs.values()):
            raise RuntimeError('显示环境仍在安装，请等待安装结束后再卸载')
        targets, browsers = self.display_targets(procs)
        print('[检查] 识别到 %d 个监控浏览器主进程、%d 个相关图形进程。' % (len(browsers), len(targets)), flush=True)
        owned_users = set()
        for user, uid, home in accounts:
            try:
                def regular(name):
                    p=home/name
                    return self.read(p) if p.is_file() and not p.is_symlink() else ''
                owned = any(START in regular(n) for n in ('.bash_profile', '.bash_login', '.profile'))
                owned = owned or self.kiosk_file(regular('.xinitrc')) or any(procs[p]['uid'] == uid for p in browsers)
                if owned or user == 'fnmkiosk':
                    owned_users.add(user)
                if owned or user == 'fnmkiosk' or any(home.glob('.*.fnmonitor-*.bak*')):
                    self.attempt('移除用户显示启动配置：'+user, lambda home=home: self.clean_home(home))
            except (OSError, RuntimeError) as e:
                self.errors.append(str(e))
        changed = set()
        def getty():
            changed.update(self.clean_getty(owned_users))
        self.attempt('停用并移除 HDMI / VNC 自启服务', self.stop_units)
        self.attempt('清除图形自动登录配置', getty)
        self.attempt('结束本应用的图形会话', lambda: self.stop_processes(targets))
        def verify_graphics():
            if self.display_targets(self.processes())[1]:
                raise RuntimeError('检测到监控浏览器重新启动，请检查其他自启入口')
        self.attempt('确认画面没有被重新启动', verify_graphics)
        if not self.errors:
            self.attempt('清除本会话遗留的 X11 锁与套接字', lambda: self.clean_x_runtime(targets))
        self.attempt('返回飞牛命令行界面', lambda: self.console(changed, targets))
        def runtime():
            for name in ('/etc/fnmonitor-hdmi.enabled', '/etc/fnmonitor-hdmi.uninstalled', '/run/fnmonitor-hdmi.on', '/run/fnmonitor-hdmi.off', '/run/fnmonitor-browser-vnc'):
                self.remove(self.path(name))
        self.attempt('清除 HDMI 开关与 VNC 运行文件', runtime)
        if self.errors:
            raise RuntimeError('\n'.join(self.errors))
        # Package records remain until configuration/process cleanup succeeds, enabling retry.
        print('[阶段] 清除本应用安装的依赖与专用账号', flush=True)
        self.safe_parents(self.resources.ROOT/'hdmi.json')
        self.resources.uninstall_all()
        print('HDMI / VNC 卸载清理完成；已返回飞牛命令行界面。', flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='清理本应用 HDMI / VNC 环境，保留监控服务供查看进度')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        raise RuntimeError('只能由飞牛应用中心在 NAS 上执行卸载清理')
    port = int(os.environ.get('TRIM_SERVICE_PORT') or 8777)
    data = Path(os.environ['TRIM_PKGVAR'])
    cfg = data/'config.json'
    if cfg.is_file():
        settings = json.loads(cfg.read_text())
        port = int(settings.get('port') or port)
    if args.port is not None:
        port = args.port
    if not 0 < port < 65536:
        raise RuntimeError('应用端口配置无效，已停止卸载')
    Cleanup(port=port).run()
    for name in ('display-scene.json', 'display-output.json', '.display-uninstall.log'):
        (data/name).unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
        main()
    except Exception as e:
        print('卸载未完成，应用清理工具与安装记录应保留，修复后可重试：'+str(e), file=sys.stderr, flush=True)
        sys.exit(1)
