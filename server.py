#!/usr/bin/env python3
"""MiniRDP - aynı ağdaki bir tarayıcıdan bu Mac'i görüntüleyip kontrol etmek için mini uzak masaüstü sunucusu."""
import asyncio
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import os
import secrets
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mss
import Quartz as Q
from aiohttp import WSMsgType, web
from PIL import Image

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
STATIC = BASE / "static"
CERTS = BASE / "certs"
TLS = (CERTS / "server.crt").exists() and (CERTS / "server.key").exists()
SCHEME = "https" if TLS else "http"
COOKIE = "minirdp_session"
SESSION_TTL = 7 * 24 * 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("minirdp")


# ---------------------------------------------------------------- yapılandırma / şifre

def load_config():
    cfg = {"host": "0.0.0.0", "port": 8765, "quality": 60, "max_width": 1600}
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    return cfg


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, digest


def check_password(cfg, password):
    if "password_hash" not in cfg:
        return False
    _, digest = hash_password(password, cfg["password_salt"])
    return hmac.compare_digest(digest, cfg["password_hash"])


CFG = load_config()
SESSIONS_PATH = BASE / "sessions.json"


def _pw_tag():
    # Oturumlar şifreye bağlı: şifre değişirse eski oturumların hepsi geçersiz olur.
    return hashlib.sha256(CFG.get("password_hash", "").encode()).hexdigest()[:16]


def load_sessions():
    try:
        data = json.loads(SESSIONS_PATH.read_text())
        if data.get("pw") != _pw_tag():
            return {}
        now = time.time()
        return {k: v for k, v in data["sessions"].items() if v > now}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def save_sessions():
    SESSIONS_PATH.write_text(json.dumps({"pw": _pw_tag(), "sessions": SESSIONS}))
    SESSIONS_PATH.chmod(0o600)


SESSIONS = load_sessions()  # token -> son kullanma zamanı
FAILS = {}  # ip -> [başarısız deneme zamanları]


def valid_session(request):
    token = request.cookies.get(COOKIE)
    exp = SESSIONS.get(token) if token else None
    return exp is not None and exp > time.time()


# ---------------------------------------------------------------- ekran yakalama

_executor = ThreadPoolExecutor(max_workers=1)
_tls = {}


def _grab_raw():
    b = Q.CGDisplayBounds(Q.CGMainDisplayID())
    dims = (b.size.width, b.size.height)
    sct = _tls.get("sct")
    if sct is None or _tls.get("dims") != dims:
        if sct is not None:
            sct.close()
            log.info("Ekran boyutu değişti: %sx%s", *dims)
        sct = _tls["sct"] = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        _tls["dims"] = dims
    shot = sct.grab(sct.monitors[1])
    return shot.size, shot.bgra


