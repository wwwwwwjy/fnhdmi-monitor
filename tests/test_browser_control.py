import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/"app"/(name+".py"))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class WebSocketTest(unittest.TestCase):
 def test_binary_and_control_frames(self):
  m=load("browser_vnc");mask=b"abcd";data=b"mouse-and-key"
  wire=b"\x82"+bytes([128+len(data)])+mask+bytes(v^mask[i%4] for i,v in enumerate(data))
  self.assertIsNone(m.parse(wire[:-1]))
  self.assertEqual(m.parse(wire),(2,data,len(wire)))
  for invalid in (b"\x82\x00",b"\x02\x80",b"\x81\x80",b"\x82\xff"+struct.pack("!Q",2**32)):
   with self.assertRaises(ValueError):m.parse(invalid)

class CleanupTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.m=load("display_resources");self.m.ROOT=Path(self.temp.name)/"records";self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def test_preexisting_packages_never_purged(self):
  self.m.write("vnc",{"packages":[]})
  with patch.object(self.m,"installed",return_value={"x11vnc","other-app"}),patch.object(self.m,"run") as run:
   self.m.uninstall("vnc")
  run.assert_not_called();self.assertFalse(self.m.ROOT.exists())
 def test_reverse_dependency_refuses_purge_and_keeps_receipt(self):
  self.m.write("vnc",{"packages":["x11vnc"]})
  with patch.object(self.m,"installed",return_value={"x11vnc","other-app"}),patch.object(self.m,"run",return_value="Remv x11vnc\nRemv other-app\n") as run:
   with self.assertRaises(RuntimeError):self.m.uninstall("vnc")
  self.assertEqual(run.call_count,1);self.assertTrue(self.m.read("vnc"))
 def test_shared_dependency_transferred_only_to_remaining_feature(self):
  self.m.write("vnc",{"packages":["x11vnc","libshared"]})
  self.m.write("hdmi",{"packages":[],"account_preexisting":True})
  def run(cmd,capture=False):
   self.calls.append(cmd)
   if cmd[0]=="apt-cache":return "chromium\nlibshared\n"
   if "-s" in cmd:return "Purg x11vnc\n"
   return ""
  with patch.object(self.m,"installed",return_value={"x11vnc","libshared","chromium"}),patch.object(self.m,"run",side_effect=run):
   self.m.uninstall("vnc")
  self.assertEqual(self.m.read("hdmi")["packages"],["libshared"])
  self.assertIsNone(self.m.read("vnc"))
  self.assertEqual(self.calls[-1][-2:],["purge","x11vnc"])
