# Architecture: The Graph Pipeline

This explains how a map screenshot becomes an interactive, fog-of-war-tracked
graph in the deployed app, and why the pipeline is shaped the way it is. See
`CLAUDE.md` for terse build commands; this doc is the human-readable version.

## Data flow

```
maps/*.jpg
  → extract_graph.py    (image → raw vertices/edges)
  → graphs/*.json        (raw extraction output, regenerable)
  → corrections.py       (human-verified fixes + metadata)
  → vertex_ids.py         (re-index against durable per-map snapshot)
  → app_template.html    (JS/CSS template with a data placeholder)
  → index.html            (generated, single-file app — never hand-edit)
```

`tools/build.py` orchestrates all of this. `--skip-extract` reuses the
existing `graphs/*.json` and re-runs everything downstream — the fast path
for template or corrections edits. Without that flag it re-runs extraction
from `maps/*.jpg` first (slow, and requires the map images, which aren't
committed — see below).

## Why a pipeline instead of hand-drawn graphs

The maps are screenshots of the in-game map screen, with paths drawn in a
distinct raster color (red, gold, or blue depending on the map). Every
traversable location is a point on that raster network, so the graph can be
extracted algorithmically instead of traced by hand — but the algorithm
gets some things wrong (see below), so a correction layer sits on top.

## 1. Extraction (`extract_graph.py`)

For each map, given a seed color and threshold:

1. **Fuzzy color select** — pixels within `threshold` of the seed color
   (Euclidean in RGB) are masked in. Some maps need two seed colors
   (`the_anomaly_lower_level` mixes red corridors with a gold segment).
2. **Skeletonize** — the color mask is thinned to 1px-wide centerlines.
3. **Triangle marker detection** (optional, `detect_triangles`) — the game
   draws small solid triangles at junctions/points of interest. These get
   detected by shape (contour solidity/size filters) and treated as
   vertices in their own right, since skeletonization alone tends to blur
   a triangle into a blob rather than a clean point. Disabled on maps
   where the triangle color is too close to the line color to
   distinguish (`dusk_slopes`) or where creature art blobs would be
   false positives (`brine_pool`, prior to shape filtering).
4. **Vertex placement** — skeleton branch points and endpoints become
   candidate vertices; Douglas-Peucker simplification (`epsilon`)
   collapses near-straight runs of skeleton pixels down to their
   endpoints, and nearby candidates within `merge_radius` px are merged.
5. **Edge validation** — a candidate edge is kept only if the straight
   line between its two vertices has good raster-pixel coverage in the
   color mask (rejects false connections from simplification artifacts).

Extraction is deterministic for a fixed image + fixed
`EXTRACTION_CONFIG` + fixed library versions, but it isn't perfect. Two
recurring failure modes drive most of the correction work:

- **Spurious vertices**: art elements that share the line's color
  (creature dots/blobs, decorative ticks) get picked up as skeleton
  branch points, or a single junction gets split into 2-3 near-duplicate
  vertices a few px apart, each carrying only some of the junction's
  edges.
- **Missing edges**: `validate_edges()` sometimes rejects a real edge
  because a dot cluster or label connector line sitting on top of the
  raster reduces its measured coverage below threshold.

Two scripts (in `.claude/skills/verify-map-labels/scripts/`) help surface
these for human review: `find_duplicate_vertices.py` flags close,
unconnected vertex pairs; `find_missing_edges.py` flags raster components
with no covering edge. Both are detection-only — every hit needs visual
triage, since real triangle markers, creature dots, and label connector
lines are all plausible false positives.

Per-map extraction parameters live in `EXTRACTION_CONFIG` in
`corrections.py`, alongside notes on why each map's settings are what they
are.

## 2. Corrections (`corrections.py`)

This is the source of truth for everything a human has verified. The
design principle: extraction should be safely re-runnable from scratch at
any time, so no manual fix ever touches `extract_graph.py` or the
`graphs/*.json` files directly — it's all applied in memory, at build
time, by `apply_corrections()`.