def _encode(size, raw, quality, max_width):
    im = Image.frombytes("RGB", size, raw, "raw", "BGRX")
    if max_width and im.width > max_width:
        h = round(im.height * max_width / im.width)
        im = im.resize((max_width, h), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def capture(last_hash, quality, max_width):
    """Değişiklik yoksa None döner; varsa (hash, jpeg)."""
    size, raw = _grab_raw()
    h = hashlib.blake2b(raw, digest_size=16).digest()
    if h == last_hash:
        return None
    return h, _encode(size, raw, quality, max_width)


def apply_resolution():
    """config.json'daki "resolution" ([genişlik, yükseklik]) farklıysa ekranı o moda alır."""
    want = CFG.get("resolution")
    if not want:
        return
    d = Q.CGMainDisplayID()
    cur = Q.CGDisplayCopyDisplayMode(d)
    if (Q.CGDisplayModeGetWidth(cur), Q.CGDisplayModeGetHeight(cur)) == tuple(want):
        return
    for m in Q.CGDisplayCopyAllDisplayModes(d, None) or []:
        if (Q.CGDisplayModeGetWidth(m), Q.CGDisplayModeGetHeight(m)) == tuple(want):
            err = Q.CGDisplaySetDisplayMode(d, m, None)
            log.info("Çözünürlük %sx%s yapıldı (hata kodu %s)", *want, err)
            return
    log.warning("Çözünürlük %sx%s bu ekranda yok", *want)


# ---------------------------------------------------------------- giriş olayları (fare / klavye)

KEYCODES = {
    "KeyA": 0, "KeyS": 1, "KeyD": 2, "KeyF": 3, "KeyH": 4, "KeyG": 5, "KeyZ": 6, "KeyX": 7,
    "KeyC": 8, "KeyV": 9, "IntlBackslash": 10, "KeyB": 11, "KeyQ": 12, "KeyW": 13, "KeyE": 14,
    "KeyR": 15, "KeyY": 16, "KeyT": 17, "Digit1": 18, "Digit2": 19, "Digit3": 20, "Digit4": 21,
    "Digit6": 22, "Digit5": 23, "Equal": 24, "Digit9": 25, "Digit7": 26, "Minus": 27,
    "Digit8": 28, "Digit0": 29, "BracketRight": 30, "KeyO": 31, "KeyU": 32, "BracketLeft": 33,
    "KeyI": 34, "KeyP": 35, "Enter": 36, "KeyL": 37, "KeyJ": 38, "Quote": 39, "KeyK": 40,
    "Semicolon": 41, "Backslash": 42, "Comma": 43, "Slash": 44, "KeyN": 45, "KeyM": 46,
    "Period": 47, "Tab": 48, "Space": 49, "Backquote": 50, "Backspace": 51, "Escape": 53,
    "MetaRight": 54, "MetaLeft": 55, "ShiftLeft": 56, "CapsLock": 57, "AltLeft": 58,
    "ControlLeft": 59, "ShiftRight": 60, "AltRight": 61, "ControlRight": 62,
    "NumpadDecimal": 65, "NumpadMultiply": 67, "NumpadAdd": 69, "NumLock": 71,
    "NumpadDivide": 75, "NumpadEnter": 76, "NumpadSubtract": 78, "NumpadEqual": 81,
    "Numpad0": 82, "Numpad1": 83, "Numpad2": 84, "Numpad3": 85, "Numpad4": 86, "Numpad5": 87,
    "Numpad6": 88, "Numpad7": 89, "Numpad8": 91, "Numpad9": 92,
    "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97, "F7": 98, "F8": 100,
    "F9": 101, "F10": 109, "F11": 103, "F12": 111, "Insert": 114, "Home": 115, "PageUp": 116,
    "Delete": 117, "End": 119, "PageDown": 121, "ArrowLeft": 123, "ArrowRight": 124,
    "ArrowDown": 125, "ArrowUp": 126,
}

MODIFIER_FLAGS = {
    "ShiftLeft": Q.kCGEventFlagMaskShift, "ShiftRight": Q.kCGEventFlagMaskShift,
    "ControlLeft": Q.kCGEventFlagMaskControl, "ControlRight": Q.kCGEventFlagMaskControl,
    "AltLeft": Q.kCGEventFlagMaskAlternate, "AltRight": Q.kCGEventFlagMaskAlternate,
    "MetaLeft": Q.kCGEventFlagMaskCommand, "MetaRight": Q.kCGEventFlagMaskCommand,
}

MOUSE = {  # js button -> (down, up, dragged, quartz button)
    0: (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGEventLeftMouseDragged, Q.kCGMouseButtonLeft),
    2: (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGEventRightMouseDragged, Q.kCGMouseButtonRight),
    1: (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, Q.kCGEventOtherMouseDragged, Q.kCGMouseButtonCenter),
}


class InputController:
    def __init__(self):
        self.src = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
        self.mods = set()
        self.buttons = set()
        self.click = {"t": 0.0, "b": None, "pos": (0, 0), "n": 0}

    def _flags(self):
        f = 0
        for code in self.mods:
            f |= MODIFIER_FLAGS[code]
        return f

    def _point(self, x, y):
        b = Q.CGDisplayBounds(Q.CGMainDisplayID())
        x = min(max(float(x), 0.0), 1.0)
        y = min(max(float(y), 0.0), 1.0)
        return (b.origin.x + x * (b.size.width - 1), b.origin.y + y * (b.size.height - 1))

    def _post(self, ev, flags=True):
        if flags:
            Q.CGEventSetFlags(ev, self._flags())
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def mouse_move(self, x, y):
        p = self._point(x, y)
        if self.buttons:
            b = min(self.buttons)
            kind, btn = MOUSE[b][2], MOUSE[b][3]
        else:
            kind, btn = Q.kCGEventMouseMoved, Q.kCGMouseButtonLeft
        self._post(Q.CGEventCreateMouseEvent(self.src, kind, p, btn))

    def mouse_button(self, b, down, x, y):
        if b not in MOUSE:
            return
        p = self._point(x, y)
        if down:
            c = self.click
            now = time.time()
            near = abs(p[0] - c["pos"][0]) < 5 and abs(p[1] - c["pos"][1]) < 5
            c["n"] = c["n"] + 1 if (c["b"] == b and near and now - c["t"] < 0.45) else 1
            c.update(t=now, b=b, pos=p)
            self.buttons.add(b)
        else:
            self.buttons.discard(b)
        kind = MOUSE[b][0] if down else MOUSE[b][1]
        ev = Q.CGEventCreateMouseEvent(self.src, kind, p, MOUSE[b][3])
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, self.click["n"])
        self._post(ev)

    def wheel(self, dx, dy):
        dy = int(max(min(-float(dy), 2000), -2000))
        dx = int(max(min(-float(dx), 2000), -2000))
        ev = Q.CGEventCreateScrollWheelEvent(self.src, Q.kCGScrollEventUnitPixel, 2, dy, dx)
        self._post(ev)

    def key(self, code, down):
        kc = KEYCODES.get(code)
        if kc is None:
            return
        if code in MODIFIER_FLAGS:
            (self.mods.add if down else self.mods.discard)(code)
        self._post(Q.CGEventCreateKeyboardEvent(self.src, kc, down))

    def type_text(self, s):
        s = str(s)[:2000]
        for ch in s:
            n = len(ch.encode("utf-16-le")) // 2
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(self.src, 0, down)
                Q.CGEventKeyboardSetUnicodeString(ev, n, ch)
                Q.CGEventSetFlags(ev, 0)
                Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def release_all(self):
        for code in list(self.mods):
            self.key(code, False)
        for b in list(self.buttons):
            loc = Q.CGEventGetLocation(Q.CGEventCreate(None))
            b_info = MOUSE[b]
            self._post(Q.CGEventCreateMouseEvent(self.src, b_info[1], loc, b_info[3]))
        self.buttons.clear()


