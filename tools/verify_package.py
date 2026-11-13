"""Exercise FPK upgrade hooks; --rescue includes the old-hook recovery path."""
import ast,hashlib,http.client,json,os,secrets,shutil,socket,sqlite3,subprocess,sys,tarfile,tempfile,time
from pathlib import Path
official=Path(sys.argv[1]);custom=Path(sys.argv[2])
def unpack(fpk,where):
 where.mkdir()
 with tarfile.open(fpk) as t:t.extractall(where,filter="data")
 (where/"app").mkdir()
 with tarfile.open(where/"app.tgz") as t:t.extractall(where/"app",filter="data")
def defs(path):
 s=path.read_text()
 return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
with tempfile.TemporaryDirectory(prefix="fnm-2415-") as td:
 t=Path(td);old=t/"old";new=t/"new";unpack(official,old);unpack(custom,new)
 allowed={"UpdateManager","MonitorApp","apply_launcher_entry","sync_launcher_db","main","DisplayController"}
 old_version=__import__("re").search(r"(?m)^version\s*=\s*(\S+)",(old/"manifest").read_text()).group(1)
 new_version=__import__("re").search(r"(?m)^version\s*=\s*(\S+)",(new/"manifest").read_text()).group(1)
 old_defs,new_defs=defs(old/"app/server.py"),defs(new/"app/server.py")
 changed={n for n,v in old_defs.items() if new_defs.get(n)!=v}
 assert changed<=allowed,changed
 for p in (old/"app/utils").rglob("*"):
  if p.is_file():assert p.read_bytes()==(new/"app/utils"/p.relative_to(old/"app/utils")).read_bytes()
 def base_dashboard(path):
  data=path.read_bytes()
  for pattern in (rb'<!-- FNMONITOR DISPLAY VIEW START -->.*?<!-- FNMONITOR DISPLAY VIEW END -->\n',rb'/\* FNH PRODUCT UPDATE START \*/.*?/\* FNH PRODUCT UPDATE END \*/\r\n',rb'<!-- FNH PRODUCT ABOUT START -->.*?<!-- FNH PRODUCT ABOUT END -->'):
   data=__import__('re').sub(pattern,b'',data,flags=__import__('re').S)
  # 3.0.10 changes only product navigation, fixed support UI and favicon resources.
  data=__import__('re').sub(rb'<!-- FNH COFFEE START -->.*?<!-- FNH COFFEE END -->\n',b'',data,flags=__import__('re').S)
  data=__import__('re').sub(rb'<link rel="(icon|apple-touch-icon)"[^>]*>',b'',data)
  lines=data.splitlines(keepends=True)
  for i,line in enumerate(lines):
   if b'<div style="display:flex;gap:8px;justify-content:center;margin-top:20px;flex-wrap:wrap">' in line:
    lines[i]=line.replace(b'https://github.com/wwwwwwjy/fnhdmi-monitor',b'https://github.com/MisiteQ/fnmonitor')
  return b''.join(lines)
 assert base_dashboard(old/"app/www/index.html")==base_dashboard(new/"app/www/index.html")
 assert (old/"cmd/main").read_text()==(new/"cmd/main").read_text()
 live=t/"live";shutil.copytree(old/"app",live);shutil.copy2(old/"manifest",live/"manifest")
 data=t/"data";data.mkdir();customdata=t/"history";customdata.mkdir()
 cfg=dict(data_dir=str(customdata),update_autocheck=0,update_autoupdate=0,disk_standby_protect=0,
          disk_scan_enabled=0,monitor={"enable":False},interval=30,retention_days=90,power_rate_yuan=.87,weather_city="北京")
 (data/"config.json").write_text(json.dumps(cfg))
 (customdata/"ui.json").write_text('{"custom-layout":"preserve","theme":"dark"}')
 with sqlite3.connect(customdata/"monitor.db") as db:
  db.execute("CREATE TABLE metrics(ts REAL NOT NULL,metric TEXT NOT NULL,value REAL NOT NULL)")
  stamp=time.time()-100
  db.execute("INSERT INTO metrics VALUES(?,?,?)",(stamp,"cpu",12.345))
 with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
 env=dict(os.environ,TRIM_APPNAME="fnmonitor-release-fixture",TRIM_APPDEST=str(live),
          TRIM_PKGVAR=str(data),PYTHONDONTWRITEBYTECODE="1")
 def req(path,body=None,cookie=""):
  c=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
  c.request("GET" if body is None else "POST",path,None if body is None else json.dumps(body),
            {"Content-Type":"application/json","X-FNM-Request":"1","Cookie":cookie})
  r=c.getresponse();result=r.status,r.read(),dict((k.lower(),v) for k,v in r.getheaders());c.close();return result
 def start():
  log=open(t/"server.log","ab")
  p=subprocess.Popen([sys.executable,str(live/"server.py"),"--host","127.0.0.1","--port",str(port),"--data-dir",str(data)],env=env,stdout=log,stderr=log)
  for _ in range(100):
   if p.poll() is not None:raise AssertionError((t/"server.log").read_text()[-2000:])
   try:
    if req("/api/auth/config")[0]==200:return p,log
   except OSError:pass
   time.sleep(.1)
  p.terminate();raise AssertionError("server startup timed out")
 def stop(p,log):
  p.terminate()
  try:p.wait(10)
  except subprocess.TimeoutExpired:p.kill();p.wait()
  log.close()
 p,log=start()
 try:
  r=req("/api/auth/setup",{"password":secrets.token_hex(24)})
  assert json.loads(r[1])["ok"]
  cookie=r[2]["set-cookie"].split(";")[0]
  assert json.loads(req("/api/config",cookie=cookie)[1])["config"]["version"]==old_version
 finally:stop(p,log)
 (data/"display-scene.json").write_text(json.dumps({"mode":"haloflux","settings":{"read_mib":600,"fps":15}}))
 (data/"display-output.json").write_text('{"mode":"1280x720"}')
 saved_output=(data/"display-output.json").read_bytes()
 saved_scene=(data/"display-scene.json").read_bytes()
 saved=(data/"config.json").read_bytes();saved_ui=(customdata/"ui.json").read_bytes()
 if '--rescue' in sys.argv[3:]:
  import importlib.util
  spec=importlib.util.spec_from_file_location('rescue',Path(__file__).parent/'unblock_upgrade.py')
  rescue=importlib.util.module_from_spec(spec);spec.loader.exec_module(rescue)
  (old/'var').symlink_to(data,target_is_directory=True)
  rescue.repair(old)
  # fnOS replacement can invoke old uninstall hooks before new code is installed.
  context=dict(env,TRIM_APP_STATUS='UPGRADE',TRIM_OLD_APPVER=old_version,wizard_delete_data='true')
  for hook in ('uninstall_init','uninstall_callback'):
   subprocess.run(['bash',str(old/'cmd'/hook)],env=context,check=True)
  assert (data/'config.json').read_bytes()==saved
 # Execute the exact pre-upgrade hook that is shipped in the new package.
 subprocess.run(["bash",str(new/"cmd/upgrade_init")],env=env,check=True)
 assert (data/"config.json").read_bytes()==saved
 backups=list((data/".display-upgrade-backups").glob("*/index.json"));assert len(backups)==1
 mapping=json.loads(backups[0].read_text())
 match=next(x for x in mapping if Path(x["source"]).resolve()==(customdata/"monitor.db").resolve())
 with sqlite3.connect(backups[0].parent/match["backup"]) as db:
  assert db.execute("SELECT value FROM metrics WHERE ts=? AND metric='cpu'",(stamp,)).fetchone()==(12.345,)
 shutil.rmtree(live);shutil.copytree(new/"app",live);shutil.copy2(new/"manifest",live/"manifest")
 subprocess.run(["bash",str(new/"cmd/upgrade_callback")],env=env,check=True)
 if '--rescue' in sys.argv[3:]:
  for hook in ('uninstall_init','uninstall_callback'):
   subprocess.run(['bash',str(new/'cmd'/hook)],env=context,check=True)
  assert (data/'config.json').read_bytes()==saved
  print('PASS: old-hook rescue and new uninstall hooks preserve data in UPGRADE context')
 assert (data/"config.json").read_bytes()==saved
 p,log=start()
 try:
  for url in ("/","/launcher.html","/remote.html","/novnc/core/rfb.js","/api/display/status","/api/config","/api/overview","/haloflux.html","/haloflux/engine.js","/haloflux/telemetry.js","/display-scene.js","/haloflux/LICENSE.txt","/api/display/telemetry","/api/display/scene"):
   r=req(url,cookie=cookie);assert r[0]==200,(url,r[0],r[1][:200])
  assert (data/"display-output.json").read_bytes()==saved_output
  assert json.loads(req("/api/display/status",cookie=cookie)[1])["display_mode"]=="1280x720"
  assert (data/"display-scene.json").read_bytes()==saved_scene
  scene=json.loads(req("/api/display/scene",cookie=cookie)[1]);assert scene["mode"]=="haloflux" and scene["settings"]["read_mib"]==600
  assert req("/api/display/telemetry")[0]==401
  assert req("/api/display/scene",{"mode":"invalid"},cookie)[0]==400
  actual=json.loads(req("/api/config",cookie=cookie)[1])["config"]
  assert actual["product"]["name"]=="飞牛HDMI动态监控"
  assert actual["product"]["developer"]=="汪同学"
  update=json.loads(req("/api/update/check",cookie=cookie)[1]);assert update["manual"] and not update["has_update"] and update["asset"] is None
  assert not json.loads(req("/api/update/install",{},cookie)[1])["ok"]
  assert req("/product-icon.png",cookie=cookie)[1]==(new/"app/www/product-icon.png").read_bytes()
  assert json.loads((live/"ui/config").read_text())[".url"]["fnmonitor.Application"]["title"]=="飞牛HDMI动态监控"
  assert actual["version"]==new_version
  for key in ("data_dir","retention_days","power_rate_yuan","weather_city"):assert actual[key]==cfg[key],key
  assert (customdata/"ui.json").read_bytes()==saved_ui
  with sqlite3.connect(customdata/"monitor.db") as db:
   assert db.execute("SELECT value FROM metrics WHERE ts=? AND metric='cpu'",(stamp,)).fetchone()==(12.345,)
  assert req("/api/display/socket")[0]==401
  assert req("/api/display/action",{"action":"invalid"},cookie)[0]==400
  assert json.loads((live/"ui/config").read_text())[".url"]["fnmonitor.Application"]["url"]=="/launcher.html"
  assert b"\"hdmi_managed\"" in req("/api/display/status",cookie=cookie)[1]
  print("PASS: actual FPK %s -> %s, backup verified; prior session, history row, custom data path, UI and settings retained; launcher/remote routes OK" % (old_version,new_version))
  print("PASS: monitoring functions, data schema, upstream utils, dashboard and service lifecycle main unchanged")
 finally:stop(p,log)
