#!/usr/bin/env python3
"""
Last War Survival – Alliance Hive Web Server
============================================
Run:  python3 hive_server.py
Then: http://localhost:8765  (opens automatically)
Press Ctrl+C to stop.

No extra packages needed — uses Python's built-in http.server.
All changes are saved to hive_config.json and exported to
hive_members_export.csv automatically.
"""

import json, csv, sys, math, webbrowser, os, hmac, hashlib, secrets, smtplib, ssl, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Timer

DIR        = Path(__file__).parent
CONFIG     = DIR / "hive_config.json"
APP_HTML   = DIR / "hive_app.html"
EXPORT_CSV = DIR / "hive_members_export.csv"
FEEDBACK   = DIR / "feedback.json"
KEYS_FILE  = DIR / "keys.json"
STATS_FILE = DIR / "stats.json"
PORT       = int(os.environ.get("PORT", 8765))
IS_HOSTED  = os.environ.get("RAILWAY_ENVIRONMENT") is not None

# Intentional demo key for Evan's Korean alliance — shared publicly with the
# alliance so they can unlock the tool for free. This is a deliberate gift,
# NOT a leaked developer key. Rotate this value if you ever stop wanting the
# freebie to be public. Rename via HIVE_DEMO_KEY env var without changing code.
KR_ALLIANCE_KEY = "HIVE-KR-ALLIANCE-2026"

# ── Access analytics ────────────────────────────────────────────────────────────
# Lightweight visit tracker — bucketed by day, keeps last 30 days in a JSON file.
# Not privacy-invasive: only stores a per-IP hash + first-see date + language
# preference. Enough to answer "how many people from KR loaded this today?"
_stats_cache = None
def _load_stats():
    global _stats_cache
    if _stats_cache is not None:
        return _stats_cache
    try:
        with open(STATS_FILE) as f:
            _stats_cache = json.load(f)
    except Exception:
        _stats_cache = {"days": {}, "total_loads": 0}
    return _stats_cache

def _save_stats():
    if _stats_cache is None:
        return
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(_stats_cache, f, indent=2)
    except Exception as e:
        print(f"[stats] Save failed: {e}")

def _record_visit(ip: str, lang: str, accept_lang: str = ""):
    """Record a page load. Hashes the IP for privacy."""
    s = _load_stats()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = s["days"].setdefault(today, {"loads": 0, "unique_ips": [], "langs": {}, "accept_langs": {}})
    day["loads"] += 1
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:12]
    if ip_hash not in day["unique_ips"]:
        day["unique_ips"].append(ip_hash)
    day["langs"][lang] = day["langs"].get(lang, 0) + 1
    if accept_lang:
        # Bucket by primary language tag (e.g. ko-KR → ko)
        primary = accept_lang.split(",")[0].split("-")[0].lower().strip()
        if primary:
            day["accept_langs"][primary] = day["accept_langs"].get(primary, 0) + 1
    s["total_loads"] += 1
    # Trim to last 30 days
    if len(s["days"]) > 30:
        for k in sorted(s["days"].keys())[:-30]:
            del s["days"][k]
    _save_stats()

# Auto-create config from example if missing (first run on hosted server)
if not CONFIG.exists():
    example = DIR / "hive_config.example.json"
    if example.exists():
        import shutil
        shutil.copy(example, CONFIG)
        print(f"  [init] Created {CONFIG} from example")

if not KEYS_FILE.exists():
    with open(KEYS_FILE, "w") as f:
        json.dump([], f)


