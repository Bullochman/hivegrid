# Alliance Hive Grid Tool
### Last War Survival — Alliance Coordination Tool

A browser-based hive management tool for Last War Survival alliances. Upload your member roster, auto-assign positions by rank and power, drag and drop to fine-tune, and export a color-coded PNG to share in Discord or WhatsApp.

---

## Features

- **10×10 interactive grid** — drag and drop members between cells
- **Click-to-edit** — update name, rank, HQ level, power, and notes from any cell
- **Inline roster editing** — edit stats directly in the table without opening a modal
- **CSV upload** — import your member list from a spreadsheet
- **Auto-assign** — R4/R5 fill inner rings first (5% buff zone), then everyone else by power descending
- **PNG export** — color-coded grid image ready for Discord/WhatsApp
- **Sort roster** — by ring distance, rank, power, or name
- **Custom alliance name** — shows in the header and all exports
- **Set MG coordinates** — enter your actual Marshall's Guard game coordinates
- **Clear grid / Reset all** — start fresh anytime
- **No external dependencies** — pure Python standard library + vanilla JS

---

## Quick Start

**1. Copy the example config:**
```bash
cp hive_config.example.json hive_config.json
```

**2. Start the server:**
```bash
python3 hive_server.py
```

**3. Open your browser:**
```
http://localhost:8765
```

That's it. No pip installs. No Node. No database setup.

---

## CSV Format

Upload a CSV file with these columns (in any order, extra spaces trimmed automatically):

| Column | Required | Example |
|--------|----------|---------|
| `Member` or `Name` | ✅ | `KittyKitty` |
| `Rank` | ✅ | `R4` |
| `HQ Level` or `HQ Lv.` | ✅ | `28` |
| `Total Power` | ✅ | `54.2M` |
| `Notes` | optional | `scout` |

A blank template is available inside the tool via the **⬇ Download blank CSV template** button.

---

## Grid Coordinate System

- MG (Marshall's Guard) is the fixed anchor — default game coordinates: X:486, Y:432
- Each grid cell = 3 game tiles in each direction
- Formula: `game_x = mg_x + (col - 4) × 3`, `game_y = mg_y + (row - 4) × 3`
- Change your MG coordinates anytime with the **📍 Set MG Coords** button

---

## Auto-Assign Priority

1. **R5 and R4 members** fill Ring 1 (adjacent to MG) first — maximizes the 5% combat buff
2. **All other members** fill outward by total power descending — strongest hitters closest in
3. Existing placements are never moved — only unassigned members are placed

---

## Files

| File | Purpose |
|------|---------|
| `hive_server.py` | Python web server (port 8765) |
| `hive_app.html` | Full interactive single-page app |
| `hive_grid.py` | CLI tool (terminal grid view, batch commands) |
| `hive_migrate.py` | One-time CSV migration utility with rename support |
| `hive_config.json` | Your live data (gitignored — copy from example) |
| `hive_config.example.json` | Safe example config to get started |

---

## CLI Commands

```bash
python3 hive_grid.py              # view grid in terminal
python3 hive_grid.py list         # list all members + positions
python3 hive_grid.py auto         # auto-assign unplaced members
python3 hive_grid.py assign "Name" COL ROW
python3 hive_grid.py swap "Name1" "Name2"
python3 hive_grid.py unassign "Name"
```

---

## Roadmap

- [ ] Hosted multi-user version (each alliance gets a unique URL)
- [ ] Stripe $10 one-time unlock (removes watermark, enables custom branding)
- [ ] Read-only shareable link (`?view=1`)
- [ ] Layout presets (circle, diamond, line formations)
- [ ] Swap suggestions (flags weak placements, recommends swaps)
- [ ] Leader dashboard (upload once, whole alliance views)

---

## Built With

- Python 3 `http.server` (zero pip dependencies)
- Vanilla HTML/CSS/JavaScript
- Canvas API for PNG export
- HTML5 Drag and Drop API

---

*Built for Last War Survival alliance leaders who are tired of typing coordinates by hand.*