INPUT = InputController()


def handle_input(m):
    t = m.get("t")
    if t == "mm":
        INPUT.mouse_move(m["x"], m["y"])
    elif t == "md":
        INPUT.mouse_button(int(m["b"]), True, m["x"], m["y"])
    elif t == "mu":
        INPUT.mouse_button(int(m["b"]), False, m["x"], m["y"])
    elif t == "wh":
        INPUT.wheel(m.get("dx", 0), m.get("dy", 0))
    elif t == "kd":
        INPUT.key(m["code"], True)
    elif t == "ku":
        INPUT.key(m["code"], False)
    elif t == "tx":
        INPUT.type_text(m["s"])


# ---------------------------------------------------------------- web

def _host_allowed(host):
    """DNS rebinding'e karşı: yalnızca IP adresi, localhost veya .local adlarıyla erişime izin ver."""
    name = host.rsplit(":", 1)[0].strip("[]").lower() if host else ""
    if name == "localhost" or name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@web.middleware
async def security(request, handler):
    # Yalnızca yerel ağdan gelen bağlantılar (192.168.x.x, 10.x.x.x, 172.16-31.x.x, localhost).
    try:
        ip = ipaddress.ip_address(request.remote or "")
    except ValueError:
        raise web.HTTPForbidden()
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not (ip.is_private or ip.is_loopback or ip.is_link_local):
        log.warning("Yerel ağ dışından erişim reddedildi: %s", ip)
        raise web.HTTPForbidden()
    if not _host_allowed(request.host):
        raise web.HTTPForbidden()
    # Başka bir siteden yapılan istekleri (CSRF / WebSocket ele geçirme) reddet.
    origin = request.headers.get("Origin")
    if (request.method != "GET" or request.path == "/ws") and origin != f"{SCHEME}://{request.host}":
        log.warning("Geçersiz Origin reddedildi: %s (%s)", origin, ip)
        raise web.HTTPForbidden()
    return await handler(request)


async def security_headers(request, response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' blob: data:; connect-src 'self' {'wss' if TLS else 'ws'}://{request.host}; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"


LOGIN_HTML = (STATIC / "login.html").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


async def index(request):
    if not valid_session(request):
        return web.Response(text=LOGIN_HTML, content_type="text/html")
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def login(request):
    ip = request.remote or "?"
    now = time.time()
    recent = [t for t in FAILS.get(ip, []) if now - t < 300]
    if len(recent) >= 5:
        return web.Response(status=429, text="Çok fazla hatalı deneme. 5 dakika sonra tekrar deneyin.")
    data = await request.post()
    if not check_password(CFG, data.get("password", "")):
        recent.append(now)
        FAILS[ip] = recent
        log.warning("Hatalı şifre denemesi: %s", ip)
        await asyncio.sleep(1)
        raise web.HTTPFound("/?hata=1")
    FAILS.pop(ip, None)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = now + SESSION_TTL
    save_sessions()
    log.info("Giriş başarılı: %s", ip)
    resp = web.HTTPFound("/")
    resp.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="Strict", secure=TLS)
    raise resp


