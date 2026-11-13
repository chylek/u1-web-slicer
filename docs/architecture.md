# Architecture

## Modules

| File | Role |
|---|---|
| `server.py` | HTTP server (stdlib `ThreadingHTTPServer`): REST API, SSE, static files, slicing jobs, zip import |
| `session.py` | The single source of truth: scene state, every edit operation (`Session.op`), undo history, profiles, colour plans, layout (arrange, prime tower) |
| `threemf.py` | Orca/Bambu 3MF parser and writer, STL import, primitives, plate grid maths |
| `paintree.py` | Orca `TriangleSelector` paint trees (`paint_color`): codec, subdivision, region painting |
| `colormix.py` | FilamentMixer pigment blend (same model as Snapmaker Orca), CIEDE2000, mix recipe search |
| `gcodeprev.py` | G-code to a compact binary toolpath for the layer preview |
| `thumbs.py` | Software renderer for the thumbnails embedded in the G-code |
| `printer.py` | Moonraker client: status, upload/print, camera keep-alive (minimal WebSocket client) |
| `mcp_server.py` | stdio MCP server; thin wrapper over the HTTP API |
| `config.py` | Environment / `.env` configuration |
| `static/` | Browser UI: `app.js` (three.js scene, panels, gizmo, painting, preview), `style.css`, generated JSON data |
| `tools/` | Generators for the JSON data in `static/` from a Snapmaker Orca source tree |

## State and persistence

`U1WEB_DATA/session/`:

- `state.json`: the current state (objects with 3MF row-vector matrices, filaments, mixes, prime tower,
  print-setting overrides, last slice result).
- `history.db`: SQLite table of state snapshots for undo/redo (depth 2000). Snapshots are small because geometry
  is referenced, not copied.
- `blobs/`: immutable geometry. `s-<shape>.pkl` holds a mesh once; `g-<gid>.pkl` holds part names and paint for a
  geometry id. Any edit to parts, paint or names produces a new gid (copy-on-write); unreferenced blobs are
  garbage-collected at start-up. `c-<hash>.json` are project config versions.
- `profiles.json`, `filaments.user.json`: the user's own presets (outside the undo history).
- `checkout/`: single-object 3MF exports locked for external editing (MCP `checkout_object`).

Slicing jobs live in `U1WEB_DATA/<job id>/` (`in.3mf`, `plate_1.gcode`, `result.json`, preview, thumbnail).

## Operations

Every mutation is `POST /api/op {"op": "<name>", ...}` handled by `Session.op`, which validates, applies,
re-checks the prime tower, records an undo snapshot with a readable label and broadcasts the new state to every
SSE listener. Objects checked out by an agent reject ops without the checkout token.

## HTTP API (summary)

| Method and path | Purpose |
|---|---|
| `GET /api/state`, `GET /api/events` | full state; SSE stream of state pushes |
| `GET /api/summary` | compact model-friendly view (used by MCP) |
| `GET /api/geo/<gid>`, `GET /api/paint/<gid>` | mesh (base64 float32) and paint for one geometry |
| `POST /api/op` | any edit operation |
| `POST /api/undo`, `/api/redo`, `GET /api/history` | history |
| `GET /api/files`, `POST /api/open`, `/api/new`, `/api/upload`, `/api/add`, `/api/add_path`, `/api/save` | projects and models |
| `POST /api/slice`, `GET /api/slice_progress`, `GET /job/<id>/...` | slicing, G-code, preview, thumbnail |
| `GET /api/profiles`, `POST /api/profiles/save`, `/api/profiles/delete` | print profiles |
| `GET /api/filaments`, `POST /api/filaments/save`, `/api/filaments/delete` | filament presets |
| `GET /api/colours/plan`, `/api/colours/used`, `/api/colours/palette` | colour mapping and mixing |
| `GET /api/printer`, `/api/printer/camera.jpg`, `POST /api/printer/sync`, `/api/printer/send` | printer |

## Orca specifics worth knowing

- The CLI needs a writable `--datadir` and `HOME` (both under `U1WEB_DATA`), and `--allow-newer-file`.
- Each plate is sliced as its own one-plate 3MF; the U1 prints plates one after another.
- An object floating above the bed makes Orca fail with an "empty layer" error, so the server checks first.
- Mixed filaments are rows in `mixed_filament_definitions`; their virtual filament ids follow the physical ones.
- Flow-variant filament keys are interleaved per `filament_flow_step_size` (see `session.filament_preset`).
