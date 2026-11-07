"""Local integration check: python3 tools/verify_display_update.py /path/to/official-x86.fpk"""
import hashlib, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, socket
from pathlib import Path
from http.client import HTTPConnection
from unittest.mock import patch
from secrets import token_hex

root = Path(__file__).resolve().parents[1]
fpk = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="fnm-upgrade-") as td:
    stage = Path(td)
    app = stage / "target"
    shutil.copytree(root / "app", app)
    shutil.copy(root / "manifest", stage / "manifest")
    os.environ.update(TRIM_APPNAME="fnmonitor-compat-test",TRIM_APPDEST=str(app),PYTHONDONTWRITEBYTECODE="1")
    spec=importlib.util.spec_from_file_location("current",app/"server.py")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    data=stage/"data";data.mkdir()
    (data/"config.json").write_text(json.dumps(dict(update_autocheck=0,update_autoupdate=0, disk_standby_protect=0)))
    with patch("threading.Timer.start"):
        result=mod.UpdateManager(str(data)).install_fpk(str(fpk),hashlib.sha256(fpk.read_bytes()).hexdigest())
    assert result[0],result
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    def req(path, body=None, cookie=None):
        c=HTTPConnection("127.0.0.1",port,timeout=5)
        headers={"X-FNM-Request":"1","Content-Type":"application/json","Cookie":cookie or ""}
        c.request("GET" if body is None else "POST",path,None if body is None else json.dumps(body),headers)
        r=c.getresponse(); result=r.status, r.read(), r.getheaders();c.close();return result
    with (stage/"run.log").open("wb") as log:
        proc=subprocess.Popen([sys.executable,str(app/"server.py"),"--host","127.0.0.1","--port",str(port),"--data-dir",str(data)],stdout=log,stderr=log)
    try:
        for _ in range(80):
            if proc.poll() is not None:raise RuntimeError((stage/"run.log").read_text()[-2000:])
            try:
                if req('/api/auth/config')[0]==200:break
            except OSError:pass
            time.sleep(.15)
        result=req('/api/auth/setup',{'password':token_hex(16)})
        assert json.loads(result[1])['ok'],result
        cookie=next(v.split(';')[0] for k,v in result[2] if k.lower()=='set-cookie')
        for url in ('/','/launcher.html','/api/display/status','/api/config','/api/overview','/remote.html','/novnc/core/rfb.js','/haloflux.html','/haloflux/engine.js','/display-scene.js','/api/display/telemetry','/api/display/scene'):
            status,body,_=req(url,cookie=cookie)
            assert status==200,(url,status,body[:300])
            if url=='/launcher.html':assert '返回飞牛命令行界面' in body.decode()
            if url=='/api/display/status':assert 'job' in json.loads(body)
            if url=='/api/config':assert json.loads(body)['config']['version']=='2.41.4'
        scene=req('/api/display/scene',{'mode':'haloflux','settings':{'fps':15}},cookie)
        assert scene[0]==200,scene
        assert json.loads(req('/api/display/scene',cookie=cookie)[1])['mode']=='haloflux'
        assert req('/api/display/telemetry')[0]==401
        assert req('/api/display/status')[0]==401
        assert req('/remote.html')[0]==302
        assert req('/api/display/socket')[0]==401
        assert req('/api/display/action',{'action':'install_env'})[0]==401
        assert req('/launcher.html')[0]==302
        # Nonmutating rejected operation exercises display POST dispatch after login.
        assert req('/api/display/action',{'action':'invalid'},cookie)[0]==400
        assert json.loads((app/'ui/config').read_text())['.url']['fnmonitor.Application']['url']=='/launcher.html'
        print('Official FPK installed into disposable tree: 2.41.4, authenticated launcher, display GET/POST, dashboard, desktop entry OK')
    finally:
        proc.terminate()
        try:proc.wait(7)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
