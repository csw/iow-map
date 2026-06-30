"""
Given a map key and an approximate (x, y) image-space point, prints the N
nearest extracted vertices with their exact pixel coords, distance, and any
currently-resolved label.

Use this instead of hovering in the debug viewer: zoom into a screenshot of
the map, eyeball roughly where a connector line terminates, then look up the
real vertex programmatically rather than via interactive mouse hover.

Usage:
  uv run python .claude/skills/verify-map-labels/scripts/nearest_vertex.py <map_key> <x> <y> [N]
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import apply_corrections, resolve_labels  # noqa: E402

map_key, x, y = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
n = int(sys.argv[4]) if len(sys.argv) > 4 else 5

graph_path = ROOT / "graphs" / f"{map_key}_graph.json"
with open(graph_path) as f:
    g = json.load(f)
verts_px, edges = apply_corrections(map_key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])
labels = resolve_labels(map_key, verts_px)

dists = []
for i, (vx, vy) in enumerate(verts_px):
    d = math.hypot(vx - x, vy - y)
    dists.append((d, i, vx, vy, labels.get(i, "")))
dists.sort()
for d, i, vx, vy, lbl in dists[:n]:
    print(f"v{i}: ({vx:.0f}, {vy:.0f})  dist={d:.1f}  label={lbl!r}")