- **`EXTRACTION_CONFIG`** — per-map seed color(s), threshold, epsilon,
  merge radius, triangle-detection toggle.
- **`_correct_<map_key>()`** functions — one per map needing fixes, each
  a short, commented sequence of `_add_edge_between()`,
  `_remove_vertex_near()`/`_retire_vertex_near()`, and
  `_remove_edge_between()` calls, keyed by **pixel coordinates**, not
  vertex indices. Coordinates survive re-extraction; indices can shift
  (extraction reorders things depending on iteration order, which isn't
  guaranteed stable across parameter or library changes). Each function's
  docstring records *why* the fix is needed — usually which detector
  found it and what visual artifact caused it — so a future re-review
  doesn't have to rediscover the reasoning from scratch.
- **`MAP_METADATA`** — labels, entry nodes (`EN`), game-start position
  (`GS`), fog radius (`FR`), all as pixel coordinates. Resolved to vertex
  indices at build time by `resolve_labels()`/`resolve_en()`/
  `resolve_gs()`, which snap each coordinate to its nearest vertex
  (within a max distance, to catch typos/drift rather than silently
  matching something far away).
- **`RETIRED_VERTICES`** — a human-readable log of vertices retired via
  `_retire_vertex_near()` (see below) — not itself load-bearing, just
  documentation of what was retired and why.
- **`KNOWN_ISSUES`** — documented problems that aren't fixed yet.

### Removing a vertex: two different tools, not interchangeable

- **`_remove_vertex_near()`** deletes a vertex outright and renumbers
  every vertex after it. This is only safe for maps that have never been
  deployed with real player data against that vertex numbering — see
  below for why. Most historical corrections use this because they
  predate the deployed app storing per-vertex state.
- **`_retire_vertex_near()`** bridges the vertex's neighbors directly
  (same topological fix) but leaves the vertex's array slot in place,
  edgeless — it becomes a permanently dead/hidden node rather than
  disappearing. Use this for **any new correction now that the app is
  deployed**. Register the retirement in `RETIRED_VERTICES`.

## 3. Stable vertex identity (`vertex_ids.py`)

This is the piece that exists purely because the app is live and people
have saved progress.

**The constraint:** the deployed app stores each player's fog-of-war
progress in browser `localStorage`, keyed by **vertex array index**
(`iow_<map_key>` → a set of visited indices, plus current position, notes,
etc.). If a rebuild changes which array index corresponds to which
physical location — because a vertex got removed and everything after it
shifted down, or because extraction happened to produce vertices in a
different order — every existing player's saved progress silently starts
pointing at the wrong nodes. There's no way to migrate this after the
fact, because the previous index→location mapping isn't recoverable once
it's gone. So: **vertex indices must never shift, and a retired index must
never be reused.**

Raw extraction order isn't guaranteed to satisfy that on its own — it's
only stable for a truly unchanged image + config + library versions.
Tweaking `EXTRACTION_CONFIG`, upgrading scikit-image, or touching the
source map image could all reorder vertices coming out of
`extract_graph.py`. `corrections.py`'s coordinate-based lookups still find
the *right vertex* in that case, but the *index* it ends up at could
differ from a previous build.

**The fix:** each map has a committed, durable identity ledger,
`graphs/<map_key>_vertex_ids.json` — a JSON array of `[x, y]` pixel
coordinates (or `null` for a tombstoned slot), one entry per stable index.
This file is **not regenerable from the map image**; it's the actual
source of truth for "which index is this vertex," and unlike
`graphs/*_graph.json` (raw, disposable extraction output) it must be
committed to git.

Every build, after `apply_corrections()` runs, `reconcile_stable_ids()`
takes the fresh `(verts_px, edges)` and fuzzy-matches every vertex against
the snapshot by nearest pixel coordinate (within `MAX_DIST=25px` — safely
under the extraction's own `merge_radius` of 30px, so it won't accidentally
conflate two distinct nearby vertices):

