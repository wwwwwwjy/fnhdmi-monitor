"""Run real browser scene switching and telemetry animation against isolated test data."""
import copy,importlib.util,json,os,shutil,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='fnm-halo-',dir='/tmp') as td:
 t=Path(td);pkg=t/'app';shutil.copytree(root/'app',pkg);data=t/'data';data.mkdir()
 spec=importlib.util.spec_from_file_location('halo_test_server',pkg/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 app=m.MonitorApp(str(data),dict(m.DEFAULT_CONFIG,update_autocheck=0,update_autoupdate=0,disk_standby_protect=0),host='127.0.0.1')
 fixture=t/'sample.json'
 sample=dict(interval=10,cpu={'percent':12,'cores':6},mem={'percent':44,'used':3.2*2**30,'total':7.3*2**30},
  temp={'cpu':48,'system':35},disk_total=92,disk_used=4.99*2**40,disk_size=5.43*2**40,
  diskio=[{'name':'sda','read_rate':20*2**20,'write_rate':5*2**20},{'name':'sda1','read_rate':20*2**20,'write_rate':5*2**20}],
  net=[{'iface':'eth0','rx_rate':35*2**20,'tx_rate':8*2**20}],
  gpu=[{'pci':'0000:01:00.0','name':'示例 GPU','util':22,'util_avail':True,'util_source':'driver','temp':55,'mem_used':2*2**30,'mem_total':8*2**30,'mem_pct':25}],
  power={'ok':True,'source':'rapl','total':107.5})
 fixture.write_text(json.dumps(sample))
 def snapshot():
  s=json.loads(fixture.read_text());s.setdefault('ts',time.time());return s
 app.collector.get_snapshot=snapshot
 server=ThreadingHTTPServer(('127.0.0.1',0),app.make_handler());app.port=server.server_port
 threading.Thread(target=server.serve_forever,daemon=True).start()
 target=t/'target.json';target.write_text(json.dumps({'port':server.server_port,'sample':str(fixture),'data':str(data)}))
 try:subprocess.run(['node',str(root/'tools/verify_halo.cjs'),str(target)],check=True)
 finally:server.shutdown();server.server_close()
