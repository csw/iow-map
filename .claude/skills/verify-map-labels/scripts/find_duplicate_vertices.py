"""
Scan a map's post-correction graph for vertex pairs that are close together
but NOT connected by an edge — candidates for the kind of unmerged-junction
bug found in Bloom Site 2 L1 (v2/v3, 23px apart) and L3 (v4/v5/v6 triple).

merge_close_vertices() only merges vertices that are either edge-connected
or raster-connected within its radius; it can still miss cases where the
raster line between two close vertices is broken/thin/anti-aliased. This
script flags everything close-and-unconnected so a human can check each one
against the raster image — it does NOT auto-fix anything, since some close
unconnected pairs are legitimate (e.g. parallel corridors).

Usage:
  uv run python .claude/skills/verify-map-labels/scripts/find_duplicate_vertices.py [map_key] [--radius 60]
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import apply_corrections, EXTRACTION_CONFIG  # noqa: E402


def scan(map_key, radius):
    graph_path = ROOT / "graphs" / f"{map_key}_graph.json"
    if not graph_path.exists():
        print(f"  (no graph file for {map_key})")
        return []
    with open(graph_path) as f:
        g = json.load(f)
    verts_px, edges = apply_corrections(map_key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])
    edge_set = set()
    for a, b in edges:
        edge_set.add((min(a, b), max(a, b)))
    n = len(verts_px)
    degree = [0] * n
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    found = []
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in edge_set:
                continue
            xi, yi = verts_px[i]
            xj, yj = verts_px[j]
            d = math.hypot(xi - xj, yi - yj)
            if d <= radius:
                found.append((d, i, j, (xi, yi), (xj, yj), degree[i], degree[j]))
    found.sort()
    return found


def main():
    radius = 60
    map_keys = []
    for a in sys.argv[1:]:
        if a.startswith("--radius"):
            radius = int(a.split("=", 1)[1]) if "=" in a else int(sys.argv[sys.argv.index(a) + 1])
        elif not a.replace(".", "").isdigit() and a in EXTRACTION_CONFIG:
            map_keys.append(a)
        elif a in EXTRACTION_CONFIG:
            map_keys.append(a)

    if not map_keys:
        map_keys = list(EXTRACTION_CONFIG.keys())

    for mk in map_keys:
        results = scan(mk, radius)
        print(f"=== {mk} ({len(results)} close-unconnected pairs within {radius}px) ===")
        for d, i, j, pi, pj, di, dj in results:
            print(f"  v{i}{pi} (deg {di}) -- v{j}{pj} (deg {dj})  dist={d:.1f}")


if __name__ == "__main__":
    main()
