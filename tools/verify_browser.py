import subprocess,os,sys,shutil,tempfile,importlib.util,threading,socket,struct,time,json
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(__file__).resolve().parents[1]
td=Path(tempfile.mkdtemp(prefix='fnm5-',dir='/tmp'));appdir=td/'app';shutil.copytree(root/'app',appdir)
p=appdir/'browser_vnc.py';p.write_text(p.read_text().replace('"/run/fnmonitor-browser-vnc/screen.sock"',repr(str(td/'vnc.sock'))))
spec=importlib.util.spec_from_file_location('test_server',appdir/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
data=td/'data';data.mkdir()
app=m.MonitorApp(str(data),dict(m.DEFAULT_CONFIG,update_autocheck=0,disk_standby_protect=0),host='127.0.0.1')
app.display_controller.browser_ready=lambda:True
server=ThreadingHTTPServer(('127.0.0.1',0),app.make_handler());app.port=server.server_port
threading.Thread(target=server.serve_forever,daemon=True).start()
events=[]
def exact(c,n):
 b=b''
 while len(b)<n:
  d=c.recv(n-len(b))
  if not d:raise EOFError()
  b+=d
 return b
fixture=td/'rfb_child.py';fixture.write_text("import socket,struct,json,sys\nfrom pathlib import Path\ntd=Path(sys.argv[1]);events=[]\ndef exact(c,n):\n b=b''\n while len(b)<n:\n  d=c.recv(n-len(b))\n  if not d:raise EOFError()\n  b+=d\n return b\nc=socket.socket(fileno=0)\nc.sendall(b'RFB 003.008\\n');exact(c,12);c.sendall(b'\\1\\1');exact(c,1);c.sendall(b'\\0\\0\\0\\0');exact(c,1)\npf=struct.pack('!BBBBHHHBBBxxx',32,24,0,1,255,255,255,16,8,0)\nc.sendall(struct.pack('!HH',320,240)+pf+struct.pack('!I',7)+b'Fn Test')\nwhile True:\n typ=exact(c,1)[0]\n if typ==0:exact(c,19)\n elif typ==2:_,n=struct.unpack('!BH',exact(c,3));exact(c,n*4)\n elif typ==3:\n  exact(c,9);c.sendall(b'\\0\\0\\0\\1'+struct.pack('!HHHHi',0,0,320,240,0)+bytes([80,140,40,0])*320*240)\n elif typ==4:\n  events.append(['key',*struct.unpack('!BxxI',exact(c,7))]);(td/'events.json').write_text(json.dumps(events))\n elif typ==5:\n  events.append(['mouse',*struct.unpack('!BHH',exact(c,5))]);(td/'events.json').write_text(json.dumps(events))\n elif typ==6:\n  n=struct.unpack('!xxxI',exact(c,7))[0];exact(c,n)\n else:raise ValueError(typ)\n")
program="import sys;sys.path.insert(0,sys.argv[1]);import vnc_session;vnc_session.serve(sys.argv[2],sys.argv[3:])"
vnc=subprocess.Popen([sys.executable,'-c',program,str(appdir),str(td/'vnc.sock'),sys.executable,str(fixture),str(td)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
(td/'browser-target.json').write_text(json.dumps({'port':server.server_port,'dir':str(td)}))
print('ready',flush=True)
try:
 subprocess.run(['node',str(root/'tools/verify_browser.cjs'),str(td/'browser-target.json')],check=True)
finally:
 vnc.terminate();vnc.wait(5);server.shutdown();shutil.rmtree(td)
