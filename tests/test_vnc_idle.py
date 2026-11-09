"""Real supervisor/Unix-socket checks with a short injected idle threshold."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from fnm_support import REPO

class IdleTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='vnc-idle-',dir='/tmp');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);os.chmod(self.root,0o700)
        self.sock=self.root/'screen.sock';self.log=open(self.root/'journal','w+');self.addCleanup(self.log.close)
        child=self.root/'child.py';child.write_text("import socket\ns=socket.socket(fileno=0)\ns.sendall(b'RFB 003.008\\n')\nwhile s.recv(4096):pass\n")
        self.args=[sys.executable,'-c','import sys;sys.path.insert(0,sys.argv[1]);import vnc_session;assert vnc_session.IDLE_TIMEOUT==1800;vnc_session.serve(sys.argv[2],sys.argv[3:],idle_timeout=.8)',str(Path(REPO)/'app'),str(self.sock),sys.executable,str(child)]
        self.procs=[];self.clients=[];self.addCleanup(self.stop)
    def stop(self):
        for c in self.clients:c.close()
        for p in self.procs:
            if p.poll() is None:p.terminate()
            p.wait(timeout=5)
    def start(self):
        p=subprocess.Popen(self.args,stdout=self.log,stderr=self.log);self.procs.append(p)
        for _ in range(150):
            if self.sock.exists():return p
            self.assertIsNone(p.poll());time.sleep(.01)
        self.fail('socket not ready')
    def connect(self):
        c=socket.socket(socket.AF_UNIX);c.settimeout(3);c.connect(str(self.sock));self.clients.append(c)
        self.assertEqual(c.recv(12),b'RFB 003.008\n');return c
    def test_no_initial_client_exits_cleanly_and_can_start_again(self):
        p=self.start();self.assertEqual(p.wait(timeout=4),0);self.assertFalse(self.sock.exists())
        self.log.flush();self.assertIn('VNC 已自动停用',(self.root/'journal').read_text())
        p=self.start();self.connect();self.assertIsNone(p.poll())
    def test_connected_viewer_kept_alive_last_disconnect_and_reconnect_reset_timer(self):
        p=self.start();a=self.connect();b=self.connect()
        time.sleep(1.1);self.assertIsNone(p.poll()) # no mouse/keyboard traffic
        a.close();time.sleep(1.1);self.assertIsNone(p.poll()) # second viewer still connected
        b.close();time.sleep(.35)
        c=self.connect();time.sleep(1.1);self.assertIsNone(p.poll())
        ended=time.monotonic();c.close();self.assertEqual(p.wait(timeout=4),0)
        self.assertGreaterEqual(time.monotonic()-ended,.75)
        self.assertFalse(self.sock.exists())

if __name__=='__main__':unittest.main()
