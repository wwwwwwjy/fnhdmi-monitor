"""Real authenticated HTTP/browser smoke check with isolated disposable app data."""
import importlib.util,os,shutil,subprocess,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='fnm-coffee-') as td:
 pkg=Path(td)/'app';shutil.copytree(root/'app',pkg)
 spec=importlib.util.spec_from_file_location('coffee_server',pkg/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 (Path(td)/'data').mkdir()
 app=m.MonitorApp(str(Path(td)/'data'),dict(m.DEFAULT_CONFIG,update_autocheck=0,update_autoupdate=0,disk_standby_protect=0),host='127.0.0.1')
 server=ThreadingHTTPServer(('127.0.0.1',0),app.make_handler());app.port=server.server_port
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:subprocess.run(['node',str(root/'tools/verify_coffee.cjs'),str(server.server_port)],check=True)
 finally:server.shutdown();server.server_close()