- **Matched** — a fresh vertex within range of a snapshot entry keeps that
  entry's index (coordinate refreshed to the new value, which may drift a
  few px between runs). Matching is greedy-exclusive: candidate pairs are
  sorted by distance and claimed in that order, so the closest match wins
  and no index or fresh vertex is claimed twice.
- **New** — a fresh vertex with no snapshot match nearby is genuinely new
  and gets appended at a brand new index (`len(snapshot)`, `len(snapshot)+1`,
  ...) — never a retired one.
- **Disappeared** — a snapshot entry with no matching fresh vertex keeps
  its index reserved and tombstoned (marked dead, coordinate zeroed to
  `null`) rather than being reused. This prints a loud `WARNING` at build
  time — a previously-real vertex vanishing is unusual enough that it's
  worth reviewing before committing (did the map image change? did a
  parameter change unexpectedly drop a real vertex?), even though the
  mechanism itself handles it safely either way.

The very first time a map is built with this system, there's no snapshot
yet — `reconcile_stable_ids()` just writes the current `(verts_px)` out
as the initial snapshot verbatim ("bootstrap"), so introducing the system
doesn't itself change any already-deployed index.

**Practical upshot:** once a vertex has ever been shipped in `index.html`,
its index is permanent. Retiring a spurious vertex uses
`_retire_vertex_near()`, not `_remove_vertex_near()`, precisely so that
retirement plays by the same "index is permanent" rule as everything else.

## 4. Dead vertices, end to end

A vertex can end up "dead" (kept in the array, excluded from the app) two
ways: retired on purpose via `_retire_vertex_near()`, or tombstoned
automatically because it vanished from extraction. `build.py` computes the
final dead list per map as the union of:

- any vertex with degree 0 after corrections (catches both retirement
  paths, since both leave the vertex edgeless), and
- `reconcile_stable_ids()`'s own disappeared list (belt-and-suspenders, in
  case a vertex vanished from extraction but a stale edge referencing it
  slipped through corrections).

That list is emitted as `D:[...]` per map in the generated JS. In the app
(`app_template.html`), dead indices are excluded from the visited-count
denominator and are hidden/non-interactive as click targets — they simply
don't render.

## 5. The HTML app (`index.html` / `app_template.html`)

Single-file app, generated by substituting a `const MAPS = {...}` block
(built from all maps' vertices, edges, labels, dead lists, and metadata)
into a `/* __MAPS_DATA__ */` placeholder in `app_template.html`.

- SVG pan/zoom via `viewBox`.
- Fog-of-war is an SVG mask: visited vertices punch white circles into an
  otherwise opaque overlay.
- State persists to `localStorage` under `iow_<map_key>`: visited-vertex
  set, current position, notes, fog toggle.
- 30-deep in-memory undo stack.
- Map images load via relative `maps/` paths (GitHub Pages hosting; see
  below on why images aren't committed).

## Adding a new correction

1. Rebuild with `--overlay-dir <dir>` to get a numbered vertex overlay
   image for visual inspection, or run the two detector scripts
   mentioned above.
2. Identify the spurious vertex or missing edge, and its pixel
   coordinates.
3. Add `_retire_vertex_near(verts_px, edges, (x, y))` (for a spurious
   vertex) or `_add_edge_between(verts_px, edges, (x1,y1), (x2,y2))` (for
   a missing edge) inside the map's `_correct_<map_key>()` function in
   `corrections.py`. Register any retirement in `RETIRED_VERTICES`.
4. Rebuild with `--skip-extract` to verify, and watch the output for
   `WARNING` lines from `vertex_ids.py` — an unexpected tombstone means
   something needs review before committing.

## Map images

The map JPEGs (`maps/*.jpg`) are screenshots of the game's map screen,
committed to the repo alongside `maps/original/` (uncleaned source
screenshots — see `docs/map-image-cleanup.md` for the denoising process
between the two). `graphs/*.json` (raw extraction output) and the
committed `graphs/*_vertex_ids.json` snapshots are enough to regenerate
`index.html` via `just build` without touching the images at all; only a
full `just build-all` re-extraction reads them.