# ── Layout presets ─────────────────────────────────────────────────────────────
# Marshall's Guard: 3×3 game tiles = 1 cell. Members butt against the MG, no gaps.
#                   Cell-grid model: positions are "col,row" in a 10×10 grid.
# Military Stronghold: 21×21 game tiles = 7×7 cells. 2 tiles of empty space
#                      between every member (in every direction). Strongest
#                      members butt directly against the stronghold mud (Ring 1).
#                      Tile-grid model: positions are "tile_x,tile_y" relative
#                      to the fortress *centre*. 4 rings × ~varied slot-count
#                      gives 120 total slots (room for 100 members + 20 spare).
LAYOUT_PRESETS = {
    "mg": {
        "label": "Marshall's Guard",
        "short": "MG",
        "use_tile_coords": False,
        "center_size":  1,        # cells the central object occupies
        "grid_size":   10,        # total grid dimension in cells
    },
    "stronghold": {
        "label": "Military Stronghold",
        "short": "Stronghold",
        "use_tile_coords": True,
        "center_tiles": 21,       # central fortress is 21×21 game tiles
        "member_size":   3,       # alliance member footprint = 3×3 tiles
        "gap_tiles":     2,       # 2-tile gap between members (and between rings)
        "max_rings":     4,       # 4 rings = ~120 slots (enough for 100 + spare)
        # Legacy cell-grid fields (vestigial, for code paths that still inspect them)
        "center_size":   7,
        "grid_size":    13,
    },
}

def _ensure_layout(cfg):
    """Backfill the layout field on configs created before stronghold mode."""
    if "layout" not in cfg:
        cfg["layout"] = {"mode": "mg"}
    mode = cfg["layout"].get("mode", "mg")
    if mode not in LAYOUT_PRESETS:
        mode = "mg"
        cfg["layout"]["mode"] = mode
    preset = LAYOUT_PRESETS[mode]
    # Copy preset fields onto cfg["layout"] so clients can read them in /api/config
    for k, v in preset.items():
        cfg["layout"][k] = v
    return cfg

def _center_half(cfg):
    """Half-extent of the central block in *its own unit* (cells for MG, tiles for stronghold).
    e.g. MG centre is 1 cell → half = 0;  Stronghold centre is 21 tiles → half = 10."""
    mode = cfg["layout"]["mode"]
    if LAYOUT_PRESETS[mode].get("use_tile_coords"):
        return (LAYOUT_PRESETS[mode]["center_tiles"] - 1) // 2
    return (LAYOUT_PRESETS[mode]["center_size"] - 1) // 2

def _is_center(cfg, c, r):
    """Does a member placed at (c, r) overlap the central block?
    MG mode: (c, r) are cell coords.  Stronghold mode: (c, r) are tile coords
    of the *top-left* of the member's 3×3 footprint, measured from fortress centre.
    """
    mode = cfg["layout"]["mode"]
    preset = LAYOUT_PRESETS[mode]
    if not preset.get("use_tile_coords"):
        g = cfg["grid"]
        h = _center_half(cfg)
        return abs(c - g["mg_col"]) <= h and abs(r - g["mg_row"]) <= h
    # Stronghold: tile-coord overlap check
    half   = (preset["center_tiles"] - 1) // 2
    member = preset["member_size"]
    return (c + member - 1 >= -half and c <= half and
            r + member - 1 >= -half and r <= half)

