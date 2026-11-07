"""Track packages added by each optional feature, without purging pre-existing dependencies."""
import json
import os
import subprocess
import pwd
from pathlib import Path

ROOT=Path("/var/lib/fnmonitor-display")

def run(args, capture=False):
    r=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE if capture else None,
                     stderr=subprocess.STDOUT if capture else None,text=True,check=False)
    if r.returncode:raise RuntimeError((r.stdout or "命令失败：%s"%args[0])[-3000:])
    return r.stdout or ""

def installed():
    lines=run(["dpkg-query","-W","-f=${binary:Package} ${db:Status-Status}\n"],True)
    return {l.split()[0] for l in lines.splitlines() if l.endswith(" installed")}

def read(feature):
    p=ROOT/(feature+".json")
    return json.loads(p.read_text()) if p.is_file() else None

def write(feature,data):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    if ROOT.is_symlink():raise RuntimeError("安装记录目录不可为链接")
    p=ROOT/(feature+".json")
    tmp=p.with_suffix(".tmp")
    with open(tmp,"w") as f:json.dump(data,f)
    os.chmod(tmp,0o600);os.replace(tmp,p)

def install(feature,port):
    before=installed();receipt=read(feature) or {"packages":[],"state":"installing"}
    if feature=="hdmi" and "account_preexisting" not in receipt:
        try:pwd.getpwnam("fnmkiosk");receipt["account_preexisting"]=True
        except KeyError:receipt["account_preexisting"]=False
    write(feature,receipt)
    try:
        if feature=="hdmi":
            run(["/bin/bash",str(Path(__file__).parent/"systemd/install-env.sh"),str(port)])
        elif feature=="vnc":
            if "x11vnc" not in before:
                print("[阶段] 更新软件列表",flush=True)
                run(["apt-get","-o","Acquire::Retries=1","-o","Acquire::http::Timeout=30","-o","Acquire::https::Timeout=30","update"])
                print("[阶段] 安装浏览器远控服务",flush=True)
                plan=run(["apt-get","-s","--no-install-recommends","install","x11vnc"],True)
                upgrades=[l for l in plan.splitlines() if l.startswith("Inst ") and l.split()[1] in before]
                if upgrades:raise RuntimeError("此安装需要升级现有系统包，已停止，原服务保留。")
                run(["apt-get","-o","DPkg::Lock::Timeout=90","--no-upgrade","--no-remove","--no-install-recommends","-y","install","x11vnc"])
        receipt["state"]="installed"
    finally:
        receipt["packages"]=sorted(set(receipt["packages"]) | (installed()-before))
        write(feature,receipt)

def uninstall(feature):
    receipt=read(feature)
    if not receipt:return
    other=read("vnc" if feature=="hdmi" else "hdmi") or {}
    if feature=="hdmi" and not receipt.get("account_preexisting",True):
        try:
            account=pwd.getpwnam("fnmkiosk")
            if account.pw_dir!="/var/lib/fnmonitor-kiosk":raise RuntimeError("专用账号目录已变化，清理已停止")
            run(["userdel","--remove","fnmkiosk"])
        except KeyError:pass
    packages=set(receipt["packages"]) & installed()
    # Only shared dependencies transfer ownership; independent feature packages are purged.
    if other and packages:
        roots = ["x11vnc"] if feature=="hdmi" else ["xinit","xserver-xorg","xauth","chromium","kbd"]
        deps=run(["apt-cache","depends","--recurse","--installed","--no-recommends","--no-suggests",
                  "--no-conflicts","--no-breaks","--no-replaces","--no-enhances",*roots],True)
        needed={l.strip() for l in deps.splitlines() if l and not l[0].isspace()}
        shared={p for p in packages if p in needed or p.split(":")[0] in needed}
        other["packages"]=sorted(set(other.get("packages",[]))|shared)
        write("vnc" if feature=="hdmi" else "hdmi",other)
        packages-=shared
    if packages:
        sim=run(["apt-get","-s","purge",*sorted(packages)],True)
        removed={line.split()[1] for line in sim.splitlines() if line.startswith(("Remv ","Purg "))}
        if removed-packages:
            raise RuntimeError("清理暂停：其他软件依赖这些包。配置已停用，安装清单保留以便继续清理："+", ".join(sorted(removed-packages)))
        print("[阶段] 清除本功能新增的软件包",flush=True)
        run(["apt-get","-o","DPkg::Lock::Timeout=90","-y","purge",*sorted(packages)])
    (ROOT/(feature+".json")).unlink(missing_ok=True)
    try:ROOT.rmdir()
    except OSError:pass

if __name__=="__main__":
    import sys
    try:
        os.environ["DEBIAN_FRONTEND"]="noninteractive"
        feature,action,port=sys.argv[1:]
        if feature not in ("hdmi","vnc") or action not in ("install","uninstall"):raise ValueError("参数错误")
        if os.geteuid()!=0:raise RuntimeError("需要 NAS 应用服务权限")
        install(feature,int(port)) if action=="install" else uninstall(feature)
        print("环境操作完成。",flush=True)
    except Exception as e:
        print(str(e),flush=True);sys.exit(1)
