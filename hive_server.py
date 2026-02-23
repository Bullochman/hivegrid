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

import json, csv, sys, math, webbrowser, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Timer

DIR        = Path(__file__).parent
CONFIG     = DIR / "hive_config.json"
APP_HTML   = DIR / "hive_app.html"
EXPORT_CSV = DIR / "hive_members_export.csv"
PORT       = int(os.environ.get("PORT", 8765))
IS_HOSTED  = os.environ.get("RAILWAY_ENVIRONMENT") is not None

# Auto-create config from example if missing (first run on hosted server)
if not CONFIG.exists():
    example = DIR / "hive_config.example.json"
    if example.exists():
        import shutil
        shutil.copy(example, CONFIG)
        print(f"  [init] Created {CONFIG} from example")


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

        else:
            self.send_response(404); self.end_headers()

    # ── POST ───────────────────────────────────────────────────────────────────
    def do_POST(self):
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
            # Keys stored as a simple set — replace with DB lookup in hosted version
            VALID_KEYS = {"HIVE-DEMO-2026"}   # placeholder; real keys generated per purchase
            key = (data.get("key") or "").strip().upper()
            if key in VALID_KEYS:
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

        # ── /api/auto — two-pass auto-assign (R4/R5 inner rings, then power) ──
        elif self.path == "/api/auto":
            g = cfg["grid"]
            mc, mr = g["mg_col"], g["mg_row"]

            def cheby(c, r): return max(abs(c - mc), abs(r - mr))
            def ppow(p):
                try: return float(str(p or 0).replace("M","").strip())
                except: return 0.0

            assigned = set(cfg["assignments"].values())
            unassigned = [n for n in cfg["members"] if n not in assigned]

            r4r5   = sorted([n for n in unassigned if cfg["members"][n].get("rank") in ("R5","R4")],
                            key=lambda n: -ppow(cfg["members"][n].get("power")))
            others = sorted([n for n in unassigned if n not in r4r5],
                            key=lambda n: -ppow(cfg["members"][n].get("power")))
            queue = r4r5 + others

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