def _ring_dist(cfg, c, r):
    """Distance from the outer edge of the central block.
    1 = first ring, 2 = second ring, ...  0 = inside the centre.
    MG mode: cell-Chebyshev distance.
    Stronghold mode: ring number based on 2-tile-gap layout."""
    mode = cfg["layout"]["mode"]
    preset = LAYOUT_PRESETS[mode]
    if not preset.get("use_tile_coords"):
        g = cfg["grid"]
        h = _center_half(cfg)
        cheb = max(abs(c - g["mg_col"]), abs(r - g["mg_row"]))
        return max(0, cheb - h)
    # Stronghold: ring r occupies the tile band [half+1+(r-1)*pitch, half+(r-1)*pitch+member]
    # in whichever axis is dominant.
    half   = (preset["center_tiles"] - 1) // 2
    member = preset["member_size"]
    pitch  = member + preset["gap_tiles"]
    d = max(abs(c), abs(r))   # use top-left corner (lower-magnitude) of the member footprint
    # Recompute using the *outer* corner so a member straddling a ring sits in its ring:
    d_outer = max(abs(c) + (member-1) if c < 0 else abs(c + member - 1),
                  abs(r) + (member-1) if r < 0 else abs(r + member - 1))
    if d_outer <= half:
        return 0
    return ((d_outer - half - 1) // pitch) + 1


def stronghold_slot_list(preset=None):
    """Enumerate every alliance-member slot around the stronghold.
    Returns a list of (tile_x, tile_y, ring) tuples, ordered Ring 1 first.

    Strategy: each ring is a hollow rectangular frame. The four CORNERS of
    the frame each hold a member (anchored), then inner edge members are
    packed at the standard pitch (member + gap) between the corners. The
    final inner→corner gap may shrink to 1 tile when (frame length - corner
    width) % pitch ≠ 0 — that's acceptable because a 1-tile gap is still
    too narrow for an enemy 3×3 unit to teleport into. The pure 2-tile gap
    is preserved between all *inner* members within an edge.

    Slot ordering within a ring is designed for *partial fills* to look
    symmetric: emit the 4 corners first (so any partial ring still has
    anchored corners), then round-robin around the 4 edges (N → E → S → W)
    one inner-member-position at a time.
    """
    p = preset or LAYOUT_PRESETS["stronghold"]
    half   = (p["center_tiles"] - 1) // 2
    member = p["member_size"]
    gap    = p["gap_tiles"]
    pitch  = member + gap
    slots = []
    for r in range(1, p["max_rings"] + 1):
        inner = half + 1 + (r - 1) * pitch
        outer = inner + member - 1
        edge_first = -outer + pitch                # first inner-member position
        edge_last  = inner - member                # last inner-member position
        if edge_last >= edge_first:
            n_inner = (edge_last - edge_first) // pitch + 1
        else:
            n_inner = 0

        # 1) Four corners first (so even a *partial* ring fill anchors them).
        slots.append((-outer, -outer, r))   # NW
        slots.append(( inner, -outer, r))   # NE
        slots.append(( inner,  inner, r))   # SE
        slots.append((-outer,  inner, r))   # SW

        # 2) Round-robin across the 4 edges, alternating sides on each pass
        #    so partial fills stay visually balanced.
        for i in range(n_inner):
            # Walk inner positions from the corners *inward* (closest-to-corner
            # first), alternating between the two ends of each edge: helps the
            # outermost ring feel "anchored" when it's only partially filled.
            half_idx = i // 2
            from_far = (i % 2 == 1)
            pos = (n_inner - 1 - half_idx) if from_far else half_idx
            x = edge_first + pos * pitch
            slots.append((x, -outer, r))                  # N inner
            slots.append(( inner, x, r))                  # E inner
            slots.append((x,  inner, r))                  # S inner
            slots.append((-outer, x, r))                  # W inner

    return slots


# ── Config helpers ─────────────────────────────────────────────────────────────
def load_cfg():
    with open(CONFIG) as f:
        cfg = json.load(f)
    cfg = _ensure_layout(cfg)
    # Evict orphan stronghold assignments — slot positions that no longer exist
    # under the current ring algorithm (happens after a slot-algorithm change).
    if cfg["layout"].get("use_tile_coords"):
        valid_keys = {f"{tx},{ty}" for tx, ty, _ in stronghold_slot_list()}
        stale = [k for k in cfg["assignments"] if k not in valid_keys]
        if stale:
            for k in stale:
                del cfg["assignments"][k]
    return cfg

def save_cfg(cfg):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    _export_csv(cfg)

def _export_csv(cfg):
    order = {"R5": 0, "R4": 1, "R3": 2, "R2": 3, "R1": 4, "": 5}
    members = sorted(
        cfg["members"].items(),
        key=lambda x: (order.get(x[1].get("rank", ""), 5), x[0])
    )
    with open(EXPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Rank", "Name", "HQ Lv.", "Total Power", "Notes"])
        for name, m in members:
            w.writerow([
                m.get("rank") or "",
                name,
                m.get("hq") or "",
                m.get("power") or "",
                m.get("notes") or "",
            ])


# ── License key helpers ─────────────────────────────────────────────────────────
def load_keys() -> set:
    try:
        with open(KEYS_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_key(key: str) -> None:
    try:
        with open(KEYS_FILE) as f:
            keys = json.load(f)
    except Exception:
        keys = []
    if key not in keys:
        keys.append(key)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)

def generate_key() -> str:
    return f"HIVE-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"

def _verify_stripe_signature(raw_body: bytes, sig_header: str, secret: str) -> bool:
    try:
        parts = {k: v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p)}
        timestamp = parts.get("t", "")
        v1_sig = parts.get("v1", "")
        if not timestamp or not v1_sig:
            return False
        if abs(time.time() - int(timestamp)) > 300:
            return False
        signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, v1_sig)
    except Exception:
        return False

