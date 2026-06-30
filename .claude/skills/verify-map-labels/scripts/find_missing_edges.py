"""
Find raster line pixels not covered by any extracted+corrected edge —
candidates for the "missing edge/vertex" bug found in Bloom Site 2 L3
(a whole triangle-marker junction with visible raster lines that
extraction never produced a vertex for).

validate_edges() in extract_graph.py only removes edges with poor raster
coverage; it has no way to flag raster line content that has NO edge
covering it at all. This script closes that gap: it rebuilds the same
line_mask extraction uses (fuzzy_select), draws a thick buffer around
every corrected edge, and reports leftover connected components of
uncovered line pixels above a size threshold — real raster line content
the graph doesn't account for.

Small leftovers are expected (line caps, anti-aliasing, label connector
lines if they share the seed color) — only components above --min-size
are reported. This does NOT auto-fix anything; each hit needs a human to
check the raster image and either add a vertex/edge or confirm it's a
false positive (e.g. a label connector, a creature dot cluster).

Usage:
  uv run python .claude/skills/verify-map-labels/scripts/find_missing_edges.py [map_key] [--min-size 150] [--buffer 12]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import apply_corrections, EXTRACTION_CONFIG  # noqa: E402
from extract_graph import fuzzy_select  # noqa: E402

MAP_IMAGE_OVERRIDES = {}


def parse_seed(s):
    return np.array([int(v) for v in s.split(",")], dtype=float)


def line_mask_for(map_key):
    cfg = EXTRACTION_CONFIG[map_key]
    img_path = ROOT / "maps" / MAP_IMAGE_OVERRIDES.get(map_key, f"{map_key}.jpg")
    arr = np.array(Image.open(img_path).convert("RGB"))
    mask = fuzzy_select(arr, parse_seed(cfg["seed"]), cfg["threshold"])
    if cfg.get("seed2"):
        mask |= fuzzy_select(arr, parse_seed(cfg["seed2"]), cfg["threshold"])
    return mask, arr.shape[0], arr.shape[1]


def edge_coverage_mask(verts_px, edges, h, w, buffer_px):
    cov = np.zeros((h, w), dtype=bool)
    canvas = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(canvas)
    for a, b in edges:
        draw.line([verts_px[a], verts_px[b]], fill=1, width=1)
    line_px = np.array(canvas, dtype=bool)
    dist = ndimage.distance_transform_edt(~line_px)
    return dist <= buffer_px


def scan(map_key, min_size, buffer_px):
    graph_path = ROOT / "graphs" / f"{map_key}_graph.json"
    if not graph_path.exists() or map_key not in EXTRACTION_CONFIG:
        return None
    mask, h, w = line_mask_for(map_key)
    with open(graph_path) as f:
        g = json.load(f)
    verts_px, edges = apply_corrections(map_key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])
    covered = edge_coverage_mask(verts_px, edges, h, w, buffer_px)
    uncovered = mask & ~covered
    labeled, n = ndimage.label(uncovered, structure=np.ones((3, 3)))
    results = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        area = len(xs)
        if area < min_size:
            continue
        cx, cy = int(xs.mean()), int(ys.mean())
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        results.append((area, cx, cy, bbox))
    results.sort(reverse=True)
    return results


def main():
    min_size = 150
    buffer_px = 12
    map_keys = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--min-size":
            min_size = int(args[i + 1]); i += 2
        elif a == "--buffer":
            buffer_px = int(args[i + 1]); i += 2
        elif a in EXTRACTION_CONFIG:
            map_keys.append(a); i += 1
        else:
            i += 1

    if not map_keys:
        map_keys = list(EXTRACTION_CONFIG.keys())

    for mk in map_keys:
        results = scan(mk, min_size, buffer_px)
        if results is None:
            continue
        print(f"=== {mk} ({len(results)} uncovered raster components >= {min_size}px) ===")
        for area, cx, cy, bbox in results:
            print(f"  centroid ({cx},{cy}) area={area}px bbox={bbox}")


if __name__ == "__main__":
    main()
