"""
Finds labels_px entries that resolve to the SAME vertex as another entry on
the same map. resolve_labels() snaps each (x, y) to its nearest vertex and
stores it in a dict keyed by vertex index — if two different labels resolve
to the same vertex, one silently overwrites the other and vanishes from the
built app with no warning at build time.

This is a distinct bug class from mis-targeting (label resolves to the WRONG
but still distinct vertex): a collision means one label disappears entirely.
Visual sweeps (Step 0 in SKILL.md) won't necessarily catch this, since both
labels' text and connector lines are genuinely present on the map image —
the bug only shows up by checking resolution, not by looking at the raster.

Run with no args to check every map, or pass a map_key to check just one.

Usage:
  uv run python .claude/skills/verify-map-labels/scripts/find_collisions.py [map_key]
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import MAP_METADATA, apply_corrections  # noqa: E402

keys = [sys.argv[1]] if len(sys.argv) > 1 else list(MAP_METADATA.keys())

found_any = False
for key in keys:
    meta = MAP_METADATA.get(key)
    graph_path = ROOT / "graphs" / f"{key}_graph.json"
    if meta is None or not graph_path.exists():
        continue
    with open(graph_path) as f:
        g = json.load(f)
    verts_px, edges = apply_corrections(key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])

    def nearest(px, max_dist=80):
        best_i, best_d = None, float("inf")
        for i, (vx, vy) in enumerate(verts_px):
            d = math.hypot(vx - px[0], vy - px[1])
            if d < best_d:
                best_i, best_d = i, d
        return best_i if best_d <= max_dist else None

    resolved = defaultdict(list)
    for (x, y), name in meta.get("labels_px", {}).items():
        idx = nearest((x, y))
        resolved[idx].append((name, (x, y)))

    collisions = {k: v for k, v in resolved.items() if k is not None and len(v) > 1}
    if collisions:
        found_any = True
        print(f"=== {key} ===")
        for vidx, items in collisions.items():
            vx, vy = verts_px[vidx]
            print(f"  v{vidx} ({vx},{vy}) claimed by {len(items)} entries — only the last one wins:")
            for name, px in items:
                print(f"    {px}: {name!r}")

if not found_any:
    print("No collisions found.")
