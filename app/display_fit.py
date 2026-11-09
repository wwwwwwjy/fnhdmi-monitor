"""Fit only the app's Chromium kiosk to its active X11 monitor.

Runs as a short-lived child. Uses advertised 1080p/720p modes; no modelines/daemon.
The browser process supplies its own X11 identity; never accept client XIDs/paths.
"""
import ctypes as C
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
from urllib.parse import urlsplit


def randr_state(raw):
    screen=re.search(r'current\s+(\d+)\s+x\s+(\d+)',raw)
    if not screen:raise RuntimeError('无法读取 X11 桌面分辨率')
    outputs=[];current=None
    for line in raw.splitlines():
        match=re.match(r'^(\S+) (connected|disconnected)\b(.*)',line)
        if match:
            current=None
            if match[2]=='connected':
                geometry=re.search(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)',match[3])
                current=dict(name=match[1],modes=[],active=bool(geometry),geometry=tuple(map(int,geometry.groups())) if geometry else None)
                outputs.append(current)
        elif current is not None:
            mode=re.match(r'^\s+(\d+x\d+)\s+(.+)$',line)
            if mode:
                current['modes'].append(mode[1])
                if '*' in mode[2]:current['mode']=mode[1]
    return dict(size=tuple(map(int,screen.groups())),outputs=outputs)


def change_mode(requested, run=subprocess.run):
    if requested not in ('auto','1920x1080','1280x720'):raise ValueError('只支持自动、1920×1080、1280×720')
    binary=shutil.which('xrandr')
    if not binary:raise RuntimeError('缺少 xrandr，请先在控制面板安装 HDMI 显示环境')
    def command(args):
        p=run([binary,*args],capture_output=True,text=True,timeout=6,stdin=subprocess.DEVNULL)
        if p.returncode:raise RuntimeError('分辨率命令失败：'+(p.stderr or p.stdout or str(p.returncode)).strip()[-500:])
        return p.stdout
    before=randr_state(command(['--query']))
    # Never shrink a shared desktop or change an unrelated second monitor.
    if len(before['outputs'])!=1 or not before['outputs'][0]['active']:
        raise RuntimeError('需要唯一已连接并启用的显示器；多屏配置请先手动选择输出')
    output=before['outputs'][0];old=output.get('mode');g=output['geometry']
    if not old:raise RuntimeError('无法确认原始输出模式，未修改')
    choices=[m for m in (('1920x1080','1280x720') if requested=='auto' else (requested,)) if m in output['modes']]
    if not choices:raise RuntimeError('显示器未报告所选 16:9 模式，已保留原设置')
    def apply(mode,size,pos):command(['--output',output['name'],'--mode',mode,'--pos',pos,'--fb','%dx%d'%size])
    def restore():
        apply(old,before['size'],'%dx%d'%(g[2],g[3]))
        restored=randr_state(command(['--query']))
        active=next((o for o in restored['outputs'] if o['name']==output['name']),{})
        if restored['size']!=before['size'] or active.get('mode')!=old:raise RuntimeError('原分辨率恢复未确认')
    failures=[]
    for mode in choices:
        size=tuple(map(int,mode.split('x')))
        changed=(old!=mode or before['size']!=size or g[2:]!=(0,0))
        try:
            if changed:apply(mode,size,'0x0')
            after=randr_state(command(['--query']))
            active=next((o for o in after['outputs'] if o['name']==output['name']),{})
            if after['size']!=size or active.get('mode')!=mode or active.get('geometry')!=(*size,0,0):
                raise RuntimeError('输出或桌面分辨率未达到目标')
            return dict(output=output['name'],mode=mode,mode_changed=changed,previous=old),restore if changed else lambda:None
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as e:
            failures.append(str(e))
            if changed:restore()
    raise RuntimeError('；'.join(failures))


def kiosk(args, port):
    if not args or Path(args[0]).name not in ('chromium','chromium-browser','chrome','google-chrome') or '--kiosk' not in args:
        return False
    for arg in args:
        try:
            u=urlsplit(arg)
            if u.scheme in ('http','https') and u.hostname in ('localhost','127.0.0.1','::1') and u.port==port:return True
        except ValueError:pass
    return False


