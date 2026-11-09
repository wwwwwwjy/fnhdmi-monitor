#!/bin/bash
# Invoked only by the authenticated display controller, never on package upgrade.
set -eu
port=${1:-8777}
[[ $port =~ ^[0-9]+$ ]] && (( port > 0 && port < 65536 )) || exit 2
fail(){ echo "$*" >&2; exit 1; }
[[ $EUID == 0 && -d /run/systemd/system ]] || fail "需要 fnOS 的 root 应用服务和 systemd。"
user=fnmkiosk
home=/var/lib/fnmonitor-kiosk
dir=/etc/systemd/system/getty@tty1.service.d
override=$dir/zz-fnmonitor-kiosk.conf
new=1
shopt -s nullglob
if [[ -e "$override" || -S /tmp/.X11-unix/X0 ]]; then new=0; fi
if ((new)); then
    [[ ! -e $home && ! -L $home ]] && ! id "$user" &>/dev/null || fail "专用账号或目录已存在，未覆盖。请先检查先前安装。"
    if systemctl -q is-active display-manager || [[ -S /tmp/.X11-unix/X0 ]]; then
        fail "已有图形桌面在运行，请先识别现有启动方式；没有修改 tty1。"
    fi
fi
echo "[阶段] 检查本机已经安装的软件"
packages=()
for pair in startx:xinit Xorg:xserver-xorg xauth:xauth chromium:chromium chvt:kbd xrandr:x11-xserver-utils; do
    command -v "${pair%%:*}" >/dev/null || packages+=("${pair#*:}")
done
if (("${#packages[@]}")); then
    export DEBIAN_FRONTEND=noninteractive
    echo "[阶段] 刷新软件包列表"
    apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
    echo "[阶段] 下载并安装：${packages[*]}"
    apt-get -o DPkg::Lock::Timeout=90 --no-remove --no-install-recommends -y install "${packages[@]}"
fi
echo "[阶段] 检查并配置本地显示"
if ((!new)); then
    echo "环境已就绪。保留现有启动配置，请接入现有脚本或使用恢复按钮。"; exit
fi
# Stage only new files. Never write as root through links in a user's home.
useradd --system --create-home --home-dir "$home" --shell /bin/bash "$user"
created=1
cleanup(){
    if ((created)); then
        if [[ -n ${installed_override:-} ]]; then rm -f "$override"; systemctl daemon-reload || :; fi
        userdel -r "$user" || :
    fi
}
trap cleanup EXIT
runuser -u "$user" -- tee "$home/.bash_profile" >/dev/null <<'PROFILE'
# >>> FNMONITOR KIOSK AUTOSTART >>>
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${FNMONITOR_KIOSK_AUTO:-}" ] && { [ -f "/run/fnmonitor-hdmi.on" ] || { [ ! -f "/run/fnmonitor-hdmi.off" ] && [ -f "/etc/fnmonitor-hdmi.enabled" ]; }; }; then
    export FNMONITOR_KIOSK_AUTO=1
    startx -- :0 vt1 -keeptty -s 0 -dpms
fi
# <<< FNMONITOR KIOSK AUTOSTART <<<
PROFILE
runuser -u "$user" -- tee "$home/.xinitrc" >/dev/null <<XINIT
#!/bin/sh
# App and HDMI logins may start in either order on boot.
python3 -c 'import socket,time
for _ in range(120):
    try:
        socket.create_connection(("127.0.0.1",$port),1).close()
        break
    except OSError:
        time.sleep(1)'
exec chromium --no-first-run --no-default-browser-check --kiosk http://127.0.0.1:$port/
XINIT
runuser -u "$user" -- chmod 700 "$home/.xinitrc"
mkdir -p "$dir"
( set -C; cat > "$override" <<UNIT
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $user --noclear %I \$TERM
UNIT
)
installed_override=1
systemctl daemon-reload
created=0
echo "环境已安装。点击「显示飞牛监控」启动；开机默认保留命令行。"
