"""Display preferences and telemetry projection. Never invokes collectors or OS commands."""
import copy
import json
import math
import os
import re
import tempfile
import threading
import time
from pathlib import Path

DEFAULTS = dict(disk="auto", net="auto", gpu="auto", read_mib=200, write_mib=200,
                net_mib=125, power_w=300, cpu_hot=90, gpu_hot=85, intensity=1,
                fps=24, quality="economy")
RANGES = dict(read_mib=(1,100000), write_mib=(1,100000), net_mib=(1,100000),
              power_w=(10,100000), cpu_hot=(40,120), gpu_hot=(40,120), intensity=(.2,1.5))


def number(v, low=0, high=float("inf")):
    return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and low <= v <= high else None


def valid_settings(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):
        raise ValueError("包含不支持的联动设置")
    out = {}
    for key,v in value.items():
        if key in ("disk","net","gpu"):
            if not isinstance(v,str) or len(v)>180 or not v or any(ord(c)<32 for c in v):
                raise ValueError("设备选择无效")
        elif key in RANGES:
            if number(v,*RANGES[key]) is None:raise ValueError("联动范围无效："+key)
        elif key=="fps":
            if type(v) is not int or v not in (15,24,30):raise ValueError("帧率仅支持 15、24、30")
        elif key=="quality" and v not in ("economy","balanced"):
            raise ValueError("画质无效")
        out[key]=v
    return out