async def logout(request):
    SESSIONS.pop(request.cookies.get(COOKIE), None)
    save_sessions()
    resp = web.HTTPFound("/")
    resp.del_cookie(COOKIE)
    raise resp


async def ca_cert(request):
    # Windows'a kurulacak yerel CA sertifikası (gizli değil; özel anahtar Mac'te kalır).
    return web.FileResponse(CERTS / "minirdp-ca.crt", headers={
        "Content-Type": "application/x-x509-ca-cert",
        "Content-Disposition": 'attachment; filename="minirdp-ca.crt"',
    })


async def clipboard_get(request):
    if not valid_session(request):
        raise web.HTTPUnauthorized()
    out = subprocess.run(["pbpaste"], capture_output=True, timeout=5).stdout
    return web.Response(text=out.decode("utf-8", "replace"))


async def clipboard_set(request):
    if not valid_session(request):
        raise web.HTTPUnauthorized()
    text = await request.text()
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=5)
    return web.Response(text="ok")


async def ws_handler(request):
    if not valid_session(request):
        raise web.HTTPUnauthorized()
    ws = web.WebSocketResponse(max_msg_size=1 << 20, heartbeat=20)
    await ws.prepare(request)
    log.info("Bağlantı açıldı: %s", request.remote)
    try:
        apply_resolution()
    except Exception:
        log.exception("Çözünürlük ayarlanamadı")

    state = {"credits": 2, "quality": CFG["quality"], "max_width": CFG["max_width"], "force": True}
    wake = asyncio.Event()
    wake.set()
    loop = asyncio.get_running_loop()

    async def sender():
        last = None
        while not ws.closed:
            await wake.wait()
            if state["credits"] <= 0:
                wake.clear()
                continue
            if state["force"]:
                last, state["force"] = None, False
            res = await loop.run_in_executor(_executor, capture, last, state["quality"], state["max_width"])
            if res is None:
                await asyncio.sleep(0.04)
                continue
            last, jpeg = res
            state["credits"] -= 1
            try:
                await ws.send_bytes(jpeg)
            except (ConnectionResetError, RuntimeError):
                break

    task = asyncio.create_task(sender())
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            t = m.get("t")
            if t == "ack":
                state["credits"] = min(state["credits"] + 1, 2)
                wake.set()
            elif t == "cfg":
                state["quality"] = int(min(max(int(m.get("quality", 60)), 10), 95))
                state["max_width"] = int(m.get("max_width", 0)) or 0
                state["force"] = True
                wake.set()
            else:
                try:
                    handle_input(m)
                except Exception:
                    log.exception("Giriş olayı işlenemedi: %s", m)
    finally:
        task.cancel()
        INPUT.release_all()
        log.info("Bağlantı kapandı: %s", request.remote)
    return ws


def check_permissions():
    try:
        if not Q.CGPreflightScreenCaptureAccess():
            log.warning("Ekran kaydı izni YOK - Sistem Ayarları > Gizlilik > Ekran Kaydı'ndan MiniRDP'ye izin verin.")
            Q.CGRequestScreenCaptureAccess()
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            log.warning("Erişilebilirlik izni YOK - Sistem Ayarları > Gizlilik > Erişilebilirlik'ten MiniRDP'ye izin verin.")
    except Exception:
        log.exception("İzin kontrolü yapılamadı")


def keep_awake():
    # Bu süreç çalıştığı sürece Mac'in uykuya geçmesini ve ekranın kapanmasını engeller.
    subprocess.Popen(["caffeinate", "-dis", "-w", str(os.getpid())])


def main():
    if "password_hash" not in CFG:
        raise SystemExit("Şifre ayarlanmamış. Önce: ./venv/bin/python set_password.py")
    check_permissions()
    keep_awake()
    app = web.Application(middlewares=[security], client_max_size=1 << 20)
    app.on_response_prepare.append(security_headers)
    app.add_routes([
        web.get("/", index),
        web.post("/login", login),
        web.get("/logout", logout),
        web.get("/ws", ws_handler),
        web.get("/clipboard", clipboard_get),
        web.post("/clipboard", clipboard_set),
        web.get("/minirdp-ca.crt", ca_cert),
    ])
    ctx = None
    if TLS:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(CERTS / "server.crt", CERTS / "server.key")
    log.info("MiniRDP dinliyor: %s://%s:%s", SCHEME, CFG["host"], CFG["port"])
    web.run_app(app, host=CFG["host"], port=CFG["port"], ssl_context=ctx, print=None, access_log=None)


if __name__ == "__main__":
    main()
