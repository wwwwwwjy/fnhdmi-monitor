"""Run distro x11vnc in supported inetd mode behind a private Unix socket.

No TCP listener is created. stdin/stdout carry RFB; stderr stays in the journal.
systemd runs this supervisor as the physical desktop owner and owns its cgroup.
"""
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

IDLE_TIMEOUT = 30 * 60

SOCKET = "/run/fnmonitor-browser-vnc/screen.sock"
COMMAND = ["/usr/bin/x11vnc", "-norc", "-display", ":0", "-auth", "guess",
           "-inetd", "-nopw", "-noxdamage", "-noremote", "-xrandr", "resize"]


def serve(path=SOCKET, command=None, idle_timeout=IDLE_TIMEOUT):
    if idle_timeout <= 0:raise ValueError("idle timeout must be positive")
    path = Path(path)
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) & 0o077):
        raise RuntimeError("远控运行目录必须由当前用户独占（0700）")
    if path.exists() or path.is_symlink():
        raise RuntimeError("远控 socket 已存在，拒绝覆盖；请停止旧服务后重试")
    children = []
    stopping = False
    idle_since = time.monotonic()
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    previous = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound = False
    try:
        listener.bind(str(path)); bound = True
        os.chmod(path, 0o600)
        listener.listen(4)
        listener.settimeout(.25)
        print("浏览器远控通道已建立，等待验证图形会话。", flush=True)
        while not stopping:
            for child in children[:]:
                result = child.poll()
                if result is not None:
                    children.remove(child)
                    if result:
                        print("x11vnc 会话退出，状态码 %s；原因见上方日志。" % result,
                              file=sys.stderr, flush=True)
            # Keep observation-only connections alive. Count idle time only
            # after the last session process has exited, using a monotonic clock.
            if children:
                idle_since = None
            elif idle_since is None:
                idle_since = time.monotonic()
            if idle_since is not None and time.monotonic() - idle_since >= idle_timeout:
                print("连续 30 分钟无人连接，VNC 已自动停用；需要时请在后台重新开启。", flush=True)
                break
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            with client:
                if len(children) >= 4:
                    continue
                # Do not merge stderr into stdout: it would corrupt the RFB handshake.
                idle_since = None
                children.append(subprocess.Popen(command or COMMAND, stdin=client,
                                                 stdout=client, stderr=None, close_fds=True))
    finally:
        listener.close()
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 3
        for child in children:
            try:
                child.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
        if bound:
            path.unlink(missing_ok=True)
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    try:
        serve()
    except Exception as exc:
        print("浏览器远控启动失败：%s" % exc, file=sys.stderr, flush=True)
        sys.exit(1)
