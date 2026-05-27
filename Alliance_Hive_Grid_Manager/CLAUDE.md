# Alliance Hive Grid Manager

Web tool for placing the 100 members of a *Last War Survival* alliance around either a **Marshall's Guard** event (3×3 tiles) or a **Military Stronghold** (21×21 tiles), assigning each member a tile coordinate so they can teleport into formation.

## Tech stack

- **Backend** — Python 3 stdlib `http.server` in `hive_server.py` (no extra deps). Port 8765 local, port from `$PORT` on Railway. Triggered by `python3 hive_server.py`.
- **Frontend** — single-file `hive_app.html`, vanilla JS, no build step.
- **Persistence** — `hive_config.json` (members, assignments, grid, layout mode). Auto-exported to `hive_members_export.csv` on every save.
- **License gating** — `keys.json` + Stripe webhook → emailed key (`HIVE-XXXX-XXXX`). Demo key: `HIVE-DEMO-2026`.

## Hosting

Live on **Railway**: `https://web-production-46ee1.up.railway.app` (the URL embedded in the license-email template). `RAILWAY_ENVIRONMENT` env var switches host to `0.0.0.0`.

## Layout modes (the core domain model)

The app supports two layout modes via a dropdown. Both share the same player object model — one member = a 3×3-tile footprint.

### Marshall's Guard (default, "mg")

- Center event = 3×3 tiles = 1 cell.
- Grid = 10×10 cells.
- Members butt directly against the MG and against each other (no gaps).
- 1 ring of members surrounds the MG; capacity ≈ ring distance × 8.

### Military Stronghold ("stronghold")

- Center fortress = 21×21 tiles = 7×7 cells.
- Members butt against the **mud** that surrounds the stronghold (Ring 1, the strongest players).
- **2 game tiles of empty space between every pair of alliance members**, in every direction, **and** between rings.
- **Corner-anchored ring algorithm**: each ring is a hollow rectangular frame whose four corners always hold a member. Inner edges are packed at pitch 5 (3-tile member + 2-tile gap) between the corners. The single inner→corner gap on each edge may shrink to 1 tile when the edge length doesn't divide evenly by 5 — accepted because a 1-tile gap is still too narrow for an enemy 3×3 footprint to teleport into. **Zero 3×3 empty zones anywhere in the layout.**
- Ring capacities (4 rings = 128 slots, room for 100 + 28 spare):

  | Ring | Distance from mud (tiles) | Slots |
  |------|---------------------------|-------|
  | 1    | 0 (against the mud)       | 20    |
  | 2    | 5 (3 member + 2 gap)      | 28    |
  | 3    | 10                        | 36    |
  | 4    | 15                        | 44    |
  | **Total** | —                  | **128** |

- Strongest player (R5 > R4 > … by total power) goes Ring 1, working outward.
- **Why it matters in-game**: any enemy who can land within 9 tiles of the mud can rally the stronghold. Spreading our members out with 2-tile gaps occupies more territory, denying enemies a teleport-and-rally landing pad. Corners must be plugged or an enemy can drop a 3×3 city into the gap.
- **Coordinate-key format**: in stronghold mode, `cfg["assignments"]` keys are `"tx,ty"` *tile* coords relative to the fortress centre (signed integers). MG mode uses `"col,row"` cell coords. The two key formats never coexist — `/api/set-layout` clears all assignments when the mode changes.

### Layout switching

- The **FORMATION** dropdown in the toolbar drives `/api/set-layout`. Switching modes wipes all placements (the coordinate systems don't translate). Member list and stats are preserved. User confirms via a JS `confirm()` before the switch.
- `/api/stronghold-slots` (GET) returns the canonical list of 128 ring slots for the frontend to render.

## Files

- `hive_server.py` — HTTP server, layout presets, auto-assign logic, Stripe webhook, CSV export.
- `hive_app.html` — single-page UI (grid, roster, modals, layout-mode dropdown, drag-drop, PNG export).
- `hive_config.json` — runtime state (gitignored alongside the example).
- `hive_config.example.json` — bootstrap default.
- `hive_members_export.csv` — generated on every save.
- `hive_grid.py` / `hive_grid.html` — older static generator versions (kept for reference, not the live tool).
- `hive_migrate.py` — one-off migration helper.
- `keys.json` — issued license keys (gitignored).
- `requirements.txt` — empty / stdlib only.

## Endpoints (POST unless noted)

- `GET /` — serve `hive_app.html`.
- `GET /api/config` — current config + layout.
- `GET /api/get-feedback` — collected user feedback.
- `/api/move`, `/api/assign`, `/api/edit`, `/api/unassign`, `/api/delete` — member operations.
- `/api/set-name` — alliance name.
- `/api/set-mg` — the **anchor tile coordinate** all member coordinates are offset from (defaults `{x:486, y:432}`).
- `/api/set-layout` `{mode: "mg" | "stronghold"}` — switch modes, resize grid, re-center anchor, evict any members that fall inside the new center block.
- `/api/auto` `{sort_by: "rank,power"}` — auto-assign members to rings (innermost first when sorting by rank).
- `/api/clear`, `/api/upload-csv`, `/api/unlock`, `/api/feedback`, `/api/stripe-webhook`.

## Conventions

- Grid coordinates `(col, row)` are cell-indexed; tile coordinates are derived (Marshall's Guard: cell × 3; Stronghold: more complex, see `_member_tile_offset` in server).
- The central block is always indexed by its center cell `(mg_col, mg_row)`. `_is_center()` checks membership; `_ring_dist()` returns Chebyshev distance from the outer edge of that block.
- "Strongest first" means: sort by `(rank, -power)` then fill rings inside-out.
