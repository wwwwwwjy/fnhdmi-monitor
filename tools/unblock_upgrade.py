"""One-time rescue for known 3.0.1-3.0.3 hooks that block installing their fix.

Only replaces two hash-verified scripts, retaining exact private backups.
No monitor/HDMI/VNC commands, no data deletion, no package installation.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

ALLOWED = {'uninstall_init': ['cd210fed4c3e6ca5960c2196cdd7a519402be69c6ca91aa026903fcd59c68282'], 'uninstall_callback': ['5a1ab4a91d0f5557faf9d4339a80f772df40dae95af96484c3aa2795f94d4250']}
STUB = b"#!/bin/sh\n# FNH304_UPGRADE_UNBLOCK: temporary recovery hook; replaced by 3.0.4 upgrade.\necho 'Upgrade recovery mode: preserve display and monitoring data. Install 3.0.4 before uninstalling.'\nexit 0\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode, uid, gid):
    fd, name = tempfile.mkstemp(prefix='.fnh304-repair-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
            os.fchown(f.fileno(), uid, gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def repair(base):
    base = Path(base)
    manifest = (base/'manifest').read_text()
    if not re.search(r'(?m)^display_name\s*=\s*飞牛HDMI动态监控\s*$', manifest):
        raise RuntimeError('应用身份不符，未修改')
    version = re.search(r'(?m)^version\s*=\s*(\S+)', manifest)
    if not version or version.group(1) not in ('3.0.1','3.0.2','3.0.3'):
        raise RuntimeError('此工具只修复 3.0.1—3.0.3，请勿用于其他版本')
    cmd = base/'cmd'
    if cmd.is_symlink() or not cmd.is_dir():
        raise RuntimeError('生命周期目录异常，未修改')
    originals = {}
    for name in ('uninstall_callback','uninstall_init'):
        path=cmd/name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('脚本类型异常，未修改：'+name)
        data=path.read_bytes(); st=path.stat()
        if data != STUB and digest(data) not in ALLOWED[name]:
            raise RuntimeError('脚本不是已核对的测试版，未覆盖：'+name)
        originals[name]=(path,data,st)
    data_dir=(base/'var').resolve(strict=True)
    backup=data_dir/'.upgrade-unblock-304'
    if backup.is_symlink():raise RuntimeError('备份目录是链接，未修改')
    backup.mkdir(mode=0o700,exist_ok=True)
    if not backup.is_dir():raise RuntimeError('备份路径异常，未修改')
    for name,(path,data,st) in originals.items():
        dst=backup/(name+'.original')
        if dst.is_symlink():raise RuntimeError('备份文件是链接，未修改')
        if dst.exists():
            if digest(dst.read_bytes()) not in ALLOWED[name]:
                raise RuntimeError('原始备份校验失败，未修改：'+name)
        elif data==STUB:
            raise RuntimeError('恢复模式缺少原始备份，未继续修改')
        else:
            atomic(dst,data,0o600,os.geteuid(),os.getegid())
        if data!=STUB and dst.read_bytes()!=data:
            raise RuntimeError('原始备份不一致，未修改：'+name)
    changed=[]
    try:
        for name,(path,data,st) in originals.items():
            if path.read_bytes()!=data:raise RuntimeError('脚本在修复期间发生变化，已停止')
            if data!=STUB:
                atomic(path,STUB,stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
                changed.append(name)
        for path,_,_ in originals.values():
            if path.read_bytes()!=STUB:raise RuntimeError('修复后校验失败')
    except Exception:
        for name in reversed(changed):
            path,data,st=originals[name]
            atomic(path,data,stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
        raise
    print('修复完成：已解除旧卸载钩子的升级拦截。')
    print('监控数据、HDMI / VNC 环境及其他服务未作修改。')
    print('原始脚本备份：'+str(backup))
    print('下一步：在飞牛应用中心覆盖安装 3.0.4 测试包；此时不要卸载应用。')


if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('需要 sudo 权限，仅修复本应用两个脚本')
    repair('/var/apps/fnmonitor')
