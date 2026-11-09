import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('halo_state',ROOT/'app/halo_state.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class HaloStateTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=m.SceneState(self.root)
 def tearDown(self):self.tmp.cleanup()
 def sample(self):
  return dict(ts=1000,interval=10,cpu={'percent':0},mem={'percent':40,'used':4,'total':10},temp={'cpu':50},disk_total=80,disk_size=100,
    diskio=[{'name':n,'read_rate':r,'write_rate':0} for n,r in [('sda',10),('sda1',10),('md0',20),('nvme0n1',30),('nvme0n1p1',30)]],
    net=[{'iface':'eth0','rx_rate':10,'tx_rate':2},{'iface':'bond0','rx_rate':10,'tx_rate':4},{'iface':'veth123','rx_rate':500,'tx_rate':0}],
    gpu=[{'pci':'0000:00:02.0','name':'Intel','util':0,'util_avail':True,'util_source':'rc6','temp':None,'shared_memory':True}],
    power={'ok':True,'source':'rapl','total':0})
 def test_missing_zero_and_estimates(self):
  d=self.state.telemetry(self.sample(),now=1001)['metrics']
  self.assertEqual(d['cpu']['value'],0);self.assertEqual(d['power']['value'],0)
  self.assertEqual(d['gpu']['value'],0);self.assertIn('估算',d['gpu']['source'])
  self.assertIsNone(d['gpu_temp']['value']);self.assertIsNone(d['vram']['value'])
  self.assertIn('估算',d['power']['source'])
 def test_no_partition_raid_or_network_double_count(self):
  d=self.state.telemetry(self.sample(),now=1001)['metrics']
  self.assertEqual(d['disk_read']['value'],40)
  self.assertEqual(d['net_rx']['value'],10);self.assertIn('bond0',d['net_rx']['source'])
 def test_explicit_sources_disappear_without_fallback(self):
  self.state.update({'settings':{'disk':'md0','net':'missing','gpu':'missing'}})
  d=self.state.telemetry(self.sample(),now=1001)['metrics']
  self.assertEqual(d['disk_read']['value'],20);self.assertIsNone(d['net_rx']['value']);self.assertIsNone(d['gpu']['value'])
 def test_stale_and_disabled_readings_not_reused(self):
  s=self.sample()
  d=self.state.telemetry(s,now=1100);self.assertTrue(d['stale']);self.assertTrue(all(v['value'] is None for v in d['metrics'].values()))
  d=self.state.telemetry(s,disabled=['net','diskio'],now=1001)['metrics']
  self.assertIsNone(d['net_rx']['value']);self.assertIsNone(d['disk_read']['value'])
 def test_nonfinite_and_boolean_values_are_unavailable(self):
  s=self.sample();s['cpu']['percent']=True;s['temp']['cpu']=float('nan');s['power']['total']=float('inf')
  d=self.state.telemetry(s,now=1001)['metrics']
  for key in ('cpu','cpu_temp','power'):self.assertIsNone(d[key]['value'])
  json.dumps(d,allow_nan=False)
 def test_preferences_atomic_persistent_and_separate(self):
  original=self.root/'config.json';original.write_text('{"retention_days":90}')
  self.state.update({'mode':'haloflux','settings':{'fps':15,'read_mib':800}})
  again=m.SceneState(self.root).status();self.assertEqual(again['mode'],'haloflux');self.assertEqual(again['settings']['fps'],15)
  self.assertEqual(original.read_text(),'{"retention_days":90}')
  before=self.state.path.read_bytes()
  for invalid in ({'mode':'shell'},{'settings':{'fps':999}},{'settings':{'intensity':float('nan')}},{'command':'evil'},[]):
   with self.assertRaises(ValueError):self.state.update(invalid)
   self.assertEqual(before,self.state.path.read_bytes())
  self.assertEqual(self.state.path.stat().st_mode&0o777,0o600)
 def test_corrupt_file_preserved_and_observation_not_persisted(self):
  self.state.path.write_text('broken');s=m.SceneState(self.root);self.assertTrue(s.status()['warning']);self.assertEqual(s.path.read_text(),'broken')
  s.seen('monitor');self.assertTrue(s.status()['connected']);self.assertEqual(s.status()['observed'],'monitor')

 def test_title_defaults_legacy_preferences_persistence_and_validation(self):
  self.state.path.write_text(json.dumps({'mode':'haloflux','settings':{'read_mib':700}}))
  legacy=m.SceneState(self.root);self.assertEqual(legacy.status()['settings']['title'],'HALOFLUX')
  self.assertEqual(legacy.status()['settings']['read_mib'],700)
  legacy.update({'settings':{'title':'  汪同学的 NAS  '}})
  self.assertEqual(m.SceneState(self.root).status()['settings']['title'],'汪同学的 NAS')
  for invalid in ('a'*33,'bad\nline','bad\x00',None,12):
   with self.assertRaises(ValueError):legacy.update({'settings':{'title':invalid}})
  self.assertEqual(legacy.status()['settings']['title'],'汪同学的 NAS')
  legacy.update({'settings':{'title':'   '}});self.assertEqual(legacy.status()['settings']['title'],'HALOFLUX')
  values=legacy.telemetry(self.sample(),now=1001)['defaults'];self.assertEqual(values,m.DEFAULTS)
  values['title']='changed';self.assertEqual(m.DEFAULTS['title'],'HALOFLUX')
