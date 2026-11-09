"""Authenticated scene endpoints and fixed local assets; no arbitrary file or command access."""
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

ASSETS={"/product-icon.png":("product-icon.png","image/png"),"/haloflux.html":("haloflux.html","text/html"),
        "/display-scene.js":("display-scene.js","text/javascript"),
        "/haloflux/engine.js":("haloflux/engine.js","text/javascript"),
        "/haloflux/telemetry.js":("haloflux/telemetry.js","text/javascript"),
        "/haloflux/LICENSE.txt":("haloflux/LICENSE.txt","text/plain")}


def serve(handler,app,data=None):
    path=urlsplit(handler.path).path
    if path not in ASSETS and path not in ("/api/display/scene","/api/display/scene/seen","/api/display/telemetry"):
        return False
    if handler.command=="GET":
        if path in ASSETS:
            rel,mime=ASSETS[path]
            handler._send(200,(Path(app.www_dir)/rel).read_bytes(),mime+("; charset=utf-8" if mime.startswith("text/") else ""))
        elif path=="/api/display/scene":handler._json(app.scenes.status())
        elif path=="/api/display/telemetry":handler._json(app.api_display_telemetry())
        else:handler.send_error(405)
        return True
    if path not in ("/api/display/scene","/api/display/scene/seen"):
        handler.send_error(405);return True
    if not app._auth_required():
        handler._json({"error":"请先启用登录口令，再切换 HDMI 画面。"},status=403);return True
    try:
        if not isinstance(data,dict):raise ValueError("显示设置必须是对象")
        if path.endswith("/seen"):
            if not ipaddress.ip_address(handler.client_address[0]).is_loopback:
                handler._json({"error":"仅接受 NAS 本机显示页面确认"},status=403);return True
            app.scenes.seen((data or {}).get("mode"))
            handler._json({"ok":True,"screen_fit":app.display_controller.auto_fit_window()})
        else:handler._json({"ok":True,"scene":app.scenes.update(data)})
    except (ValueError,TypeError):handler._json({"error":"显示设置无效，请检查模式、设备及联动范围。"},status=400)
    except OSError:handler._json({"error":"显示设置保存失败，未更改当前设置。"},status=500)
    return True
