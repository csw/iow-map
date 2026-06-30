"""
Generates map_data_debug.json (repo root) for label_debug_viewer.html.

Dumps, per map: corrected vertices/edges, the CURRENTLY RESOLVED label/EN/GS
vertex indices (what the build actually produces today), and the raw
labels_px coordinates from corrections.py (what you're trying to fix).

Run from repo root: uv run python .claude/skills/verify-map-labels/scripts/gen_debug_data.py
Re-run after every corrections.py edit to refresh the viewer.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from corrections import MAP_METADATA, apply_corrections, resolve_labels, resolve_en, resolve_gs  # noqa: E402

MAP_ORDER = [
    "central_reef", "east_reef", "the_bloom_main", "dusk_slopes",
    "brine_pool", "the_anomaly_lower_level", "the_anomaly_upper_level",
    "the_bloom_site_2_level_1", "the_bloom_site_2_level_2",
    "the_bloom_site_2_level_3", "the_bloom_site_2_level_4",
]

out = {}
for key in MAP_ORDER:
    graph_path = ROOT / "graphs" / f"{key}_graph.json"
    if not graph_path.exists():
        continue
    with open(graph_path) as f:
        g = json.load(f)
    verts_px, edges = apply_corrections(key, g["vertices_px"], g["edges"], g["image_w"], g["image_h"])
    out[key] = {
        "w": g["image_w"],
        "h": g["image_h"],
        "verts": verts_px,
        "edges": edges,
        "labels": resolve_labels(key, verts_px),   # {vertex_idx: "Label Name"} -- what build currently produces
        "en": resolve_en(key, verts_px),
        "gs": resolve_gs(key, verts_px),
        "labels_px": {f"{x},{y}": t for (x, y), t in MAP_METADATA[key].get("labels_px", {}).items()},
    }

out_path = ROOT / "map_data_debug.json"
with open(out_path, "w") as f:
    json.dump(out, f)
print(f"wrote {out_path}")
