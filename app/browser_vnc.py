"""Same-origin, authenticated WebSocket bridge to a private Unix VNC socket."""
import base64
import hashlib
import os
import select
import socket
import struct
import time
from pathlib import Path
from urllib.parse import urlsplit

SOCKET = "/run/fnmonitor-browser-vnc/screen.sock"

def frame(data, opcode=2):
    n=len(data)
    return bytes([0x80|opcode])+ (bytes([n]) if n<126 else b"\x7e"+struct.pack("!H",n) if n<65536 else b"\x7f"+struct.pack("!Q",n)) + data

def parse(buf):
    """Return (opcode, payload, bytes consumed), None if incomplete. Fragmentation rejected."""
    if len(buf)<2:return None
    a,b=buf[:2]
    if not a&128 or a&112 or not b&128 or a&15 not in (2,8,9,10):
        raise ValueError("unsupported websocket frame")
    n=b&127; off=2
    if n==126:
        if len(buf)<4:return None
        n=struct.unpack("!H",buf[2:4])[0];off=4
    elif n==127:
        if len(buf)<10:return None
        n=struct.unpack("!Q",buf[2:10])[0];off=10
    if n>1024*1024 or (a&15>=8 and n>125):raise ValueError("frame too large")
    if len(buf)<off+4+n:return None
    mask=buf[off:off+4];body=buf[off+4:off+4+n]
    return a&15,bytes(v^mask[i%4] for i,v in enumerate(body)),off+4+n

def serve(handler, app):
    path=urlsplit(handler.path).path
    if path not in ("/remote.html","/api/display/socket") and not path.startswith("/novnc/"):
        return False
    if not app._auth_required():
        handler._json({"error":"请先启用监控登录口令。"},status=403);return True
    if not app._check_auth(handler.headers):
        if path=="/remote.html":
            handler.send_response(302);handler.send_header("Location","/login.html?next=%2Fremote.html")
            handler.send_header("Content-Length","0");handler.end_headers()
        else:handler._json({"error":"需要登录"},status=401)
        return True
    if path=="/api/display/socket":
        bridge(handler,app);return True
    rel=path.lstrip("/")
    root=Path(app.www_dir).resolve();file=(root/rel).resolve()
    if not file.is_relative_to(root) or file.suffix not in (".js",".html",".json",".txt") or not file.is_file():
        handler.send_error(404);return True
    body=file.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type","text/javascript; charset=utf-8" if file.suffix==".js" else "text/html; charset=utf-8" if file.suffix==".html" else "text/plain; charset=utf-8")
    handler.send_header("X-Content-Type-Options","nosniff")
    handler.send_header("Cache-Control","no-store")
    handler.send_header("Content-Length",str(len(body)))
    handler.end_headers();handler.wfile.write(body)
    return True

def bridge(h,app):
    origin=urlsplit(h.headers.get("Origin",""))
    # An authenticated cookie alone must not allow cross-site WebSocket hijacking.
    key=h.headers.get("Sec-WebSocket-Key","")
    try: valid_key=len(base64.b64decode(key,validate=True))==16
    except ValueError:valid_key=False
    if (origin.scheme not in ("http","https") or origin.netloc.lower()!=h.headers.get("Host","").lower()
        or h.headers.get("Upgrade","").lower()!="websocket"
        or "upgrade" not in h.headers.get("Connection","").lower()
        or h.headers.get("Sec-WebSocket-Version")!="13" or not valid_key):
        h.send_error(403);return
    if not app.display_controller.browser_ready():
        h.send_error(409,"Remote control is stopped");return
    upstream=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        upstream.settimeout(3);upstream.connect(SOCKET)
    except OSError:
        upstream.close();h.send_error(503);return
    h.send_response(101)
    h.send_header("Upgrade","websocket");h.send_header("Connection","Upgrade")
    h.send_header("Sec-WebSocket-Accept",base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode())
    if "binary" in h.headers.get("Sec-WebSocket-Protocol","").split(","):h.send_header("Sec-WebSocket-Protocol","binary")
    h.end_headers();h.wfile.flush()
    h.close_connection=True;client=h.connection;client.settimeout(3)
    buf=b"";deadline=time.monotonic()+7200;check=0
    try:
        while time.monotonic()<deadline:
            if time.monotonic()>check:
                if not app._auth_required() or not app._check_auth(h.headers) or not app.display_controller.browser_ready():break
                check=time.monotonic()+2
            ready,_,_=select.select([client,upstream],[],[],1)
            if upstream in ready:
                data=upstream.recv(65536)
                if not data:break
                client.sendall(frame(data))
            if client in ready:
                data=client.recv(65536)
                if not data:break
                buf+=data
                while True:
                    parsed=parse(buf)
                    if parsed is None:break
                    opcode,payload,used=parsed;buf=buf[used:]
                    if opcode==8:return
                    if opcode==9:client.sendall(frame(payload,10))
                    if opcode==2:upstream.sendall(payload)
    except (OSError,ValueError):pass
    finally:
        upstream.close()
        try:client.sendall(frame(b"",8))
        except OSError:pass
