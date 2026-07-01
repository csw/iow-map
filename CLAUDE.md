# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rule

**Never edit `index.html` directly** — it is generated. All changes go into `tools/corrections.py` (graph fixes) or `tools/app_template.html` (UI changes), then rebuild.

## Build Commands

```bash
uv sync              # install deps (first time)
just build           # HTML only, from existing graphs/ -- use this after template/corrections edits
just build-all       # full rebuild (needs maps/)
```

Equivalent raw commands (see `justfile`), for cases `just` doesn't cover:

```bash
uv run python tools/build.py                           # full rebuild (needs maps/)
uv run python tools/build.py --skip-extract            # HTML only, from existing graphs/
uv run python tools/build.py --maps east_reef          # rebuild specific map(s)
uv run python tools/build.py --overlay-dir overlays/   # save debug overlays
```

## Architecture

### Data flow

```
maps/*.jpg → extract_graph.py → graphs/*.json → corrections.py → vertex_ids.py → app_template.html → index.html
```

`build.py` orchestrates this: it calls `extract_graph.py` as a subprocess per map, then applies corrections and reconciles stable vertex IDs in-process, resolves metadata, then injects everything into `app_template.html` via a `/* __MAPS_DATA__ */` placeholder.

### corrections.py — the source of truth

Everything human-verified lives here:

- `EXTRACTION_CONFIG` — per-map seed color, threshold, epsilon, merge radius, triangle detection toggle
- `MAP_METADATA` — labels, entry nodes, game start position; all as **pixel coordinates** (not vertex indices), resolved at build time
- `apply_corrections(map_key, verts_px, edges, w, h)` — per-map fix functions using `_remove_vertex_near()` and `_add_edge_between()` helpers
- `RETIRED_VERTICES` — indices retired via `_retire_vertex_near()` (see below), documented per map
- `KNOWN_ISSUES` — documented problems that aren't yet fixed

Pixel coordinates survive re-extraction because vertex indices can change; coordinates don't.

### tools/vertex_ids.py — stable vertex identity (app is deployed — indices are load-bearing)

The deployed app stores each player's fog-of-war progress in `localStorage` keyed by **vertex array index**. That means vertex indices can never shift between builds, or every existing player's saved progress silently points at the wrong vertex.

- `graphs/<map>_vertex_ids.json` — **committed, durable** snapshot of pixel coordinates per stable index (not regenerable from the map image alone). This is the anchor.
- `reconcile_stable_ids()` runs after `apply_corrections()` on every build. It fuzzy-matches the fresh (verts_px, edges) against the snapshot by nearest pixel coordinate (within `MAX_DIST=25px`) so every vertex keeps its existing index even if extraction reorders things (param tweaks, library upgrades, minor image edits).
  - Matched vertices: keep their index, coordinate refreshed.
  - New vertices: appended with a brand new index — never reuses a retired/tombstoned one.
  - Vertices missing from the fresh extraction: index kept and tombstoned (dead), never reused. Prints a loud `WARNING` — treat this as a signal to investigate before committing, since a real vertex vanishing is usually a bug.
- Removing a vertex on purpose (spurious extraction artifact)? Use **`_retire_vertex_near()`** in corrections.py, not `_remove_vertex_near()` — the latter renumbers every subsequent vertex and is only safe pre-deployment. Register the retirement in `RETIRED_VERTICES`.
- Dead/tombstoned vertices (from either mechanism) are auto-detected in `build.py` (degree-0 after corrections, or reconciliation's dead list) and passed to the app as `D:[...]`; `app_template.html` excludes them from the visited-count denominator and permanently hides/disables them as click targets.

### HTML app (index.html)

Single-file app embedded in `app_template.html`:
- SVG pan/zoom with `viewBox`
- Fog-of-war via SVG mask (white circles at visited vertex positions)
- State persisted to `localStorage` keyed `iow_<map_key>`
- 30-deep undo stack (in-memory)
- Uses relative `maps/` paths for map images (GitHub Pages)

### tools/label-viewer.html

Standalone visual overlay tool for verifying label placements. Open in a browser pointing at a map image to check that label pixel coordinates in `corrections.py` align with the actual map.

## Adding Graph Corrections

1. Run with `--overlay-dir` to get a numbered vertex overlay image
2. Identify spurious vertices or missing edges visually
3. Add `_retire_vertex_near(verts_px, edges, (x, y))` (removes a spurious vertex without renumbering — see vertex_ids.py above) or `_add_edge_between(verts_px, edges, (x1,y1), (x2,y2))` calls inside the relevant `_correct_<map_key>()` function in `corrections.py`. Register any retirement in `RETIRED_VERTICES`.
4. Rebuild with `--skip-extract` to verify. Watch the output for `WARNING` lines from `vertex_ids.py` — a vertex unexpectedly vanishing means something needs review before committing.

## Known Issues (from corrections.py)

- **east_reef**: creature dot clusters (same red as graph lines) create spurious vertices near Petal Shoot, Shed Feather, Silken Strands — needs manual `_remove_vertex_near` pass