LICENSE_EMAIL = {
    "en": {
        "subject": "Your Alliance Hive Grid License Key",
        "body": (
            "Thank you for your purchase!\n\n"
            "Your license key is:\n\n"
            "    {key}\n\n"
            "To activate:\n"
            "  1. Open the Alliance Hive Grid tool\n"
            "  2. Click 'Unlock Full Version'\n"
            "  3. Paste the key above and click Unlock\n\n"
            "Tool URL: https://web-production-46ee1.up.railway.app\n\n"
            "Questions? Reply to this email.\n"
        ),
    },
    "ko": {
        "subject": "연맹 벌집 배치도 라이선스 키",
        "body": (
            "결제 감사합니다!\n\n"
            "라이선스 키:\n\n"
            "    {key}\n\n"
            "활성화 방법:\n"
            "  1. 연맹 벌집 배치도 사이트 열기\n"
            "  2. '정식 버전 잠금해제' 클릭\n"
            "  3. 위 키를 붙여넣고 잠금해제 클릭\n\n"
            "사이트 URL: https://web-production-46ee1.up.railway.app\n\n"
            "문의사항은 이 이메일에 답장해 주세요.\n"
        ),
    },
}

# Errors returned in JSON responses — sent to the client, so we localize.
ERROR_MSGS = {
    "en": {
        "invalid_move":      "Invalid move",
        "into_center":       "Cannot move into {label}",
        "name_required":     "Name required",
        "cell_is_center":    "That cell is part of the {label}",
        "invalid_key":       "Invalid key",
        "xy_int":            "x and y must be integers",
        "unknown_layout":    "Unknown layout: {mode}",
    },
    "ko": {
        "invalid_move":      "잘못된 이동",
        "into_center":       "{label} 안으로 이동할 수 없습니다",
        "name_required":     "이름이 필요합니다",
        "cell_is_center":    "이 셀은 {label}의 일부입니다",
        "invalid_key":       "유효하지 않은 키",
        "xy_int":            "x와 y는 정수여야 합니다",
        "unknown_layout":    "알 수 없는 배치: {mode}",
    },
}

# Central-block labels get their own translations (they surface inside error messages).
CENTER_LABEL = {
    "mg":         {"en": "Marshall's Guard", "ko": "원수 근위대"},
    "stronghold": {"en": "Military Stronghold", "ko": "군사 요새"},
}

def send_key_email(to_email: str, key: str, lang: str = "en") -> None:
    host  = os.environ.get("SMTP_HOST", "")
    port  = int(os.environ.get("SMTP_PORT", 587))
    user  = os.environ.get("SMTP_USER", "")
    pw    = os.environ.get("SMTP_PASS", "")
    frm   = os.environ.get("SMTP_FROM", user)
    if not (host and user and pw):
        print("[email] Warning: SMTP env vars not set — skipping email delivery")
        return
    if lang not in LICENSE_EMAIL:
        lang = "en"
    try:
        subject = LICENSE_EMAIL[lang]["subject"]
        body    = LICENSE_EMAIL[lang]["body"].format(key=key)
        # RFC 2047 encode subject so non-ASCII (Korean) doesn't break headers
        from email.header import Header
        encoded_subject = Header(subject, "utf-8").encode()
        msg = (
            f"From: {frm}\r\n"
            f"To: {to_email}\r\n"
            f"Subject: {encoded_subject}\r\n"
            f"MIME-Version: 1.0\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Transfer-Encoding: 8bit\r\n\r\n"
            f"{body}"
        )
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, pw)
            smtp.sendmail(frm, to_email, msg.encode("utf-8"))
        print(f"[email] Sent {lang} key {key} to {to_email}")
    except Exception as e:
        print(f"[email] Error sending to {to_email}: {e}")


# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Log every request so Railway logs show real traffic — but skip
        # noisy repeats from health checks / bots.
        msg = fmt % args
        if "GET /favicon.ico" in msg or "HEAD /" in msg:
            return
        ip = self._client_ip()
        print(f"[req] {ip} — {msg}")

    def _client_ip(self):
        """Get the real client IP — Railway/proxies inject X-Forwarded-For."""
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _lang(self):
        """Pick the client's UI language for error strings.
        The frontend sends X-Hive-Lang; fall back to Accept-Language."""
        hl = (self.headers.get("X-Hive-Lang") or "").lower().strip()
        if hl in ERROR_MSGS:
            return hl
        al = (self.headers.get("Accept-Language") or "").lower()
        return "ko" if al.startswith("ko") else "en"

    def _err(self, key, **fmt):
        lang = self._lang()
        msg = ERROR_MSGS[lang].get(key, ERROR_MSGS["en"][key])
        return msg.format(**fmt) if fmt else msg

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Stripe webhook ─────────────────────────────────────────────────────────
    def _handle_stripe_webhook(self):
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        if not webhook_secret:
            print("[webhook] Error: STRIPE_WEBHOOK_SECRET not set")
            self._send_json({"error": "Webhook secret not configured"}, status=500)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""

        sig_header = self.headers.get("Stripe-Signature", "")
        if not _verify_stripe_signature(raw_body, sig_header, webhook_secret):
            print("[webhook] Invalid signature")
            self._send_json({"error": "Invalid signature"}, status=400)
            return

        try:
            event = json.loads(raw_body)
        except Exception:
            self._send_json({"error": "Invalid JSON"}, status=400)
            return

        if event.get("type") == "checkout.session.completed":
            obj = event.get("data", {}).get("object", {})
            email = (
                (obj.get("customer_details") or {}).get("email")
                or obj.get("customer_email")
            )
            # Language routing: the frontend appends ?client_reference_id=<lang>
            # to the Stripe checkout URL, which Stripe passes through unchanged.
            client_ref = (obj.get("client_reference_id") or "").lower().strip()
            lang = client_ref if client_ref in ("en", "ko") else "en"
            key = generate_key()
            save_key(key)
            print(f"[webhook] Generated {lang} key {key} for order")
            if email:
                send_key_email(email, key, lang=lang)
            else:
                print("[webhook] Warning: no email found in checkout session")

        self._send_json({"ok": True})

    # ── GET ────────────────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            data = APP_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
            # Record page load for analytics (only actual page loads, not asset fetches)
            try:
                _record_visit(
                    self._client_ip(),
                    self._lang(),
                    self.headers.get("Accept-Language", ""),
                )
            except Exception as e:
                print(f"[stats] Failed to record visit: {e}")

        elif self.path == "/api/config":
            self._send_json(load_cfg())

        elif self.path == "/api/stats":
            # Public-safe analytics endpoint — shows aggregate counts, no raw IPs.
            s = _load_stats()
            days_out = {}
            for date, d in sorted(s["days"].items(), reverse=True):
                days_out[date] = {
                    "loads":        d["loads"],
                    "unique_ips":   len(d["unique_ips"]),
                    "langs":        d["langs"],
                    "accept_langs": d["accept_langs"],
                }
            self._send_json({
                "ok":          True,
                "total_loads": s["total_loads"],
                "days":        days_out,
            })

        elif self.path == "/api/stronghold-slots":
            slots = stronghold_slot_list()
            p = LAYOUT_PRESETS["stronghold"]
            self._send_json({
                "ok": True,
                "preset": p,
                "slots": [{"tx": tx, "ty": ty, "ring": r} for tx, ty, r in slots],
            })

        elif self.path == "/api/get-feedback":
            data = []
            if FEEDBACK.exists():
                try:
                    with open(FEEDBACK) as f:
                        data = json.load(f)
                except Exception:
                    data = []
            self._send_json({"ok": True, "count": len(data), "feedback": data})

        else:
            self.send_response(404); self.end_headers()

    # ── POST ───────────────────────────────────────────────────────────────────
    def do_POST(self):
        if self.path == "/api/stripe-webhook":
            self._handle_stripe_webhook()
            return

        data = self._read_json()
        cfg  = load_cfg()
        g    = cfg["grid"]
        mc, mr = g["mg_col"], g["mg_row"]
        mode = cfg["layout"]["mode"]
        # Localized central-block label (fall back to the English preset short name)
        center_label = CENTER_LABEL.get(mode, {}).get(self._lang(), cfg["layout"]["short"])

        # ── /api/move  {from: "col,row", to: "col,row"} ──────────────────────
        if self.path == "/api/move":
            src = data.get("from", "")
            dst = data.get("to", "")
            if not src or not dst or src == dst:
                self._send_json({"ok": False, "error": self._err("invalid_move")}); return
            sc, sr = map(int, src.split(","))
            dc, dr = map(int, dst.split(","))
            if _is_center(cfg, sc, sr) or _is_center(cfg, dc, dr):
                self._send_json({"ok": False, "error": self._err("into_center", label=center_label)}); return
            name_src = cfg["assignments"].pop(src, None)
            name_dst = cfg["assignments"].pop(dst, None)
            if name_src: cfg["assignments"][dst] = name_src
            if name_dst: cfg["assignments"][src] = name_dst
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/assign  {name, col, row} ─────────────────────────────────────
        elif self.path == "/api/assign":
            name = (data.get("name") or "").strip()
            col  = int(data.get("col", 0))
            row  = int(data.get("row", 0))
            if not name:
                self._send_json({"ok": False, "error": self._err("name_required")}); return
            if _is_center(cfg, col, row):
                self._send_json({"ok": False, "error": self._err("cell_is_center", label=center_label)}); return
            # remove from old position
            for k, v in list(cfg["assignments"].items()):
                if v == name: del cfg["assignments"][k]; break
            cfg["assignments"][f"{col},{row}"] = name
            if name not in cfg["members"]:
                cfg["members"][name] = {"rank": "", "hq": None, "power": None, "notes": ""}
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/edit  {old_name, name, rank, hq, power, notes} ──────────────
        elif self.path == "/api/edit":
            old  = (data.get("old_name") or "").strip()
            new  = (data.get("name")     or "").strip()
            rank = (data.get("rank")     or "").strip()
            pw   = (data.get("power")    or "").strip() or None
            note = (data.get("notes")    or "").strip()
            hq_r = data.get("hq")
            try:   hq = int(hq_r) if hq_r not in (None, "") else None
            except: hq = None

            if not new:
                self._send_json({"ok": False, "error": self._err("name_required")}); return

            # find current grid position of old member
            pos_key = next((k for k, v in cfg["assignments"].items() if v == old), None)

            # remove old entry
            if old and old in cfg["members"]:
                del cfg["members"][old]

            # write updated entry
            cfg["members"][new] = {"rank": rank, "hq": hq, "power": pw, "notes": note}

            # update assignment key if name changed
            if pos_key and old != new:
                cfg["assignments"][pos_key] = new

            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/unassign  {name} ─────────────────────────────────────────────
        elif self.path == "/api/unassign":
            name = (data.get("name") or "").strip()
            for k, v in list(cfg["assignments"].items()):
                if v == name: del cfg["assignments"][k]; break
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/delete  {name} — remove member entirely ─────────────────────
        elif self.path == "/api/delete":
            name = (data.get("name") or "").strip()
            for k, v in list(cfg["assignments"].items()):
                if v == name: del cfg["assignments"][k]; break
            cfg["members"].pop(name, None)
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/set-name  {alliance_name} ───────────────────────────────────
        elif self.path == "/api/set-name":
            name = (data.get("alliance_name") or "").strip()
            cfg["alliance_name"] = name
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/unlock  {key} — validate license key ─────────────────────────
        elif self.path == "/api/unlock":
            key = (data.get("key") or "").strip().upper()
            valid_keys = load_keys()
            # KR alliance demo key — intentional public share (see top of file).
            valid_keys.add(KR_ALLIANCE_KEY)
            # Admin escape hatch: env var for a second, non-source-controlled key
            # you can rotate on Railway without redeploying.
            demo = (os.environ.get("HIVE_DEMO_KEY") or "").strip().upper()
            if demo:
                valid_keys.add(demo)
            if key in valid_keys:
                cfg["unlocked"] = True
                save_cfg(cfg)
                self._send_json({"ok": True, "config": cfg})
            else:
                self._send_json({"ok": False, "error": self._err("invalid_key")})

        # ── /api/set-mg  {x, y} — move the MG anchor point ──────────────────
        elif self.path == "/api/set-mg":
            try:
                new_x = int(data.get("x", cfg["mg"]["x"]))
                new_y = int(data.get("y", cfg["mg"]["y"]))
            except (ValueError, TypeError):
                self._send_json({"ok": False, "error": self._err("xy_int")}); return
            cfg["mg"]["x"] = new_x
            cfg["mg"]["y"] = new_y
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/feedback  {name, votes: [...], comment} ─────────────────────
        elif self.path == "/api/feedback":
            name    = (data.get("name")    or "Anonymous").strip()[:60]
            votes   = [str(v)[:40] for v in (data.get("votes") or []) if isinstance(v, str)]
            comment = (data.get("comment") or "").strip()[:500]
            entry   = {"ts": int(time.time()), "name": name, "votes": votes, "comment": comment}
            existing = []
            if FEEDBACK.exists():
                try:
                    with open(FEEDBACK) as f:
                        existing = json.load(f)
                except Exception:
                    existing = []
            existing.append(entry)
            with open(FEEDBACK, "w") as f:
                json.dump(existing, f, indent=2)
            self._send_json({"ok": True})

        # ── /api/clear  — wipe all assignments (keep members) ────────────────
        elif self.path == "/api/clear":
            mode = data.get("mode", "assignments")   # "assignments" or "all"
            cfg["assignments"] = {}
            if mode == "all":
                cfg["members"] = {}
            save_cfg(cfg)
            self._send_json({"ok": True, "config": cfg})

        # ── /api/upload-csv — parse CSV upload, merge into members ───────────
        elif self.path == "/api/upload-csv":
            import io
            csv_text = data.get("csv", "")
            rank_order_map = {"R5": 0, "R4": 1, "R3": 2, "R2": 3, "R1": 4}
            def ppow(p):
                try: return float(str(p or 0).replace("M","").strip())
                except: return 0.0

            reader = csv.DictReader(io.StringIO(csv_text))
            # normalize headers
            if reader.fieldnames:
                reader.fieldnames = [k.strip().rstrip(":") for k in reader.fieldnames]

            added, updated = 0, 0
            for row in reader:
                name  = (row.get("Member") or row.get("Name") or "").strip()
                rank  = (row.get("Rank") or "").strip()
                hq_s  = (row.get("HQ Level") or row.get("HQ Lv.") or "").strip()
                power = (row.get("Total Power") or "").strip() or None
                notes = (row.get("Notes") or "").strip()
                if not name: continue
                try: hq = int(hq_s)
                except: hq = None
                entry = {"rank": rank, "hq": hq, "power": power, "notes": notes}
                if name in cfg["members"]:
                    # Only overwrite if new rank is higher or same rank with more power
                    prev = cfg["members"][name]
                    ro_new  = rank_order_map.get(rank, 5)
                    ro_prev = rank_order_map.get(prev.get("rank",""), 5)
                    if ro_new < ro_prev or (ro_new == ro_prev and ppow(power) >= ppow(prev.get("power"))):
                        cfg["members"][name] = entry
                    updated += 1
                else:
                    cfg["members"][name] = entry
                    added += 1

            save_cfg(cfg)
            self._send_json({"ok": True, "added": added, "updated": updated, "config": cfg})

        # ── /api/set-layout {mode: "mg" | "stronghold"} ──────────────────────
        elif self.path == "/api/set-layout":
            mode = (data.get("mode") or "").strip().lower()
            if mode not in LAYOUT_PRESETS:
                self._send_json({"ok": False, "error": self._err("unknown_layout", mode=mode)}); return
            preset = LAYOUT_PRESETS[mode]
            prev_mode = cfg.get("layout", {}).get("mode", "mg")
            cfg["layout"] = {"mode": mode}
            new_size = preset["grid_size"]
            cfg["grid"]["cols"]   = new_size
            cfg["grid"]["rows"]   = new_size
            cfg["grid"]["mg_col"] = new_size // 2
            cfg["grid"]["mg_row"] = new_size // 2
            cfg["grid"]["step"]   = 3
            cfg = _ensure_layout(cfg)
            evicted = 0
            # Switching modes swaps the entire coordinate system → clear all placements.
            if prev_mode != mode:
                evicted = len(cfg["assignments"])
                cfg["assignments"] = {}
            else:
                # Same mode, just re-anchored — evict only placements now inside the centre.
                for k in list(cfg["assignments"].keys()):
                    try:
                        c, r = map(int, k.split(","))
                    except ValueError:
                        del cfg["assignments"][k]; evicted += 1; continue
                    if _is_center(cfg, c, r):
                        del cfg["assignments"][k]; evicted += 1
            save_cfg(cfg)
            self._send_json({"ok": True, "evicted": evicted, "config": cfg})

        # ── /api/auto — auto-assign with configurable sort priority ──────────
        elif self.path == "/api/auto":
            g = cfg["grid"]
            mc, mr = g["mg_col"], g["mg_row"]

            def cheby(c, r): return _ring_dist(cfg, c, r)
            def ppow(p):
                try: return float(str(p or 0).replace("M","").strip())
                except: return 0.0

            sort_by = (data.get("sort_by") or "rank,power").strip()
            fields  = [s.strip() for s in sort_by.split(",") if s.strip()]
            RANK_ORD = {"R5": 0, "R4": 1, "R3": 2, "R2": 3, "R1": 4}

            def make_key(name):
                m = cfg["members"][name]
                key = []
                for f in fields:
                    if f == "rank":
                        key.append(RANK_ORD.get(m.get("rank", ""), 5))
                    elif f == "hq":
                        try: hq = int(m.get("hq") or 0)
                        except: hq = 0
                        key.append(-hq)
                    elif f == "power":
                        key.append(-ppow(m.get("power")))
                return key

            assigned   = set(cfg["assignments"].values())
            unassigned = [n for n in cfg["members"] if n not in assigned]

            # Two-pass only when rank is the primary field: R4/R5 fill inner rings first
            if fields and fields[0] == "rank":
                r4r5   = sorted([n for n in unassigned if cfg["members"][n].get("rank") in ("R5","R4")],
                                key=make_key)
                others = sorted([n for n in unassigned if n not in set(r4r5)],
                                key=make_key)
                queue = r4r5 + others
            else:
                queue = sorted(unassigned, key=make_key)

            mode = cfg["layout"]["mode"]
            if LAYOUT_PRESETS[mode].get("use_tile_coords"):
                # Stronghold: the canonical slot list is already ordered for
                # symmetric partial-ring fills (corners first, then N/E/S/W
                # round-robin). Just walk it in order.
                empty = []
                for tx, ty, ring in stronghold_slot_list():
                    k = f"{tx},{ty}"
                    if k not in cfg["assignments"]:
                        empty.append((tx, ty))
                placed = 0
                for name, (tx, ty) in zip(queue, empty):
                    cfg["assignments"][f"{tx},{ty}"] = name
                    placed += 1
            else:
                empty = []
                for c in range(g["cols"]):
                    for r in range(g["rows"]):
                        k = f"{c},{r}"
                        if k not in cfg["assignments"] and not (c == mc and r == mr):
                            empty.append((cheby(c,r), math.atan2(c-mc, -(r-mr)), c, r))
                empty.sort()
                placed = 0
                for name, (_, _, c, r) in zip(queue, empty):
                    cfg["assignments"][f"{c},{r}"] = name
                    placed += 1

            save_cfg(cfg)
            self._send_json({"ok": True, "placed": placed, "config": cfg})

        else:
            self.send_response(404); self.end_headers()


# ── Entry point ────────────────────────────────────────────────────────────────
def run():
    if not APP_HTML.exists():
        print(f"[error] Missing {APP_HTML}  — run this from ~/claudecode/")
        sys.exit(1)

    host = "0.0.0.0" if IS_HOSTED else "localhost"
    url  = f"http://localhost:{PORT}" if not IS_HOSTED else f"https://${{RAILWAY_STATIC_URL}}"

    print(f"\n  ◈  Alliance Hive Grid — Web Server")
    print(f"  URL  : {url}")
    print(f"  JSON : {CONFIG}")
    print(f"  Port : {PORT}  |  Hosted: {IS_HOSTED}")
    print(f"\n  Press Ctrl+C to stop.\n")

    if not IS_HOSTED:
        Timer(0.6, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        HTTPServer((host, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")


if __name__ == "__main__":
    run()