def sessions(port, proc=Path('/proc')):
    found=[]
    for p in proc.glob('[0-9]*'):
        try:
            args=[x.decode(errors='replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
            if not kiosk(args,port):continue
            uid=int(re.search(r'(?m)^Uid:\s+(\d+)',(p/'status').read_text()).group(1))
            env=dict(x.decode(errors='replace').split('=',1) for x in (p/'environ').read_bytes().split(b'\0') if b'=' in x)
            if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?',env.get('DISPLAY','')):continue
            found.append((int(p.name),uid,env))
        except (OSError,ValueError,AttributeError):continue
    if len(found)!=1:raise RuntimeError('未找到唯一的本应用 HDMI 浏览器；请先显示监控或 HALOFLUX 画面')
    return found[0]


def monitor_for(rect, monitors, root):
    valid=[m for m in monitors if m['width']>0 and m['height']>0]
    primary=next((m for m in valid if m['primary']),None)
    if primary:return primary
    x,y,w,h=rect;cx,cy=x+w/2,y+h/2
    return next((m for m in valid if m['x']<=cx<m['x']+m['width'] and m['y']<=cy<m['y']+m['height']),valid[0] if valid else root)


class Monitor(C.Structure):
    _fields_=[('name',C.c_ulong),('primary',C.c_int),('automatic',C.c_int),('noutput',C.c_int),
              ('x',C.c_int),('y',C.c_int),('width',C.c_int),('height',C.c_int),
              ('mwidth',C.c_int),('mheight',C.c_int),('outputs',C.POINTER(C.c_ulong))]


class Attributes(C.Structure):
    _fields_=[(k,C.c_int) for k in ('x','y','width','height','border_width','depth')]+[
        ('visual',C.c_void_p),('root',C.c_ulong),('window_class',C.c_int),
        ('bit_gravity',C.c_int),('win_gravity',C.c_int),('backing_store',C.c_int),
        ('backing_planes',C.c_ulong),('backing_pixel',C.c_ulong),('save_under',C.c_int),
        ('colormap',C.c_ulong),('map_installed',C.c_int),('map_state',C.c_int),
        ('all_event_masks',C.c_long),('your_event_mask',C.c_long),('do_not_propagate_mask',C.c_long),
        ('override_redirect',C.c_int),('screen',C.c_void_p)]


class X11:
    def __init__(self):
        self.x=C.CDLL('libX11.so.6')
        D=C.c_void_p; W=C.c_ulong; I=C.c_int; U=C.c_uint
        signatures={
            'XOpenDisplay':([C.c_char_p],D),'XCloseDisplay':([D],I),'XDefaultRootWindow':([D],W),
            'XInternAtom':([D,C.c_char_p,I],W),'XFree':([D],I),'XSync':([D,I],I),
            'XQueryTree':([D,W,C.POINTER(W),C.POINTER(W),C.POINTER(C.POINTER(W)),C.POINTER(U)],I),
            'XGetGeometry':([D,W,C.POINTER(W),C.POINTER(I),C.POINTER(I),C.POINTER(U),C.POINTER(U),C.POINTER(U),C.POINTER(U)],I),
            'XGetWindowProperty':([D,W,W,C.c_long,C.c_long,I,W,C.POINTER(W),C.POINTER(I),C.POINTER(W),C.POINTER(W),C.POINTER(D)],I),
            'XMoveResizeWindow':([D,W,I,I,U,U],I),'XSetWindowBorderWidth':([D,W,U],I),
            'XGetWindowAttributes':([D,W,C.POINTER(Attributes)],I),
            'XSetScreenSaver':([D,I,I,I,I],I),'XForceScreenSaver':([D,I],I),
            'XGetScreenSaver':([D,C.POINTER(I),C.POINTER(I),C.POINTER(I),C.POINTER(I)],I),
            'XQueryExtension':([D,C.c_char_p,C.POINTER(I),C.POINTER(I),C.POINTER(I)],I),
        }
        for name,(args,result) in signatures.items():
            f=getattr(self.x,name);f.argtypes=args;f.restype=result
        self.errors=[]
        self.handler=C.CFUNCTYPE(I,D,D)(lambda *_:self.errors.append('X11 window changed during fit') or 0)
        self.x.XSetErrorHandler.argtypes=[C.c_void_p];self.x.XSetErrorHandler.restype=C.c_void_p
        self.x.XSetErrorHandler(C.cast(self.handler,C.c_void_p))
        self.d=self.x.XOpenDisplay(None)
        if not self.d:raise RuntimeError('无法连接本应用 X11 会话，请检查显示登录状态')
        self.root=self.x.XDefaultRootWindow(self.d)

    def keep_awake(self):
        # Changes only this kiosk X server; no kernel console/global power files.
        # Reset an already blanked saver, then prevent all future idle blanking.
        self.x.XForceScreenSaver(self.d,0)  # ScreenSaverReset
        self.x.XSetScreenSaver(self.d,0,0,0,1)  # disabled, no blanking, allow exposures
        timeout,interval,blanking,exposures=(C.c_int() for _ in range(4))
        self.x.XGetScreenSaver(self.d,C.byref(timeout),C.byref(interval),C.byref(blanking),C.byref(exposures))
        self.x.XSync(self.d,0)
        if self.errors or timeout.value or interval.value:
            raise RuntimeError('屏保关闭未确认，HDMI 常亮尚未生效')
        opcode,event,error=(C.c_int() for _ in range(3))
        dpms='unsupported'
        if self.x.XQueryExtension(self.d,b'DPMS',C.byref(opcode),C.byref(event),C.byref(error)):
            ext=C.CDLL('libXext.so.6');D=C.c_void_p;U=C.c_ushort;I=C.c_int
            for name,args in {
                'DPMSCapable':[D], 'DPMSSetTimeouts':[D,U,U,U], 'DPMSDisable':[D],
                'DPMSInfo':[D,C.POINTER(U),C.POINTER(I)],
                'DPMSGetTimeouts':[D,C.POINTER(U),C.POINTER(U),C.POINTER(U)],
            }.items():
                f=getattr(ext,name);f.argtypes=args;f.restype=I
            if ext.DPMSCapable(self.d):
                if not ext.DPMSSetTimeouts(self.d,0,0,0) or not ext.DPMSDisable(self.d):
                    raise RuntimeError('显示休眠关闭失败')
                # DPMSDisable also wakes an already powered-down display.
                level=C.c_ushort();enabled=C.c_int()
                standby,suspend,off=(C.c_ushort() for _ in range(3))
                info=ext.DPMSInfo(self.d,C.byref(level),C.byref(enabled))
                timers=ext.DPMSGetTimeouts(self.d,C.byref(standby),C.byref(suspend),C.byref(off))
                self.x.XSync(self.d,0)
                if not info or not timers or enabled.value or level.value or any(v.value for v in (standby,suspend,off)) or self.errors:
                    raise RuntimeError('显示休眠关闭未确认，HDMI 常亮尚未生效')
                dpms='disabled'
        return dict(screen_saver_timeout=0,dpms=dpms)

    def prop(self,win,name):
        kind=C.c_ulong();fmt=C.c_int();count=C.c_ulong();after=C.c_ulong();data=C.c_void_p()
        atom=self.x.XInternAtom(self.d,name.encode(),1)
        if not atom:return []
        try:
            rc=self.x.XGetWindowProperty(self.d,win,atom,0,64,0,0,C.byref(kind),C.byref(fmt),C.byref(count),C.byref(after),C.byref(data))
            if rc or fmt.value!=32 or not data:return []
            return list(C.cast(data,C.POINTER(C.c_ulong))[:count.value])
        finally:
            if data:self.x.XFree(data)

    def children(self,win):
        root=C.c_ulong();parent=C.c_ulong();children=C.POINTER(C.c_ulong)();count=C.c_uint()
        try:
            if not self.x.XQueryTree(self.d,win,C.byref(root),C.byref(parent),C.byref(children),C.byref(count)):return []
            return list(children[:min(count.value,4096)])
        finally:
            if children:self.x.XFree(children)

    def geometry(self,win):
        root=C.c_ulong();x=C.c_int();y=C.c_int();w=C.c_uint();h=C.c_uint();border=C.c_uint();depth=C.c_uint()
        if not self.x.XGetGeometry(self.d,win,C.byref(root),C.byref(x),C.byref(y),C.byref(w),C.byref(h),C.byref(border),C.byref(depth)):
            raise RuntimeError('无法读取图形窗口尺寸')
        return x.value,y.value,w.value,h.value

    def monitors(self):
        try:
            rr=C.CDLL('libXrandr.so.2');rr.XRRGetMonitors.argtypes=[C.c_void_p,C.c_ulong,C.c_int,C.POINTER(C.c_int)]
            rr.XRRGetMonitors.restype=C.POINTER(Monitor);rr.XRRFreeMonitors.argtypes=[C.POINTER(Monitor)];rr.XRRFreeMonitors.restype=None
            count=C.c_int();items=rr.XRRGetMonitors(self.d,self.root,1,C.byref(count))
            try:return [{k:getattr(items[i],k) for k in ('x','y','width','height','primary')} for i in range(min(count.value,32))] if items else []
            finally:
                if items:rr.XRRFreeMonitors(items)
        except (OSError,AttributeError):return []

    def visible(self,win):
        attrs=Attributes()
        return bool(self.x.XGetWindowAttributes(self.d,win,C.byref(attrs)) and attrs.map_state==2 and not attrs.override_redirect)

    def fit(self,pid):
        # Search only root children and one WM reparenting level, selecting the
        # largest app window rather than popups. Never resize unrelated clients.
        candidates=[]
        for top in self.children(self.root):
            for win in [top,*self.children(top)]:
                if self.prop(win,'_NET_WM_PID')==[pid] and self.visible(win):
                    rect=self.geometry(win)
                    if rect[2]>=320 and rect[3]>=200:candidates.append((rect[2]*rect[3],win,top,rect))
        if not candidates:raise RuntimeError('尚未找到本应用浏览器窗口，请稍后重试')
        _,win,top,rect=max(candidates)
        _,_,rw,rh=self.geometry(self.root)
        target=monitor_for(rect,self.monitors(),dict(x=0,y=0,width=rw,height=rh,primary=True))
        if not (0<target['width']<=32768 and 0<target['height']<=32768):raise RuntimeError('显示器尺寸无效')
        x,y,w,h=(target[k] for k in ('x','y','width','height'))
        # The installed kiosk has no window manager. Refuse to fight a custom WM
        # rather than resize its frame or other clients through reparenting.
        if win!=top:raise RuntimeError('检测到自定义窗口管理器，请使用其全屏功能；未修改其他窗口')
        changed=rect!=(x,y,w,h)
        if changed:
            self.x.XSetWindowBorderWidth(self.d,win,0)
            self.x.XMoveResizeWindow(self.d,win,x,y,w,h)
        self.x.XSync(self.d,0)
        actual=self.geometry(win);self.x.XSync(self.d,0)
        if self.errors or actual!=(x,y,w,h):raise RuntimeError('窗口尺寸尚未确认，请重试适配')
        return dict(width=w,height=h,changed=changed)

    def close(self):self.x.XCloseDisplay(self.d)


def main(port,mode='auto'):
    pid,uid,env=sessions(port)
    account=pwd.getpwuid(uid)
    if os.geteuid()==0:
        os.setgroups([]);os.setgid(account.pw_gid);os.setuid(uid)
    elif os.geteuid()!=uid:raise RuntimeError('没有本应用图形会话权限')
    os.environ['DISPLAY']=env['DISPLAY'];os.environ['HOME']=account.pw_dir
    auth=env.get('XAUTHORITY') or str(Path(account.pw_dir)/'.Xauthority')
    if not Path(auth).is_absolute():raise RuntimeError('图形认证路径无效')
    os.environ['XAUTHORITY']=auth
    x=X11()
    try:
        awake=x.keep_awake()
        result,restore=change_mode(mode)
        try:return dict(**x.fit(pid),**result,keep_awake=awake)
        except Exception:
            restore()
            raise
    finally:x.close()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);p.add_argument('--mode',choices=('auto','1920x1080','1280x720'),default='auto');args=p.parse_args()
    try:print(json.dumps(dict(ok=True,**main(args.port,args.mode)),ensure_ascii=False))
    except Exception as e:
        print(json.dumps(dict(ok=False,message=str(e)),ensure_ascii=False));raise SystemExit(1)
