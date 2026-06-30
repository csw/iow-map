# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rule

**Never edit `iow-map.html` or `index.html` directly** — both are generated. All changes go into `tools/corrections.py` (graph fixes) or `tools/app_template.html` (UI changes), then rebuild.

## Build Commands

```bash
uv sync                                                    # install deps (first time)
uv run python tools/build_all.py                           # full rebuild (needs maps/)
uv run python tools/build_all.py --skip-extract            # HTML only, from existing graphs/
uv run python tools/build_all.py --maps east_reef          # rebuild specific map(s)
uv run python tools/build_all.py --overlay-dir overlays/   # save debug overlays
```

## Architecture

### Data flow

```
maps/*.jpg → extract_graph.py → graphs/*.json → corrections.py → app_template.html → iow-map.html / index.html
```

`build_all.py` orchestrates this: it calls `extract_graph.py` as a subprocess per map, then applies corrections and resolves metadata in-process, then injects everything into `app_template.html` via a `/* __MAPS_DATA__ */` placeholder.

### corrections.py — the source of truth

Everything human-verified lives here:

- `EXTRACTION_CONFIG` — per-map seed color, threshold, epsilon, merge radius, triangle detection toggle
- `MAP_METADATA` — labels, entry nodes, game start position; all as **pixel coordinates** (not vertex indices), resolved at build time
- `apply_corrections(map_key, verts_px, edges, w, h)` — per-map fix functions using `_remove_vertex_near()` and `_add_edge_between()` helpers
- `KNOWN_ISSUES` — documented problems that aren't yet fixed

Pixel coordinates survive re-extraction because vertex indices can change; coordinates don't.

### HTML app (iow-map.html / index.html)

Single-file app embedded in `app_template.html`:
- SVG pan/zoom with `viewBox`
- Fog-of-war via SVG mask (white circles at visited vertex positions)
- State persisted to `localStorage` keyed `iow_<map_key>`
- 30-deep undo stack (in-memory)
- `iow-map.html` uses S3 URLs for map images; `index.html` uses relative `maps/` paths (GitHub Pages)

### tools/label-viewer.html

Standalone visual overlay tool for verifying label placements. Open in a browser pointing at a map image to check that label pixel coordinates in `corrections.py` align with the actual map.

## Adding Graph Corrections

1. Run with `--overlay-dir` to get a numbered vertex overlay image
2. Identify spurious vertices or missing edges visually
3. Add `_remove_vertex_near(verts_px, edges, (x, y))` or `_add_edge_between(verts_px, edges, (x1,y1), (x2,y2))` calls inside the relevant `_correct_<map_key>()` function in `corrections.py`
4. Rebuild with `--skip-extract` to verify

## Known Issues (from corrections.py)

- **east_reef**: creature dot clusters (same red as graph lines) create spurious vertices near Petal Shoot, Shed Feather, Silken Strands — needs manual `_remove_vertex_near` pass
- **brine_pool**: most label assignments are wrong; triangle detection disabled (creature blobs cause false positives)
- **the_bloom_main**: missing edges north of Fan Stem
