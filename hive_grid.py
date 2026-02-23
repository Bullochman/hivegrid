#!/usr/bin/env python3
"""
Last War Survival – Alliance Hive Grid Manager
================================================
Manages a 10×10 city grid around the Marshall's Guard (MG).
Each city occupies a 3×3 tile block; coordinates step by 3.

USAGE
  python3 hive_grid.py                        simple 10×10 grid (default)
  python3 hive_grid.py detail                 10×10 grid showing 3×3 tile footprints
  python3 hive_grid.py coords                 coordinate map (no names)
  python3 hive_grid.py list                   list all members and their positions
  python3 hive_grid.py assign NAME COL ROW    assign member to cell (0-indexed)
  python3 hive_grid.py move   NAME COL ROW    alias for assign
  python3 hive_grid.py swap   NAME1 NAME2     swap two members' positions
  python3 hive_grid.py unassign NAME          remove member from grid
  python3 hive_grid.py auto                   auto-fill empty cells (rank → power)
  python3 hive_grid.py import FILE            update member list from CSV

NOTES
  • Grid is 10 cols × 10 rows (0-indexed).  MG sits at col=4, row=4.
  • Game coordinate: x = mg_x + (col - mg_col) × 3
                     y = mg_y + (row - mg_row) × 3
  • Requires: hive_config.json in the same directory.
"""

import json, csv, sys, math
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
DIR         = Path(__file__).parent
CONFIG_PATH = DIR / "hive_config.json"

# ── ANSI ───────────────────────────────────────────────────────────────────────
RST  = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"

RANK_COLOR = {
    "R5": "\033[95m",   # bright magenta (leader)
    "R4": "\033[93m",   # gold
    "R3": "\033[96m",   # cyan
    "R2": "\033[92m",   # green
    "R1": "\033[94m",   # blue
    "MG": "\033[91m",   # bright red
    "":   "\033[90m",   # dark gray
}
OUTER = "\033[97m"      # bright white for frame

# ── Config I/O ─────────────────────────────────────────────────────────────────
def load() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[error] Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)

