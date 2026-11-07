"""Safety checks for the optional HDMI kiosk integration."""
import os
import subprocess
import tempfile
import unittest

from fnm_support import load_server


class DisplayControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fnm-display-")
        self.home = os.path.join(self.tmp, "home", "fnmtest")
        self.override = os.path.join(self.tmp, "etc", "systemd", "system",
                                     "getty@tty1.service.d")
        os.makedirs(self.home)
        os.makedirs(self.override)
        self.override_file = os.path.join(self.override, "zz-fnmonitor-kiosk.conf")
        with open(self.override_file, "w") as f:
            f.write("[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin fnmtest --noclear %I $TERM\n")
        self.profile = os.path.join(self.home, ".bash_profile")
        self.state = os.path.join(self.tmp, "etc", "fnmonitor-hdmi.enabled")
        with open(self.profile, "w") as f:
            f.write('''# >>> FNMONITOR KIOSK AUTOSTART >>>
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] &&
   [ -z "${FNMONITOR_KIOSK_AUTO:-}" ]; then
    export FNMONITOR_KIOSK_AUTO=1
    startx
fi
# <<< FNMONITOR KIOSK AUTOSTART <<<
''')
        self.unit_dir = os.path.join(self.tmp, "units")
        os.makedirs(self.unit_dir)
        self.calls = []
        os.makedirs(os.path.join(self.tmp, "run"))
        self.controller = load_server().DisplayController(
            runner=self.run_command, system_root=self.tmp, unit_dir=self.unit_dir)

    def run_command(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[:2] == ["loginctl", "list-sessions"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(argv, 3, "inactive", "")
        if argv and argv[0] == "pkill":
            return subprocess.CompletedProcess(argv, 1, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setup_backs_up_and_handles_multiline_guard(self):
        ok, message, status = self.controller.setup_hdmi()
        self.assertTrue(ok, message)
        self.assertTrue(status["integrated"])
        self.assertTrue(status["hdmi_enabled"])
        with open(self.profile, "r") as f:
            text = f.read()
        self.assertIn('[ -f "/etc/fnmonitor-hdmi.enabled" ]', text)
        self.assertTrue(os.path.isfile(self.state))
        with open(self.profile + ".fnmonitor-control.bak", "r") as f:
            backup = f.read()
        self.assertNotIn("hdmi.enabled", backup)
        self.assertIn("startx", backup)
        ok2, _, _ = self.controller.setup_hdmi()
        self.assertTrue(ok2, "setup is idempotent")

    def test_boot_choice_does_not_interrupt_display(self):
        self.assertTrue(self.controller.setup_hdmi()[0])
        self.calls.clear()
        self.assertTrue(self.controller.action("boot_off")[0])
        self.assertFalse(os.path.exists(self.state))
        self.assertFalse(any(c[:2] == ["systemctl", "stop"] for c in self.calls))
        self.assertTrue(self.controller.action("boot_on")[0])

    def test_off_fails_when_x_keeps_accepting_connections(self):
        from unittest.mock import patch
        self.assertTrue(self.controller.setup_hdmi()[0])
        with patch.object(self.controller, "_display_alive", return_value=True), patch("time.sleep"):
            ok, reason, st = self.controller.action("hdmi_off")
        self.assertFalse(ok)
        self.assertIn(":0", reason)
        self.assertTrue(st["hdmi_enabled"])

    def test_stale_socket_filename_is_not_a_running_desktop(self):
        xdir = os.path.join(self.tmp, "tmp", ".X11-unix")
        os.makedirs(xdir)
        open(os.path.join(xdir, "X0"), "wb").close()
        self.assertFalse(self.controller.status()["hdmi_running"])

    def test_external_tty4_switch_does_not_stop_x_or_restart_getty(self):
        from unittest.mock import patch
        from pathlib import Path
        root = Path(self.tmp)
        (root / "tmp").mkdir(exist_ok=True)
        (root / "tmp/.X0-lock").write_text("681832")
        proc = root / "proc/681832"
        proc.mkdir(parents=True)
        (proc / "comm").write_text("Xorg")
        (proc / "stat").write_text("681832 (Xorg) S 8 8 8 %d" % os.makedev(4, 4))
        active = root / "sys/class/tty/tty0/active"
        active.parent.mkdir(parents=True)
        active.write_text("tty4")
        def run(argv, **kw):
            if argv[0] == "chvt":
                active.write_text("tty" + argv[1])
            return self.run_command(argv, **kw)
        self.controller.runner = run
        with patch.object(self.controller, "_display_alive", return_value=True):
            self.assertEqual(self.controller.status()["display_vt"], "tty4")
            (root / "tmp/.X0-lock").unlink()
            (proc / "cmdline").write_bytes(b"Xorg\x00:0\x00vt4\x00")
            self.assertEqual(self.controller.status()["display_vt"], "tty4")
            for action, tty in (("show_console", "tty1"), ("show_desktop", "tty4")):
                ok, msg, st = self.controller.action(action)
                self.assertTrue(ok, msg)
                self.assertEqual(st["active_vt"], tty)
                self.assertTrue(st["hdmi_running"])
            self.assertFalse(self.controller.action("hdmi_off")[0])
            self.assertFalse(any(c[0] == "pkill" or "stop" in c for c in self.calls))

    def test_background_install_streams_output_and_finishes_after_refresh(self):
        from pathlib import Path
        from unittest.mock import patch
        import time
        temp = Path(self.tmp)
        (temp / "display_resources.py").write_text(
            'from pathlib import Path\ndef read(feature):return None\n'
            'if __name__=="__main__":\n'
            ' import time,sys\n print("[阶段] 下载软件",flush=True)\n print("first package",flush=True)\n'
            ' for i in range(100):\n'
            '  if Path(__file__+".resume").exists():break\n'
            '  time.sleep(.03)\n'
            ' print("cannot install",flush=True)\n sys.exit(7)\n')
        self.controller.port = 8777
        with patch.object(load_server(), "__file__", str(temp / "server.py")):
            ok, _, _ = self.controller.start_job("install_env")
            self.assertTrue(ok)
            for _ in range(100):
                if "first package" in self.controller.status()["job"]["lines"]:
                    break
                time.sleep(.015)
            j = self.controller.status()["job"]
            self.assertEqual((j["state"], j["stage"]), ("running", "下载软件"))
            self.assertFalse(self.controller.start_job("hdmi_off")[0])
            (temp / "display_resources.py.resume").touch()
            for _ in range(100):
                if self.controller.job()["state"] != "running":
                    break
                time.sleep(.015)
            j = self.controller.status()["job"]
            self.assertEqual(j["state"], "error")
            self.assertIn("退出码 7", j["message"])
            self.assertIn("cannot install", j["lines"])

    def test_unrecognized_profile_is_left_untouched(self):
        with open(self.profile, "w") as f:
            f.write("# user login setup\n")
        ok, _, _ = self.controller.setup_hdmi()
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.profile + ".fnmonitor-control.bak"))

    def test_hdmi_off_terminates_only_tty1_session_and_returns_to_getty(self):
        ok, _, _ = self.controller.setup_hdmi()
        self.assertTrue(ok)
        xdir = os.path.join(self.tmp, "tmp", ".X11-unix")
        os.makedirs(xdir)
        xpath = os.path.join(xdir, "X0")
        with open(xpath, "w"):
            pass
        probes = [0]

        def runner(argv, **kw):
            self.calls.append(list(argv))
            if argv[:2] == ["loginctl", "list-sessions"]:
                return subprocess.CompletedProcess(argv, 0,
                    "7 1000 fnmtest seat0 tty1\n8 1000 fnmtest seat0 pts/0\n", "")
            if argv[:2] == ["loginctl", "show-session"]:
                return subprocess.CompletedProcess(argv, 0, "tty1\n", "")
            if argv[:2] == ["loginctl", "terminate-session"]:
                if os.path.exists(xpath):
                    os.unlink(xpath)
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[:2] == ["systemctl", "is-active"]:
                return subprocess.CompletedProcess(argv, 3, "inactive", "")
            if argv and argv[0] == "pkill":
                if argv[1] == "-TERM":
                    code = 0
                elif argv[1] == "-0":
                    probes[0] += 1
                    code = 0
                else:
                    code = 1
                return subprocess.CompletedProcess(argv, code, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.calls.clear()
        self.controller.runner = runner
        ok, message, status = self.controller.action("hdmi_off")
        self.assertTrue(ok, message)
        self.assertTrue(status["hdmi_enabled"])
        self.assertFalse(status["hdmi_running"])
        self.assertTrue(os.path.exists(self.state))
        self.assertIn(["loginctl", "terminate-session", "7"], self.calls)
        self.assertIn(["systemctl", "stop", "getty@tty1.service"], self.calls)
        self.assertIn(["systemctl", "start", "getty@tty1.service"], self.calls)
        self.assertNotIn(["systemctl", "restart", "getty@tty1.service"], self.calls)
        self.assertIn(["pkill", "-TERM", "-t", "tty1"], self.calls)
        self.assertIn(["pkill", "-0", "-t", "tty1"], self.calls)
        self.assertIn(["pkill", "-KILL", "-t", "tty1"], self.calls)
        self.assertNotIn(["loginctl", "terminate-session", "8"], self.calls)

    def test_off_can_clear_graphics_left_after_older_uninstall(self):
        ok, _, _ = self.controller.setup_hdmi()
        self.assertTrue(ok)
        ok, _, status = self.controller.uninstall_hdmi()
        self.assertTrue(ok)
        self.assertTrue(status["hdmi_uninstalled"])

        xdir = os.path.join(self.tmp, "tmp", ".X11-unix")
        os.makedirs(xdir, exist_ok=True)
        xpath = os.path.join(xdir, "X0")
        with open(xpath, "w"):
            pass

        def runner(argv, **kw):
            self.calls.append(list(argv))
            if argv[:2] == ["loginctl", "list-sessions"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv and argv[0] == "pkill":
                if argv[1] == "-TERM":
                    os.unlink(xpath)
                    code = 0
                else:
                    code = 1
                return subprocess.CompletedProcess(argv, code, "", "")
            if argv[:2] == ["systemctl", "is-active"]:
                return subprocess.CompletedProcess(argv, 3, "inactive", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.controller.runner = runner
        ok, message, status = self.controller.action("hdmi_off")
        self.assertTrue(ok, message)
        self.assertTrue(status["hdmi_uninstalled"])
        self.assertFalse(status["hdmi_running"])
        self.assertFalse(os.path.exists(xpath))
        self.assertIn(["systemctl", "start", "getty@tty1.service"], self.calls)

    def test_hdmi_off_reports_when_tty_process_cleanup_cannot_run(self):
        ok, _, _ = self.controller.setup_hdmi()
        self.assertTrue(ok)

        def runner(argv, **kw):
            self.calls.append(list(argv))
            if argv[:2] == ["loginctl", "list-sessions"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv and argv[0] == "pkill":
                return subprocess.CompletedProcess(argv, 1, "", "pkill is unavailable")
            if argv[:2] == ["systemctl", "is-active"]:
                return subprocess.CompletedProcess(argv, 3, "inactive", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.controller.runner = runner
        ok, message, _ = self.controller.action("hdmi_off")
        self.assertFalse(ok)
        self.assertIn("tty1 图形进程清理失败", message)

    def test_uninstall_removes_kiosk_setup_and_keeps_recovery_backups(self):
        ok, _, _ = self.controller.setup_hdmi()
        self.assertTrue(ok)
        xinitrc = os.path.join(self.home, ".xinitrc")
        with open(xinitrc, "w") as f:
            f.write("chromium --kiosk http://127.0.0.1:8777/#/overview\n")
        xdir = os.path.join(self.tmp, "tmp", ".X11-unix")
        os.makedirs(xdir)
        xpath = os.path.join(xdir, "X0")
        with open(xpath, "w"):
            pass

        def runner(argv, **kw):
            self.calls.append(list(argv))
            if argv[:2] == ["loginctl", "list-sessions"]:
                return subprocess.CompletedProcess(argv, 0, "7 1000 fnmtest seat0 tty1\n", "")
            if argv[:2] == ["loginctl", "show-session"]:
                return subprocess.CompletedProcess(argv, 0, "tty1\n", "")
            if argv[:2] == ["loginctl", "terminate-session"]:
                if os.path.exists(xpath):
                    os.unlink(xpath)
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[:2] == ["systemctl", "is-active"]:
                return subprocess.CompletedProcess(argv, 3, "inactive", "")
            if argv and argv[0] == "pkill":
                return subprocess.CompletedProcess(argv, 1, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.controller.runner = runner
        ok, message, status = self.controller.uninstall_hdmi()
        self.assertTrue(ok, message)
        self.assertTrue(status["hdmi_uninstalled"])
        self.assertFalse(status["compatible"])
        self.assertFalse(os.path.exists(self.state))
        self.assertFalse(os.path.exists(self.override_file))
        self.assertTrue(os.path.isfile(self.override_file + ".fnmonitor-uninstall.bak"))
        self.assertFalse(os.path.exists(xinitrc))
        self.assertTrue(os.path.isfile(xinitrc + ".fnmonitor-uninstall.bak"))
        with open(self.profile, "r") as f:
            self.assertNotIn(self.controller.PROFILE_START, f.read())
        self.assertTrue(os.path.isfile(self.profile + ".fnmonitor-uninstall.bak"))
        self.assertIn(["loginctl", "terminate-session", "7"], self.calls)
        self.assertIn(["systemctl", "daemon-reload"], self.calls)
        self.assertIn(["systemctl", "stop", "getty@tty1.service"], self.calls)
        self.assertIn(["systemctl", "start", "getty@tty1.service"], self.calls)

        # Reinstall must use the preserved backups, expose a usable HDMI setup state,
        # and leave the recovery copies intact.
        from unittest.mock import patch
        with patch.object(self.controller, "_display_alive", return_value=True):
            ok, message, status = self.controller.action("setup_hdmi")
        self.assertTrue(ok, message)
        self.assertTrue(status["compatible"])
        self.assertTrue(status["integrated"])
        self.assertTrue(status["hdmi_enabled"])
        self.assertFalse(status["hdmi_uninstalled"])
        self.assertTrue(os.path.isfile(self.override_file))
        self.assertTrue(os.path.isfile(xinitrc))
        self.assertTrue(os.path.isfile(self.profile + ".fnmonitor-uninstall.bak"))
        self.assertTrue(os.path.isfile(self.override_file + ".fnmonitor-uninstall.bak"))
        self.assertTrue(os.path.isfile(xinitrc + ".fnmonitor-uninstall.bak"))


if __name__ == "__main__":
    unittest.main()
