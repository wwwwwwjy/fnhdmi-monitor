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

def uninstall_all():
    """Application removal: purge the union, so HDMI/VNC cannot retain each other.

    Keep packages required by another application. No autoremove and no guessing
    ownership of dependencies installed manually before our receipts existed.
    Receipts survive any actual purge failure, allowing uninstall_init to retry.
    """
    if ROOT.is_symlink() or any((ROOT/n).is_symlink() for n in ("hdmi.json","vnc.json")):
        raise RuntimeError("安装记录是符号链接，未执行依赖清理")
    if ROOT.exists():
        unexpected={p.name for p in ROOT.iterdir()}-{"hdmi.json","vnc.json","hdmi.tmp","vnc.tmp"}
        if unexpected:raise RuntimeError("安装记录目录有未识别文件，未删除："+", ".join(sorted(unexpected)))
    receipts={f:read(f) for f in ("hdmi","vnc")}
    if not any(receipts.values()):
        print("没有本应用新增依赖的安装记录；保留原有系统软件。",flush=True)
        if ROOT.exists():
            if any(ROOT.iterdir()):raise RuntimeError("缺少完整安装记录，保留临时清单以便恢复")
            ROOT.rmdir()
        return
    owned=set()
    for receipt in receipts.values():
        for package in (receipt or {}).get("packages",[]):
            import re
            if not isinstance(package,str) or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?",package):
                raise RuntimeError("依赖安装记录包含无效包名，已停止")
            owned.add(package)
    rows=run(["dpkg-query","-W","-f=${binary:Package} ${db:Status-Status}\n"],True)
    present={l.split()[0] for l in rows.splitlines() if len(l.split())==2 and l.split()[1]!="not-installed"}
    packages=owned & present  # Include config-files left by an interrupted purge.
    normal=lambda names:{n.split(":")[0] for n in names}
    def simulated(names):
        plan=run(["apt-get","-s","purge",*sorted(names)],True)
        return {line.split()[1] for line in plan.splitlines() if line.startswith(("Remv ","Purg "))}
    retained=set()
    while packages:
        if not (normal(simulated(packages))-normal(packages)):
            break
        unsafe={p for p in packages if normal(simulated({p}))-normal(packages)}
        if not unsafe:
            # Alternative dependencies can be safe individually but unsafe together.
            # Keep the ambiguous group rather than remove a user's unrelated app.
            unsafe=set(packages)
        retained|=unsafe
        packages-=unsafe
    if retained:
        print("[保留共享依赖] 其他软件仍需要："+", ".join(sorted(retained)),flush=True)
    if packages:
        print("[阶段] 卸载本应用新增依赖（含残余包配置）",flush=True)
        run(["apt-get","-o","DPkg::Lock::Timeout=90","-y","purge",*sorted(packages)])
        after=run(["dpkg-query","-W","-f=${binary:Package} ${db:Status-Status}\n"],True)
        remaining={l.split()[0] for l in after.splitlines() if len(l.split())==2 and l.split()[1]!="not-installed"}
        if normal(remaining)&normal(packages):
            raise RuntimeError("依赖包尚未清理完成，安装记录已保留")
    receipt=receipts.get("hdmi") or {}
    if receipt.get("account_preexisting") is False:
        try:
            account=pwd.getpwnam("fnmkiosk")
        except KeyError:
            account=None
        if account:
            if account.pw_dir!="/var/lib/fnmonitor-kiosk" or not account.pw_uid:
                raise RuntimeError("专用账号已变化，未删除")
            run(["userdel","--remove","fnmkiosk"])
        # The dedicated home remains ours even if a prior userdel removed the account.
        home=ROOT.parent/"fnmonitor-kiosk"
        if home.is_symlink():
            home.unlink()
        elif home.exists():
            import shutil
            shutil.rmtree(home)
    for feature,receipt in receipts.items():
        if receipt is not None:(ROOT/(feature+".json")).unlink(missing_ok=True)
        (ROOT/(feature+".tmp")).unlink(missing_ok=True)
    try:ROOT.rmdir()
    except FileNotFoundError:pass
    except OSError:raise RuntimeError("安装记录目录有未识别的文件，未删除；请检查后重试")

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
