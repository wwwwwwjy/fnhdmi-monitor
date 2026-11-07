"""Regression coverage for the unsupported -unixsockonly startup and migration."""
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fnm_support import load_server, REPO

OLD_UNIT = """[Unit]
Description=fnMonitor browser control of the physical display
After=network.target
[Service]
Type=simple
User=%i
WorkingDirectory=~
RuntimeDirectory=fnmonitor-browser-vnc
RuntimeDirectoryMode=0700
UMask=0077
ExecStart=/usr/bin/x11vnc -display :0 -auth guess -unixsockonly /run/fnmonitor-browser-vnc/screen.sock -nopw -forever -shared -noxdamage
Restart=no
"""


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.units = self.root / "units"; self.units.mkdir()
        self.calls = []
        def runner(argv, **kwargs):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        self.c = load_server().DisplayController(runner=runner, system_root=str(self.root), unit_dir=str(self.units))
        self.c._resources().write("vnc", {"packages": [], "active_user": "fixtureuser"})
        self.unit = self.units / "fnmonitor-browser-vnc@.service"
        self.unit.write_text(OLD_UNIT)

    def tearDown(self):
        self.temp.cleanup()

    def test_migrate_known_service_preserve_data_idempotently(self):
        untouched = self.units / "other-app.service"; untouched.write_text("unrelated")
        self.c._browser_sync_unit()
        updated = self.unit.read_text()
        self.assertNotIn("unixsockonly", updated)
        self.assertIn("vnc_session.py", updated)
        self.assertNotIn("@APP_DIR@", updated)
        self.c._browser_sync_unit()
        self.assertEqual(self.unit.read_text(), updated)
        self.assertEqual(untouched.read_text(), "unrelated")
        self.assertEqual(set(self.units.iterdir()), {untouched, self.unit})
        receipt = self.c._resources().read("vnc")
        self.assertEqual(receipt["active_user"], "fixtureuser")
        self.assertEqual(receipt["packages"], [])
        self.assertEqual(receipt["unit_sha256"], hashlib.sha256(updated.encode()).hexdigest())
        self.assertEqual(self.calls, [["systemctl", "daemon-reload"]] * 2)

    def test_refuse_modified_or_symlinked_service(self):
        self.unit.write_text(OLD_UNIT + "# personal config\n")
        with self.assertRaises(OSError): self.c._browser_sync_unit()
        self.assertIn("personal config", self.unit.read_text())
        self.unit.unlink(); self.unit.symlink_to(self.root / "unrelated")
        with self.assertRaises(OSError): self.c._browser_sync_unit()
        self.assertEqual(self.calls, [])

    def test_cleanup_accepts_new_service_and_preserves_other_files(self):
        self.c._browser_sync_unit()
        unrelated = self.units / "other.service"; unrelated.write_text("keep")
        with patch.object(self.c, "_describe", return_value={}), patch.object(self.c, "_env_install", return_value=(True, "removed", {})):
            ok, _, _ = self.c._browser_remove()
        self.assertTrue(ok)
        self.assertFalse(self.unit.exists())
        self.assertEqual(unrelated.read_text(), "keep")

    def test_error_from_start_of_log_survives_help_tail(self):
        c = self.c
        st = {"browser_installed": True, "vnc_user": "fixtureuser", "hdmi_running": True}
        lines = "XOpenDisplay failed: Authorization required\n" + "renamed: -mouse, use -cursor\n" * 100
        def runner(argv, **kw):
            self.calls.append(argv)
            out = lines if argv[0] == "journalctl" else "a" * 32 if argv[:2] == ["systemctl", "show"] else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        c.runner = runner
        c._job = {"state": "running", "stage": "", "lines": []}
        with patch.object(c, "_describe", return_value=st), patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__.return_value.recv.return_value = b""
            ok, message, _ = c._browser_start()
        self.assertFalse(ok)
        self.assertIn("XOpenDisplay failed", message)
        self.assertIn("XOpenDisplay failed", c._job["lines"][0])
        self.assertFalse(c._resources().read("vnc")["ready"])
        self.assertEqual(mock_socket.call_count, 1)
        journal = next(a for a in self.calls if a[0] == "journalctl")
        self.assertIn("_SYSTEMD_INVOCATION_ID=" + "a" * 32, journal)


class InetdSupervisorTest(unittest.TestCase):
    def test_private_stream_stderr_separation_reconnect_and_stop_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="vnc-test-", dir="/tmp") as td:
            td = Path(td); os.chmod(td, 0o700)
            child = td / "child.py"
            child.write_text("import os,sys,socket\nfrom pathlib import Path\n"
                             "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
                             "print('diagnostic belongs in journal',file=sys.stderr,flush=True)\n"
                             "s=socket.socket(fileno=0);s.sendall(b'RFB 003.008\\n')\n"
                             "while True:\n d=s.recv(4096)\n if not d:break\n s.sendall(d)\n")
            pidfile = td / "pid"; sockpath = td / "screen.sock"
            program = "import sys;sys.path.insert(0,sys.argv[1]);import vnc_session;vnc_session.serve(sys.argv[2],sys.argv[3:])"
            with (td / "journal").open("w+") as log:
                p = subprocess.Popen([sys.executable, "-c", program, str(Path(REPO)/"app"), str(sockpath), sys.executable, str(child), str(pidfile)], stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        if sockpath.exists():break
                        self.assertIsNone(p.poll()); time.sleep(.02)
                    self.assertEqual(sockpath.stat().st_mode & 0o777, 0o600)
                    for _ in range(2):
                        with socket.socket(socket.AF_UNIX) as c:
                            c.settimeout(3); c.connect(str(sockpath))
                            self.assertEqual(c.recv(12), b"RFB 003.008\n")
                            c.sendall(b"mouse-keyboard"); self.assertEqual(c.recv(14), b"mouse-keyboard")
                    with socket.socket(socket.AF_UNIX) as c:
                        c.settimeout(3); c.connect(str(sockpath)); c.recv(12)
                        child_pid = int(pidfile.read_text())
                        p.terminate(); p.wait(timeout=5)
                        self.assertEqual(c.recv(1), b"")
                        with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
                    self.assertFalse(sockpath.exists())
                    log.seek(0); self.assertIn("diagnostic belongs in journal", log.read())
                finally:
                    if p.poll() is None:p.terminate(); p.wait(timeout=5)