class SceneState:
    def __init__(self, directory):
        self.path=Path(directory)/"display-scene.json"
        self.lock=threading.RLock()
        self.config={"mode":"monitor","settings":dict(DEFAULTS)}
        self.observed=None
        self.load_error=""
        if self.path.exists():
            try:
                data=json.loads(self.path.read_text())
                if data.get("mode") not in ("monitor","haloflux"):raise ValueError("画面模式无效")
                self.config={"mode":data["mode"],"settings":dict(DEFAULTS,**valid_settings(data.get("settings",{})))}
            except (ValueError,OSError,TypeError) as exc:
                self.load_error="显示设置读取失败，暂用飞牛监控；原文件保留："+str(exc)

    def status(self):
        with self.lock:
            out=copy.deepcopy(self.config)
            age=time.monotonic()-self.observed[1] if self.observed else None
            out.update(observed=self.observed[0] if age is not None and age<15 else None,
                       connected=age is not None and age<15, warning=self.load_error)
            return out

    def seen(self,mode):
        if mode not in ("monitor","haloflux"):raise ValueError("画面模式无效")
        with self.lock:self.observed=(mode,time.monotonic())

    def update(self,data):
        if not isinstance(data,dict) or not data or set(data)-{"mode","settings"}:
            raise ValueError("不支持的显示设置")
        with self.lock:
            new=copy.deepcopy(self.config)
            if "mode" in data:
                if data["mode"] not in ("monitor","haloflux"):raise ValueError("画面模式无效")
                new["mode"]=data["mode"]
            if "settings" in data:new["settings"].update(valid_settings(data["settings"]))
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(prefix=".display-scene-",dir=self.path.parent)
            try:
                with os.fdopen(fd,"w") as f:
                    json.dump(new,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
                os.replace(tmp,self.path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
            self.config=new;self.load_error=""
            return self.status()

    def telemetry(self,snapshot,disabled=(),now=None):
        now=time.time() if now is None else now
        snap=snapshot if isinstance(snapshot,dict) else {}
        cfg=self.status()["settings"]
        ts=number(snap.get("ts"));interval=number(snap.get("interval"),1,3600) or 10
        age=max(0,now-ts) if ts else None
        stale=ts is None or ts>now+5 or age>max(30,interval*3+5)
        metrics={}
        def add(key,value,unit,source,reason="传感器或驱动未提供"):
            v=number(value,-40 if unit=="°C" else 0,160 if unit=="°C" else 100 if unit=="%" else float("inf"))
            metrics[key]={"value":None if stale else v,"unit":unit,"source":source,
                          "reason":"采样已过期" if stale else "" if v is not None else reason}
        cpu=snap.get("cpu") or {};mem=snap.get("mem") or {};temp=snap.get("temp") or {}
        add("cpu",cpu.get("percent"),"%","CPU")
        add("cpu_temp",temp.get("cpu"),"°C","CPU 温度")
        add("memory",mem.get("percent"),"%","系统内存")
        add("memory_used",mem.get("used"),"B","系统内存")
        add("memory_total",mem.get("total"),"B","系统内存")
        add("storage",snap.get("disk_total") if number(snap.get("disk_size"),1) else None,"%","存储池总占用")
        add("storage_used",snap.get("disk_used"),"B","存储池")
        add("storage_total",snap.get("disk_size"),"B","存储池")
        disks=[d for d in (snap.get("diskio") or []) if isinstance(d,dict) and isinstance(d.get("name"),str)]
        # Sum whole physical devices, never both a device and its partitions/RAID layers.
        physical=[d for d in disks if re.fullmatch(r"(?:sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)",d["name"])]
        chosen=physical if cfg["disk"]=="auto" else [d for d in disks if d["name"]==cfg["disk"]]
        ds="物理盘合计" if cfg["disk"]=="auto" else cfg["disk"]
        def total(items,key):
            vals=[number(d.get(key)) for d in items]
            return sum(vals) if vals and all(v is not None for v in vals) else None
        for key,field in (("disk_read","read_rate"),("disk_write","write_rate")):
            add(key,None if "diskio" in disabled else total(chosen,field),"B/s",ds,"磁盘 I/O 采集关闭或所选设备不可用")
        nets=[n for n in (snap.get("net") or []) if isinstance(n,dict) and isinstance(n.get("iface"),str)]
        eligible=[n for n in nets if not re.match(r"^(lo$|docker|veth|br-|virbr|tun|tap|vnet|lxc|kube|wg|vxlan)",n["iface"])]
        net=max(eligible,key=lambda n:(number(n.get("rx_rate")) or 0)+(number(n.get("tx_rate")) or 0),default={}) if cfg["net"]=="auto" else next((n for n in nets if n["iface"]==cfg["net"]),{})
        ns=("最忙网卡 · " if cfg["net"]=="auto" else "")+net.get("iface","未发现网卡")
        for key,field in (("net_rx","rx_rate"),("net_tx","tx_rate")):
            add(key,None if "net" in disabled else net.get(field),"B/s",ns,"网络采集关闭或所选网卡不可用")
        gpus=[g for g in (snap.get("gpu") or []) if isinstance(g,dict)]
        gid=lambda g,i:str(g.get("pci") or "gpu-"+str(i))
        gpu=max(gpus,key=lambda g:number(g.get("util")) or 0,default={}) if cfg["gpu"]=="auto" else next((g for i,g in enumerate(gpus) if gid(g,i)==cfg["gpu"]),{})
        gs=str(gpu.get("name") or "未发现 GPU")
        util=gpu.get("util") if gpu.get("util_avail") is not False else None
        if gpu.get("util_source") not in (None,"driver","pmu"):gs+=" · "+str(gpu["util_source"])+"估算"
        add("gpu",util,"%",gs,"所选 GPU 不提供占用率")
        add("gpu_temp",gpu.get("temp"),"°C",gs,"所选 GPU 不提供独立温度")
        vp=gpu.get("mem_pct")
        used=number(gpu.get("mem_used"));size=number(gpu.get("mem_total"),1)
        if vp is None and used is not None and size is not None:vp=used/size*100
        if gpu.get("shared_memory"):vp=used=size=None
        for key,value,unit in (("vram",vp,"%"),("vram_used",used,"B"),("vram_total",size,"B")):
            add(key,value,unit,gs,"共享显存或驱动未提供专用显存读数")
        power=snap.get("power") or {};source=power.get("source")
        ps={"idrac":"iDRAC 整机实测","rapl":"CPU 实测 + 整机估算","estimate":"整机估算","estimated":"整机估算"}.get(source,"整机估算 / "+str(source or "未知"))
        add("power",power.get("total") if power.get("ok") else None,"W",ps)
        return dict(ts=ts,age=age,stale=stale,interval=interval,metrics=metrics,settings=cfg,
                    devices=dict(disks=[d["name"] for d in disks],nets=[n["iface"] for n in nets],
                                 gpus=[dict(id=gid(g,i),name=str(g.get("name") or gid(g,i))) for i,g in enumerate(gpus)]))