def save(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Coordinate helpers ─────────────────────────────────────────────────────────
def coord(cfg, col, row):
    g = cfg["grid"]
    return (
        cfg["mg"]["x"] + (col - g["mg_col"]) * g["step"],
        cfg["mg"]["y"] + (row - g["mg_row"]) * g["step"],
    )

def chebyshev(cfg, col, row):
    g = cfg["grid"]
    return max(abs(col - g["mg_col"]), abs(row - g["mg_row"]))

def cell_key(col, row): return f"{col},{row}"

def who(cfg, col, row):
    return cfg["assignments"].get(cell_key(col, row))

def find(cfg, name):
    """Return (col, row) of member, or None."""
    nl = name.lower()
    for k, v in cfg["assignments"].items():
        if v.lower() == nl:
            c, r = k.split(",")
            return int(c), int(r)
    return None

def power_float(p):
    try:
        return float(str(p or 0).replace("M", "").strip())
    except (ValueError, TypeError):
        return 0.0

def rank_key(member_data):
    """Sort key: R5/R4 get inner-ring priority, then all members by power descending."""
    rank = member_data.get("rank", "")
    tier = 0 if rank in ("R5", "R4") else 1   # R5/R4 = tier 0, everyone else = tier 1
    return (tier, -power_float(member_data.get("power")))

# ── Simple view ────────────────────────────────────────────────────────────────
CW = 18   # visible cell width — wide enough for "Name (R4,29,54.8M)"

def member_tag(cfg, name):
    """Return '(RANK,HQ,POWER)' string for a member."""
    m  = cfg["members"].get(name, {})
    rk = m.get("rank") or "?"
    hq = m.get("hq")
    pw = m.get("power") or "—"
    hq_s = str(hq) if hq is not None else "—"
    return f"({rk},{hq_s},{pw})"

def render_simple(cfg):
    g    = cfg["grid"]
    cols, rows = g["cols"], g["rows"]
    mc,  mr    = g["mg_col"], g["mg_row"]
    H = "─" * CW

    print(f"\n{BOLD}{OUTER}  ◈  LAST WAR SURVIVAL — ALLIANCE HIVE GRID  ◈")
    print(f"  MG @ ({cfg['mg']['x']},{cfg['mg']['y']})   cols 0-{cols-1}   rows 0-{rows-1}   step = {g['step']}{RST}\n")
    print(f"{DIM}  Best viewed in a wide terminal (≥190 chars){RST}\n")

    def hbar(l, m, r):
        seg = m + H
        return f"{OUTER}{l}{H}{seg*(cols-1)}{r}{RST}"

    print(hbar("┌", "┬", "┐"))
    for row in range(rows):
        nline  = [f"{OUTER}│{RST}"]   # name line
        iline  = [f"{OUTER}│{RST}"]   # (RANK,HQ,POWER) line
        cline  = [f"{OUTER}│{RST}"]   # coordinate line
        for col in range(cols):
            x, y = coord(cfg, col, row)
            coord_s = f"({x},{y})"
            if col == mc and row == mr:
                c    = RANK_COLOR["MG"]
                n_d  = "*** MG ***"
                i_d  = f"({cfg['mg']['x']},{cfg['mg']['y']})"
                c_d  = "486, 432"
                nline.append(f"{c}{BOLD}{n_d:^{CW}}{RST}")
                iline.append(f"{c}{BOLD}{i_d:^{CW}}{RST}")
                cline.append(f"{c}{BOLD}{c_d:^{CW}}{RST}")
            else:
                name = who(cfg, col, row) or ""
                rk   = cfg["members"].get(name, {}).get("rank", "") if name else ""
                c    = RANK_COLOR.get(rk, RANK_COLOR[""])
                if name:
                    n_trunc = (name[:CW-1] + "…") if len(name) >= CW else name
                    tag     = member_tag(cfg, name)
                    t_trunc = (tag[:CW-1] + "…") if len(tag) >= CW else tag
                    nline.append(f"{c}{n_trunc:^{CW}}{RST}")
                    iline.append(f"{c}{t_trunc:^{CW}}{RST}")
                    cline.append(f"{DIM}{coord_s:^{CW}}{RST}")
                else:
                    nline.append(f"{DIM}{'·':^{CW}}{RST}")
                    iline.append(f"{DIM}{'─'*6:^{CW}}{RST}")
                    cline.append(f"{DIM}{coord_s:^{CW}}{RST}")
            nline.append(f"{OUTER}│{RST}")
            iline.append(f"{OUTER}│{RST}")
            cline.append(f"{OUTER}│{RST}")

        print("".join(nline))
        print("".join(iline))
        print("".join(cline))
        sep = "└" if row == rows-1 else "├"
        end = "┘" if row == rows-1 else "┤"
        mid = "┴" if row == rows-1 else "┼"
        print(hbar(sep, mid, end))

    print(f"\n  {BOLD}Rank colors:{RST} ", end="")
    for rank in ["R5","R4","R3","R2","R1","MG",""]:
        label = "Empty" if rank == "" else rank
        print(f"{RANK_COLOR[rank]}{BOLD}{label}{RST} ", end="")
    print()

# ── Detail view (3×3 sub-tiles) ────────────────────────────────────────────────
TW = 13   # inner tile visual width  (1+3+1+3+1+3+1)

def tile_lines(color, name, x, y):
    c  = color
    h  = "─" * 3
    dot, bl = " · ", "▓▓▓"
    ab = (name.replace(" ","")[:3] if name else "···").ljust(3)[:3]

    return [
        f"{c}┌{h}┬{h}┬{h}┐{RST}",
        f"{c}│{bl}│{bl}│{bl}│{RST}",
        f"{c}├{h}┼{h}┼{h}┤{RST}",
        f"{c}│{bl}│{BOLD}{ab}{RST}{c}│{bl}│{RST}",
        f"{c}├{h}┼{h}┼{h}┤{RST}",
        f"{c}│{bl}│{bl}│{bl}│{RST}",
        f"{c}└{h}┴{h}┴{h}┘{RST}",
        f"{c}{(name[:TW] if name else '─'*TW):^{TW}}{RST}",
        f"{DIM}{'('+str(x)+','+str(y)+')':^{TW}}{RST}",
    ]

def render_detail(cfg):
    g          = cfg["grid"]
    cols, rows = g["cols"], g["rows"]
    mc, mr     = g["mg_col"], g["mg_row"]
    OH = "━"

    def obar(l, m, r):
        seg = OH * TW
        return f"{OUTER}{l}{(seg+m)*(cols-1)}{seg}{r}{RST}"

    print(f"\n{BOLD}{OUTER}  ◈  LAST WAR SURVIVAL — ALLIANCE HIVE GRID (3×3 DETAIL)  ◈   MG @ ({cfg['mg']['x']},{cfg['mg']['y']}){RST}")
    print(f"{DIM}  ▓▓▓ = city tile footprint   centre abbrev = player initials{RST}\n")

    print(obar("┏","┳","┓"))
    for row in range(rows):
        tiles = []
        for col in range(cols):
            x, y = coord(cfg, col, row)
            if col == mc and row == mr:
                tiles.append(tile_lines(RANK_COLOR["MG"], "***MG***", x, y))
            else:
                name  = who(cfg, col, row) or ""
                rank  = cfg["members"].get(name, {}).get("rank", "") if name else ""
                color = RANK_COLOR.get(rank, RANK_COLOR[""])
                tiles.append(tile_lines(color, name, x, y))

        for li in range(9):     # 7 grid lines + name + coord
            parts = [f"{OUTER}┃{RST}"]
            for t in tiles:
                parts.append(t[li])
                parts.append(f"{OUTER}┃{RST}")
            print("".join(parts))

        if row < rows - 1:
            print(obar("┣","╋","┫"))
    print(obar("┗","┻","┛"))

    print(f"\n  {BOLD}Rank colors:{RST} ", end="")
    for rank in ["R5","R4","R3","R2","R1","MG",""]:
        label = "Empty" if rank == "" else rank
        print(f"{RANK_COLOR[rank]}{BOLD}{label}{RST} ", end="")
    print()

# ── Coordinate-only map ────────────────────────────────────────────────────────
def render_coords(cfg):
    g          = cfg["grid"]
    cols, rows = g["cols"], g["rows"]
    mc, mr     = g["mg_col"], g["mg_row"]
    CW2 = 10
    H2  = "─" * CW2

    print(f"\n{BOLD}{OUTER}  ◈  COORDINATE MAP  ◈   MG @ ({cfg['mg']['x']},{cfg['mg']['y']}){RST}\n")
    print(f"{OUTER}┌{H2}{'┬'+H2*(cols-1)}┐{RST}")

    for row in range(rows):
        line = [f"{OUTER}│{RST}"]
        for col in range(cols):
            x, y = coord(cfg, col, row)
            s    = f"({x},{y})"
            if col == mc and row == mr:
                line.append(f"{RANK_COLOR['MG']}{BOLD}{s:^{CW2}}{RST}")
            else:
                line.append(f"{DIM}{s:^{CW2}}{RST}")
            line.append(f"{OUTER}│{RST}")
        print("".join(line))
        sep = "└" if row == rows-1 else "├"
        end = "┘" if row == rows-1 else "┤"
        mid = "┴" if row == rows-1 else "┼"
        inner = (mid + H2) * (cols - 1)
        print(f"{OUTER}{sep}{H2}{inner}{end}{RST}")

# ── List members ───────────────────────────────────────────────────────────────
def cmd_list(cfg):
    g = cfg["grid"]
    # Reverse-map assignments: name → (col, row)
    pos_map = {}
    for k, v in cfg["assignments"].items():
        c, r = k.split(",")
        pos_map[v] = (int(c), int(r))

    assigned   = sorted(pos_map.keys(),  key=lambda n: chebyshev(cfg, *pos_map[n]))
    unassigned = [n for n in cfg["members"] if n not in pos_map]
    unassigned.sort(key=lambda n: rank_key(cfg["members"][n]))

    print(f"\n{BOLD}{OUTER}  ◈  MEMBER ASSIGNMENTS{RST}\n")
    print(f"  {'NAME':<22} {'RANK':<5} {'POWER':<8} {'COL':>4} {'ROW':>4}  COORD       DIST")
    print("  " + "─"*70)

    for name in assigned:
        col, row = pos_map[name]
        m   = cfg["members"].get(name, {})
        rk  = m.get("rank", "?")
        pw  = m.get("power") or "—"
        x, y = coord(cfg, col, row)
        dist = chebyshev(cfg, col, row)
        c = RANK_COLOR.get(rk, RANK_COLOR[""])
        print(f"  {c}{name:<22}{RST} {c}{rk:<5}{RST} {pw:<8} {col:>4} {row:>4}  ({x},{y})  ring {dist}")

    if unassigned:
        print(f"\n  {DIM}── Unassigned ──────────────────────────────{RST}")
        for name in unassigned:
            m  = cfg["members"][name]
            rk = m.get("rank", "?")
            pw = m.get("power") or "—"
            c  = RANK_COLOR.get(rk, RANK_COLOR[""])
            print(f"  {c}{name:<22}{RST} {c}{rk:<5}{RST} {pw:<8}")
    print()

# ── Assign / Move ──────────────────────────────────────────────────────────────
def cmd_assign(cfg, name, col, row):
    g = cfg["grid"]
    if not (0 <= col < g["cols"] and 0 <= row < g["rows"]):
        print(f"[error] ({col},{row}) out of range 0-{g['cols']-1} × 0-{g['rows']-1}")
        return False
    if col == g["mg_col"] and row == g["mg_row"]:
        print("[error] That cell is the MG.")
        return False
    # Remove from old cell if already placed
    old = find(cfg, name)
    if old:
        del cfg["assignments"][cell_key(*old)]
    # Warn if cell occupied
    occupant = who(cfg, col, row)
    if occupant:
        print(f"[warn] Cell ({col},{row}) was occupied by {occupant} — they are now unassigned.")
        del cfg["assignments"][cell_key(col, row)]
    cfg["assignments"][cell_key(col, row)] = name
    # Auto-add to members if unknown
    if name not in cfg["members"]:
        cfg["members"][name] = {"rank": "", "hq": None, "power": None, "notes": "added by assign"}
        print(f"[info] Added {name!r} to members with no rank/power — update manually.")
    x, y = coord(cfg, col, row)
    print(f"  ✓  {name} → col {col}, row {row}  ({x},{y})  ring {chebyshev(cfg,col,row)}")
    return True

# ── Swap ───────────────────────────────────────────────────────────────────────
def cmd_swap(cfg, n1, n2):
    p1, p2 = find(cfg, n1), find(cfg, n2)
    if not p1: print(f"[error] {n1!r} not on grid"); return False
    if not p2: print(f"[error] {n2!r} not on grid"); return False
    cfg["assignments"][cell_key(*p1)] = n2
    cfg["assignments"][cell_key(*p2)] = n1
    x1,y1 = coord(cfg,*p1); x2,y2 = coord(cfg,*p2)
    print(f"  ✓  Swapped: {n1} → ({x1},{y1})   {n2} → ({x2},{y2})")
    return True

# ── Unassign ───────────────────────────────────────────────────────────────────
def cmd_unassign(cfg, name):
    pos = find(cfg, name)
    if not pos:
        print(f"[info] {name!r} was not on the grid.")
        return
    del cfg["assignments"][cell_key(*pos)]
    print(f"  ✓  {name} removed from {pos}")

# ── Auto-assign ────────────────────────────────────────────────────────────────
def cmd_auto(cfg):
    """
    Two-pass placement:
      Pass 1 — R5/R4 members fill closest empty cells (5% buff ring priority)
      Pass 2 — Everyone else fills remaining cells by power descending
               (so top hitters regardless of rank get the next-closest spots)
    """
    g = cfg["grid"]
    assigned = set(cfg["assignments"].values())

    unassigned = [n for n in cfg["members"] if n not in assigned]
    if not unassigned:
        print("[info] All members are already assigned.")
        return

    # Split into priority tiers
    r4r5  = sorted([n for n in unassigned if cfg["members"][n].get("rank") in ("R5","R4")],
                   key=lambda n: -power_float(cfg["members"][n].get("power")))
    others = sorted([n for n in unassigned if n not in r4r5],
                    key=lambda n: -power_float(cfg["members"][n].get("power")))
    members_queue = r4r5 + others

    # Empty cells sorted by (ring, clockwise angle from top)
    empty_cells = []
    for c in range(g["cols"]):
        for r in range(g["rows"]):
            if cell_key(c, r) not in cfg["assignments"]:
                if not (c == g["mg_col"] and r == g["mg_row"]):
                    dist  = chebyshev(cfg, c, r)
                    angle = math.atan2(c - g["mg_col"], -(r - g["mg_row"]))
                    empty_cells.append((dist, angle, c, r))
    empty_cells.sort()

    count = 0
    for name, (_, _, c, r) in zip(members_queue, empty_cells):
        cfg["assignments"][cell_key(c, r)] = name
        x, y = coord(cfg, c, r)
        rk = cfg["members"][name].get("rank","?")
        pw = cfg["members"][name].get("power") or "—"
        print(f"  {RANK_COLOR.get(rk,'')}✓  {name:<22} {rk:<3} {pw:<8}{RST} → ring {chebyshev(cfg,c,r)}  ({x},{y})")
        count += 1

    leftover = len(members_queue) - count
    print(f"\n  Assigned {count} member(s)." + (f"  {leftover} member(s) have no cell — grid full." if leftover else ""))

# ── HTML export ────────────────────────────────────────────────────────────────
RANK_CSS = {
    "R5": "#DA8FFF",   # magenta  (leader)
    "R4": "#FFD700",   # gold
    "R3": "#00BFFF",   # cyan
    "R2": "#44DD66",   # green
    "R1": "#6699FF",   # blue
    "MG": "#FF5555",   # red
    "":   "#555555",   # empty
}

def _cell_html(cfg, col, row, mc, mr):
    """Return the HTML for one grid cell."""
    x, y = coord(cfg, col, row)
    if col == mc and row == mr:
        clr = RANK_CSS["MG"]
        return (
            f'<td class="cell mg">'
            f'<div class="cname" style="color:{clr}">★ MG ★</div>'
            f'<div class="cinfo" style="color:{clr}">{x},{y}</div>'
            f'<div class="ccoord" style="color:{clr}">Marshall\'s Guard</div>'
            f'</td>'
        )
    name = who(cfg, col, row) or ""
    if name:
        m   = cfg["members"].get(name, {})
        rk  = m.get("rank") or "?"
        hq  = m.get("hq")
        pw  = m.get("power") or "—"
        hqs = str(hq) if hq is not None else "—"
        clr = RANK_CSS.get(rk, RANK_CSS[""])
        tag = f"({rk},{hqs},{pw})"
        dist = chebyshev(cfg, col, row)
        bg  = "#1e1e2e" if dist == 1 else ("#1a1a2a" if dist == 2 else "#151520")
        return (
            f'<td class="cell" style="background:{bg}">'
            f'<div class="cname" style="color:{clr}">{name}</div>'
            f'<div class="cinfo" style="color:{clr}">{tag}</div>'
            f'<div class="ccoord">({x},{y})</div>'
            f'</td>'
        )
    else:
        return (
            f'<td class="cell empty">'
            f'<div class="cname">·</div>'
            f'<div class="cinfo">——</div>'
            f'<div class="ccoord">({x},{y})</div>'
            f'</td>'
        )

def render_html(cfg):
    g = cfg["grid"]
    cols, rows = g["cols"], g["rows"]
    mc, mr = g["mg_col"], g["mg_row"]
    out_path = DIR / "hive_grid.html"

    # Build table rows
    rows_html = []
    for row in range(rows):
        cells = "".join(_cell_html(cfg, col, row, mc, mr) for col in range(cols))
        rows_html.append(f"<tr>{cells}</tr>")
    table = "\n".join(rows_html)

    # Build member list sidebar
    pos_map = {}
    for k, v in cfg["assignments"].items():
        c, r = k.split(",")
        pos_map[v] = (int(c), int(r))

    list_rows = []
    assigned_sorted = sorted(pos_map, key=lambda n: (chebyshev(cfg, *pos_map[n]),
                                                       -power_float(cfg["members"].get(n,{}).get("power"))))
    for name in assigned_sorted:
        col2, row2 = pos_map[name]
        m   = cfg["members"].get(name, {})
        rk  = m.get("rank","?")
        pw  = m.get("power") or "—"
        x2, y2 = coord(cfg, col2, row2)
        dist = chebyshev(cfg, col2, row2)
        clr = RANK_CSS.get(rk, RANK_CSS[""])
        list_rows.append(
            f'<tr>'
            f'<td style="color:{clr};font-weight:bold">{name}</td>'
            f'<td style="color:{clr}">{rk}</td>'
            f'<td style="color:#aaa">{pw}</td>'
            f'<td style="color:#888">({x2},{y2})</td>'
            f'<td style="color:#666">ring {dist}</td>'
            f'</tr>'
        )
    sidebar = "\n".join(list_rows)

    legend_items = "".join(
        f'<span style="color:{RANK_CSS[r]};font-weight:bold;margin-right:14px">{r or "Empty"}</span>'
        for r in ["R5","R4","R3","R2","R1","MG",""]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Last War Survival – Alliance Hive Grid</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0d0d1a;
      color: #c0c0d0;
      font-family: 'Courier New', Courier, monospace;
      padding: 24px;
    }}
    h1 {{ color: #ffffff; font-size: 18px; margin-bottom: 4px; }}
    .subtitle {{ color: #888; font-size: 13px; margin-bottom: 16px; }}
    .legend {{ margin-bottom: 20px; font-size: 13px; }}
    .grid-wrap {{ overflow-x: auto; margin-bottom: 32px; }}
    table.grid {{
      border-collapse: collapse;
      border: 2px solid #ffffff44;
    }}
    table.grid td.cell {{
      border: 1px solid #333355;
      padding: 8px 10px;
      text-align: center;
      min-width: 130px;
      vertical-align: middle;
      background: #111122;
      transition: background 0.15s;
    }}
    table.grid td.cell:hover {{ background: #1a1a33 !important; }}
    table.grid td.cell.mg {{ background: #220000 !important; border: 2px solid #FF5555; }}
    table.grid td.cell.empty {{ opacity: 0.35; }}
    .cname {{ font-size: 13px; font-weight: bold; white-space: nowrap; }}
    .cinfo {{ font-size: 11px; margin-top: 2px; }}
    .ccoord {{ font-size: 10px; color: #666688; margin-top: 3px; }}
    h2 {{ color: #aaaacc; font-size: 15px; margin-bottom: 10px; }}
    table.members {{ border-collapse: collapse; width: 100%; max-width: 640px; font-size: 13px; }}
    table.members td {{ padding: 4px 10px; border-bottom: 1px solid #1a1a2a; }}
    table.members tr:hover td {{ background: #111122; }}
    .ts {{ color: #555; font-size: 11px; margin-top: 32px; }}
  </style>
</head>
<body>
  <h1>◈ LAST WAR SURVIVAL — ALLIANCE HIVE GRID ◈</h1>
  <div class="subtitle">
    MG @ ({cfg['mg']['x']},{cfg['mg']['y']}) &nbsp;|&nbsp;
    Grid: {cols}×{rows} &nbsp;|&nbsp;
    Step: {g['step']} tiles &nbsp;|&nbsp;
    Assigned: {len(cfg['assignments'])}/99
  </div>
  <div class="legend">Rank colors: {legend_items}</div>

  <div class="grid-wrap">
    <table class="grid">
      {table}
    </table>
  </div>

  <h2>Member Roster (by ring distance)</h2>
  <table class="members">
    <tr style="color:#666;font-size:11px">
      <td>NAME</td><td>RANK</td><td>POWER</td><td>COORD</td><td>DIST</td>
    </tr>
    {sidebar}
  </table>

  <div class="ts">Generated by hive_grid.py · Last War Survival Alliance Tool</div>
</body>
</html>"""

    with open(out_path, "w") as f:
        f.write(html)
    print(f"  ✓  Saved → {out_path}")
    import webbrowser
    webbrowser.open(out_path.as_uri())
    print("  ✓  Opened in your default browser.")

# ── Import CSV ─────────────────────────────────────────────────────────────────
def cmd_import(cfg, filepath):
    path = Path(filepath)
    if not path.exists():
        print(f"[error] File not found: {filepath}"); return

    added, updated = 0, 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name  = (row.get("Name") or "").strip()
            rank  = (row.get("Rank") or "").strip()
            hq    = row.get("HQ Lv.","").strip() or None
            power = row.get("Total Power","").strip() or None
            notes = row.get("Notes","").strip()
            if not name: continue
            if hq:
                try: hq = int(hq)
                except ValueError: hq = None
            if name in cfg["members"]:
                cfg["members"][name].update({"rank":rank,"hq":hq,"power":power,"notes":notes})
                updated += 1
            else:
                cfg["members"][name] = {"rank":rank,"hq":hq,"power":power,"notes":notes}
                added += 1

    print(f"  ✓  Import complete — {added} added, {updated} updated.")

# ── Main CLI ───────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    cmd  = args[0].lower() if args else "view"

    cfg = load()

    if cmd in ("view", ""):
        render_simple(cfg)

    elif cmd == "detail":
        render_detail(cfg)

    elif cmd == "coords":
        render_coords(cfg)

    elif cmd == "list":
        cmd_list(cfg)

    elif cmd in ("assign", "move"):
        if len(args) < 4:
            print("Usage: assign NAME COL ROW"); sys.exit(1)
        name = args[1]
        try: col, row = int(args[2]), int(args[3])
        except ValueError: print("[error] COL and ROW must be integers"); sys.exit(1)
        if cmd_assign(cfg, name, col, row):
            save(cfg)

    elif cmd == "swap":
        if len(args) < 3:
            print("Usage: swap NAME1 NAME2"); sys.exit(1)
        if cmd_swap(cfg, args[1], args[2]):
            save(cfg)

    elif cmd == "unassign":
        if len(args) < 2:
            print("Usage: unassign NAME"); sys.exit(1)
        cmd_unassign(cfg, args[1])
        save(cfg)

    elif cmd in ("auto", "auto-assign"):
        cmd_auto(cfg)
        save(cfg)

    elif cmd == "import":
        if len(args) < 2:
            print("Usage: import FILE.csv"); sys.exit(1)
        cmd_import(cfg, args[1])
        save(cfg)

    elif cmd in ("html", "web", "browser"):
        render_html(cfg)

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
