"""Stage the display extension into an explicitly tested upstream release.

The normal updater verifies the official release digest before calling this.
Only staged files are written. Unknown backend layouts require a new bridge.
"""
import ast
import hashlib
import re
import shutil
from pathlib import Path

SUPPORTED = {"2.41.4": "ab86d8b13ed06af1fe785470b39009934d433cdd2d619e2e85884815323426d2"}

def prepare(installed, staged, unpacked):
    old, new = Path(installed), Path(staged)
    src = new / "server.py"
    version = re.search(r"(?m)^version\s*=\s*([0-9.]+)\s*$",
                        (Path(unpacked) / "manifest").read_text())
    v = version.group(1) if version else ""
    if SUPPORTED.get(v) != hashlib.sha256(src.read_bytes()).hexdigest():
        raise ValueError("此官方包尚未验证与 HDMI / VNC 面板兼容。保留当前服务，请等待适配包。")
    base = (old / "server.py").read_text()
    tree = ast.parse(base)
    def definition(name):
        node = next(n for n in tree.body if getattr(n, "name", "") == name)
        return ast.get_source_segment(base, node)
    def block(first, following):
        a = base.index(first)
        return base[a:base.index(following, a+len(first))]
    s = src.read_text()
    def inject(anchor, before):
        nonlocal s
        if s.count(anchor) != 1:
            raise ValueError("官方接口结构不匹配，已停止")
        s = s.replace(anchor, before+anchor)
    inject('import argparse\n', 'import stat, glob, tempfile\nfrom pathlib import Path\nfrom urllib.parse import quote\ntry:\n    import pwd\nexcept ImportError:\n    pwd = None\n')
    inject('class MonitorApp:', '_DISPLAY_MUTATION = threading.Lock()\n'+definition('DisplayController')+'\n\n')
    inject('        self.updater = UpdateManager(data_dir)', '        self.display_controller = DisplayController()\n        self.display_controller.port = int(port)\n        import importlib.util\n        spec = importlib.util.spec_from_file_location("halo_state", os.path.join(os.path.dirname(__file__), "halo_state.py"))\n        scene_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(scene_module)\n        self.scenes = scene_module.SceneState(self._cfg_dir)\n')
    inject('    def api_overview(self):', block('    def api_display_telemetry(self):','    def api_overview(self):'))
    inject('        # 备份当前 app/', block('        # HDMI compatibility gate:', '        # 备份当前 app/'))
    s = s.replace('    def install_fpk(self, fpk_path, expect_sha256=None):',
                  block('    def install_fpk(self, fpk_path, expect_sha256=None):','    def _install_fpk_guarded(')+'    def _install_fpk_guarded(self, fpk_path, expect_sha256=None):')
    inject('                if path == "/api/overview":', block('                # HALOFLUX routes: this point is after the common authentication gate.','                if path == "/remote.html" or path == "/api/display/socket" or path.startswith("/novnc/"):')+block('                if path == "/remote.html" or path == "/api/display/socket" or path.startswith("/novnc/"):', '                if path == "/api/display/status":')+block('                if path == "/api/display/status":','                    return\n')+'                    return\n                if path == "/launcher.html":\n                    self._serve_html("launcher.html")\n                    return\n')
    inject('                    if path in ("/", "/index.html"):', block('                    if path in ("/launcher.html","/remote.html","/haloflux.html"):','                    if path in ("/", "/index.html"):'))
    inject('                if path == "/api/docker/action":', block('                if path in ("/api/display/scene", "/api/display/scene/seen"):', '                if path == "/api/docker/action":'))
    s=s.replace('POST_ONLY = {', 'POST_ONLY = {"/api/display/scene/seen", "/api/display/action", ')
    # Preserve the upstream helpers; replace only the two desktop entry writers.
    for name in ('apply_launcher_entry','sync_launcher_db'):
        node=next(n for n in ast.parse(s).body if getattr(n,'name','')==name)
        ls=s.splitlines(keepends=True)
        ls[node.lineno-1:node.end_lineno]=[definition(name)+'\n']
        s=''.join(ls)
    compile(s, str(src), 'exec')
    src.write_text(s)
    for rel in ('www/launcher.html','systemd/install-env.sh','systemd/fnmonitor-x11vnc@.service','display_compat.py','browser_vnc.py','vnc_session.py','display_resources.py','systemd/fnmonitor-browser-vnc@.service','www/remote.html','www/display-view.html','www/display-scene.js','www/haloflux.html','halo_state.py','halo_routes.py','ui/config'):
        dst=new/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(old/rel,dst)
    shutil.copytree(old/'www/haloflux',new/'www/haloflux',dirs_exist_ok=True)
    shutil.copytree(old/'www/novnc',new/'www/novnc',dirs_exist_ok=True)
    dashboard=new/'www/index.html'
    dashboard.write_bytes(dashboard.read_bytes().replace(b'</body>',(old/'www/display-view.html').read_bytes()+b'</body>'))
    login=new/'www/login.html'
    js=login.read_text()
    anchor="return location.pathname.replace(/login\\.html$/, '');"
    if anchor not in js:
        raise ValueError("登录页不能返回控制面板，已停止")
    login.write_text(js.replace(anchor,"if(['/launcher.html','/remote.html','/haloflux.html'].includes(new URLSearchParams(location.search).get('next')))return new URLSearchParams(location.search).get('next'); "+anchor))
