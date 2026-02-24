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
PORT       = int(os.environ.get("PORT", 8765))
IS_HOSTED  = os.environ.get("RAILWAY_ENVIRONMENT") is not None

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


# ── Config helpers ─────────────────────────────────────────────────────────────
def load_cfg():
    with open(CONFIG) as f:
        return json.load(f)

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

def send_key_email(to_email: str, key: str) -> None:
    host  = os.environ.get("SMTP_HOST", "")
    port  = int(os.environ.get("SMTP_PORT", 587))
    user  = os.environ.get("SMTP_USER", "")
    pw    = os.environ.get("SMTP_PASS", "")
    frm   = os.environ.get("SMTP_FROM", user)
    if not (host and user and pw):
        print("[email] Warning: SMTP env vars not set — skipping email delivery")
        return
    try:
        subject = "Your Alliance Hive Grid License Key"
        body = (
            f"Thank you for your purchase!\n\n"
            f"Your license key is:\n\n"
            f"    {key}\n\n"
            f"To activate:\n"
            f"  1. Open the Alliance Hive Grid tool\n"
            f"  2. Click 'Unlock Full Version'\n"
            f"  3. Paste the key above and click Unlock\n\n"
            f"Tool URL: https://web-production-46ee1.up.railway.app\n\n"
            f"Questions? Reply to this email.\n"
        )
        msg = f"From: {frm}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, pw)
            smtp.sendmail(frm, to_email, msg.encode("utf-8"))
        print(f"[email] Sent key {key} to {to_email}")
    except Exception as e:
        print(f"[email] Error sending to {to_email}: {e}")


# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass   # silence access log

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

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
            key = generate_key()
            save_key(key)
            print(f"[webhook] Generated key {key} for order")
            if email:
                send_key_email(email, key)
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

        elif self.path == "/api/config":
            self._send_json(load_cfg())

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

        # ── /api/move  {from: "col,row", to: "col,row"} ──────────────────────
        if self.path == "/api/move":
            src = data.get("from", "")
            dst = data.get("to", "")
            if not src or not dst or src == dst:
                self._send_json({"ok": False, "error": "Invalid move"}); return
            sc, sr = map(int, src.split(","))
            dc, dr = map(int, dst.split(","))
            if (sc == mc and sr == mr) or (dc == mc and dr == mr):
                self._send_json({"ok": False, "error": "Cannot move MG"}); return
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
                self._send_json({"ok": False, "error": "Name required"}); return
            if col == mc and row == mr:
                self._send_json({"ok": False, "error": "That cell is MG"}); return
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
                self._send_json({"ok": False, "error": "Name required"}); return

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
            valid_keys.add("HIVE-DEMO-2026")   # demo key stays hardcoded, not in file
            if key in valid_keys:
                cfg["unlocked"] = True
                save_cfg(cfg)
                self._send_json({"ok": True, "config": cfg})
            else:
                self._send_json({"ok": False, "error": "Invalid key"})

        # ── /api/set-mg  {x, y} — move the MG anchor point ──────────────────
        elif self.path == "/api/set-mg":
            try:
                new_x = int(data.get("x", cfg["mg"]["x"]))
                new_y = int(data.get("y", cfg["mg"]["y"]))
            except (ValueError, TypeError):
                self._send_json({"ok": False, "error": "x and y must be integers"}); return
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

        # ── /api/auto — auto-assign with configurable sort priority ──────────
        elif self.path == "/api/auto":
            g = cfg["grid"]
            mc, mr = g["mg_col"], g["mg_row"]

            def cheby(c, r): return max(abs(c - mc), abs(r - mr))
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
