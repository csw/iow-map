"""
Given a map key and an approximate (x, y) near a label's white/colored
connector line, finds the line's actual two endpoints (text side and vertex
side) by tracing the connected component of near-white pixels, and reports
which extracted vertex the vertex-side endpoint actually lands on.

This exists because eyeballing a zoomed screenshot crop is unreliable in
crowded junction areas — multiple lines/vertices close together make it easy
to visually associate a label with the wrong nearby vertex. This script
finds the line's pixel-precise endpoint instead of trusting a screenshot.

Usage:
  uv run python .claude/skills/verify-map-labels/scripts/trace_connector.py <map_key> <x> <y> [--color white|gold]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import ConvexHull

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import apply_corrections, resolve_labels  # noqa: E402

MAP_IMAGE_OVERRIDES = {}  # map_key -> filename, if it ever differs from f"{map_key}.jpg"


def main():
    map_key, x, y = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    color = "white"
    for a in sys.argv[4:]:
        if a.startswith("--color"):
            color = a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]

    img_path = ROOT / "maps" / MAP_IMAGE_OVERRIDES.get(map_key, f"{map_key}.jpg")
    arr = np.array(Image.open(img_path).convert("RGB"))

    if color == "white":
        mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] > 200) & (arr[:, :, 2] > 200)
    elif color == "gold":
        # gold/yellow connector lines (e.g. entry-node lines): high R+G, low B
        mask = (arr[:, :, 0] > 180) & (arr[:, :, 1] > 140) & (arr[:, :, 2] < 100)
    else:
        raise ValueError(f"unknown color {color}")

    labeled, n = ndimage.label(mask, structure=np.ones((3, 3)))

    # find component(s) with a pixel within 60px of the click point
    yy, xx = np.where(mask)
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    nearby = d2 < 60 ** 2
    if not nearby.any():
        print(f"No {color} pixels found within 60px of ({x:.0f},{y:.0f}). "
              f"Try a larger search or different --color.")
        return
    comp_ids = set(labeled[yy[nearby], xx[nearby]].tolist())
    comp_ids.discard(0)

    graph_path = ROOT / "graphs" / f"{map_key}_graph.json"
    with open(graph_path) as f:
        g = json.load(f)
    verts_px, edges = apply_corrections(map_key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])
    labels = resolve_labels(map_key, verts_px)

    def nearest_vertex(px, py):
        best_i, best_d = None, float("inf")
        for i, (vx, vy) in enumerate(verts_px):
            d = math.hypot(vx - px, vy - py)
            if d < best_d:
                best_i, best_d = i, d
        return best_i, best_d

    for cid in comp_ids:
        pys, pxs = np.where(labeled == cid)
        pts = np.column_stack([pxs, pys])
        if len(pts) < 3:
            print(f"component {cid}: too small ({len(pts)} px) to analyze")
            continue
        try:
            hull = ConvexHull(pts)
            hpts = pts[hull.vertices]
        except Exception:
            hpts = pts
        # find the pair of hull points with max pairwise distance (line's two ends)
        best_pair = None
        best_dist = -1
        for i in range(len(hpts)):
            for j in range(i + 1, len(hpts)):
                d = np.hypot(*(hpts[i] - hpts[j]))
                if d > best_dist:
                    best_dist = d
                    best_pair = (hpts[i], hpts[j])
        if best_pair is None:
            continue
        p1, p2 = best_pair
        v1, d1 = nearest_vertex(*p1)
        v2, d2_ = nearest_vertex(*p2)
        # vertex-side endpoint = whichever extreme point is closer to an actual vertex
        if d1 <= d2_:
            vertex_end, other_end, vidx, vdist = p1, p2, v1, d1
        else:
            vertex_end, other_end, vidx, vdist = p2, p1, v2, d2_
        print(f"component {cid}: {len(pts)}px, span {best_dist:.0f}px")
        print(f"  endpoint A: ({p1[0]},{p1[1]})  endpoint B: ({p2[0]},{p2[1]})")
        print(f"  -> vertex-side endpoint ({vertex_end[0]},{vertex_end[1]}) "
              f"nearest to v{vidx} ({verts_px[vidx][0]:.0f},{verts_px[vidx][1]:.0f}) "
              f"dist={vdist:.1f}  current_label={labels.get(vidx, '')!r}")


if __name__ == "__main__":
    main()
