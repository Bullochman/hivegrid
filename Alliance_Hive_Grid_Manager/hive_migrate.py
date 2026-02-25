#!/usr/bin/env python3
"""
hive_migrate.py  —  Apply updated CSV to hive_config.json
Handles:
  • Flexible CSV column names (Member/Name, HQ Level/HQ Lv., Total Power:/Total Power)
  • In-place renames that preserve grid positions
  • Departed members removed from grid and member list
  • New members added as unassigned
  • Deduplication (highest rank wins; on tie, highest power wins)
Run once:  python3 hive_migrate.py
"""

import json, csv
from pathlib import Path

DIR    = Path(__file__).parent
CONFIG = DIR / "hive_config.json"
CSV    = Path("/Users/evanjones/Downloads/01-23-26 Updated Alliance Hive Details UPDATED.csv")

# ── Known renames: old config name → new CSV name ─────────────────────────────
RENAMES = {
    "KittijKittij":      "KittyKitty",
    "Becccsss":          "Beccss",
    "AuntyAnne":         "Aunty Anne",
    "SofaKingBrokenToe": "SoftaKingBrokenToe",
    "DonQuixoteRosi":    "DonQuixoteRosinante1",
    "HUCKLEBERRY 1":     "Huckleberry",
    "FruityB":           "FuityB",
    "Cocopop88":         "Cocopop808",
    "1CrazzyWolf":       "1CrazyWolf",
    "Rubix01":           "Rubid01",
    "D1ngle":            "D1NGLE",
    "Over W8 Ninja":     "OverW8Ninja",
    "AmanduhBanananuh":  "AmanduhBananuh",
    "MayorMudFart":      "MaryMudFart",
    "Brains out":        "BrainsOut",
    "DerpyLlama5300":    "Derpyllama5300",
    "SettlerGASM":       "SettlerGasm",
    "Ree the destroyed": "Ree the Destroyed",
    "Sticky socks":      "sticky s0ckz",
    "Cleo":              "Cleo333",
    "SurvivvHer":        "SurvivHer",
    "Greenlynn13":       "Grennlynn13",
    "Skyosz":            "Sykosz",
    "EliasSanchez11":    "Elias Sanchez",
    "JinJaburu":         "Jinjaburu",
    "WV guy":            "WVGuy",
    "RiverWild":         "Riverwild",
    "buraktr":           "Buraktr",
    "DJTonnyBr":         "DJTonnyBR",
    "imbroed101":        "imbored101",
    "biggity":           "Biggity",
    "Nosunrise":         "nosunrise",
    "stephham919":       "Stephham919",
    "Dottie Hinson":     "DottieHinson",
    "Evan M J":          "Evan M J",     # unchanged
    "FiyahDude":         "FiyahDude",    # unchanged, rank updated in CSV
    "Rodrigo RC":        "Rodrigo RC",   # unchanged, rank changed R3→R2
}

# ── Members who left the alliance — remove from grid + member list ─────────────
DEPARTED = [
    "Syyosz",
    "Comandante 21d3f2007",
    "DeadZoneX",
]

def rank_order(r):
    return {"R5": 0, "R4": 1, "R3": 2, "R2": 3, "R1": 4}.get(r, 5)

def parse_power(p):
    try:    return float(str(p or "0").replace("M", "").strip())
    except: return 0.0

def load_csv(path):
    """Parse CSV with flexible column names; deduplicate by highest rank, then highest power."""
    best = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize header keys (strip whitespace and trailing colons)
        reader.fieldnames = [k.strip().rstrip(":") for k in reader.fieldnames]
        for row in reader:
            # Try multiple possible column name variants
            name  = (row.get("Member") or row.get("Name") or "").strip()
            rank  = (row.get("Rank")   or "").strip()
            hq_s  = (row.get("HQ Level") or row.get("HQ Lv.") or "").strip()
            power = (row.get("Total Power") or "").strip() or None
            if not name: continue
            try:   hq = int(hq_s)
            except: hq = None
            entry = {"rank": rank, "hq": hq, "power": power}
            if name not in best:
                best[name] = entry
            else:
                prev = best[name]
                ro_new  = rank_order(rank)
                ro_prev = rank_order(prev["rank"])
                if ro_new < ro_prev:
                    best[name] = entry
                elif ro_new == ro_prev:
                    if parse_power(power) > parse_power(prev["power"]):
                        best[name] = entry
    return best

def main():
    cfg = json.loads(CONFIG.read_text())
    csv_data = load_csv(CSV)

    members     = cfg["members"]
    assignments = cfg["assignments"]

    # ── 1. Remove departed members ───────────────────────────────────────────
    removed = []
    for name in DEPARTED:
        if name in members:
            del members[name]
            removed.append(name)
        # Also unassign from grid
        for k, v in list(assignments.items()):
            if v == name:
                del assignments[k]
                print(f"  [departed] Removed '{name}' from grid cell {k}")
    if removed:
        print(f"  [departed] Removed {len(removed)} departed member(s): {', '.join(removed)}")

    # ── 2. Apply in-place renames ────────────────────────────────────────────
    for old, new in RENAMES.items():
        if old == new: continue   # skip no-ops
        # Update grid assignments
        for k, v in list(assignments.items()):
            if v == old:
                assignments[k] = new
                print(f"  [rename] grid {k}: '{old}' → '{new}'")
        # Merge member record
        old_data = members.pop(old, {})
        if new not in members:
            members[new] = old_data

    # ── 3. Apply CSV data to all matching names ──────────────────────────────
    updated, added = 0, 0
    for name, entry in csv_data.items():
        if name in members:
            members[name].update(entry)
            updated += 1
        else:
            members[name] = dict(entry, notes="")
            added += 1

    # ── 4. Report members in config not found in new CSV (may have left) ────
    csv_names  = set(csv_data.keys())
    unmatched  = [n for n in members if n not in csv_names]
    if unmatched:
        print(f"\n  [warn] {len(unmatched)} member(s) still in config but NOT in new CSV:")
        for n in sorted(unmatched):
            print(f"         • {n}  ← consider removing if they left the alliance")

    cfg["members"]     = members
    cfg["assignments"] = assignments
    CONFIG.write_text(json.dumps(cfg, indent=2))

    print(f"\n  ✓  Removed  {len(removed)} departed member(s)")
    print(f"  ✓  Updated  {updated} existing members")
    print(f"  ✓  Added    {added} new members")
    print(f"  ✓  Total members in config: {len(members)}")
    print(f"  ✓  Saved → {CONFIG}")

if __name__ == "__main__":
    main()
