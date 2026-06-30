"""
IOW Map Tracker — Post-Extraction Corrections
===============================================

This module captures every manual adjustment to the algorithmically
extracted graphs. After running extract_graph.py on all maps, run
this to apply corrections before building the HTML.

Design principle: the extraction pipeline should be re-runnable from
scratch at any time. All human-verified fixes live here, not in the
extraction code or the HTML.

Usage:
    from corrections import EXTRACTION_CONFIG, MAP_METADATA, apply_corrections
    # 1. Extract each map using EXTRACTION_CONFIG[key]
    # 2. apply_corrections(key, vertices_px, edges) → corrected (vertices_px, edges)
    # 3. Use MAP_METADATA[key] for labels, EN, GS, FR
"""

import json
import math
from pathlib import Path


# ─── Per-Map Extraction Parameters ─────────────────────────────────────────
# These are the CLI args for extract_graph.py, per map.
# If you re-extract, use these exact settings.

EXTRACTION_CONFIG = {
    "central_reef": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
    },
    "east_reef": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
        # NOTE: dot-cluster contamination around Petal Shoot, Shed Feather,
        # Silken Strands. Creature dots are same red as graph lines. Needs
        # VLM correction pass (see KNOWN_ISSUES below).
    },
    "the_bloom_main": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
        # NOTE: some edges missed in dark background N of Fan Stem.
    },
    "dusk_slopes": {
        "seed": "222,172,9", "threshold": 80, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": False,
        # Gold lines — triangle detection disabled (ambiguous with line color).
    },
    "brine_pool": {
        "seed": "22,80,252", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": False,
        # Triangle detection disabled: creature blobs sit directly on path
        # edges (< 3px) and pass all size/distance filters. No algorithmic
        # filter can distinguish them from real triangle markers.
        # Straight sections may be missing intermediate waypoints.
    },
    "the_anomaly_lower_level": {
        "seed": "246,0,68", "seed2": "222,172,9", "threshold": 90,
        "epsilon": 5, "merge_radius": 30, "detect_triangles": True,
        # Dual-seed: bottom corridor to Dusk Slopes uses gold/amber lines.
    },
    "the_anomaly_upper_level": {
        "seed": "240,75,30", "threshold": 80, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
        # Graph lines are orange-red, NOT the standard magenta-red (246,0,68).
    },
    "the_bloom_site_2_level_1": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
    },
    "the_bloom_site_2_level_2": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
    },
    "the_bloom_site_2_level_3": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
    },
    "the_bloom_site_2_level_4": {
        "seed": "246,0,68", "threshold": 90, "epsilon": 5,
        "merge_radius": 30, "detect_triangles": True,
    },
}


# ─── Post-Extraction Graph Corrections ─────────────────────────────────────
# Applied after extraction. Each correction is a function of
# (vertices_px, edges, image_w, image_h) → (vertices_px, edges).
#
# Corrections find vertices/edges by COORDINATE PROXIMITY, not by index,
# so they survive re-extraction even if indices change.

def _find_nearest_vertex(verts_px, target_px, max_dist=30):
    """Find vertex index nearest to target pixel coords."""
    best_i, best_d = None, float("inf")
    tx, ty = target_px
    for i, (vx, vy) in enumerate(verts_px):
        d = math.hypot(vx - tx, vy - ty)
        if d < best_d:
            best_i, best_d = i, d
    if best_d > max_dist:
        return None
    return best_i


def _remove_vertex_near(verts_px, edges, target_px, max_dist=30):
    """Remove a vertex near target_px, connecting its two neighbors."""
    idx = _find_nearest_vertex(verts_px, target_px, max_dist)
    if idx is None:
        print(f"  WARN: no vertex near {target_px} (max_dist={max_dist})")
        return verts_px, edges

    neighbors = []
    for a, b in edges:
        if a == idx:
            neighbors.append(b)
        elif b == idx:
            neighbors.append(a)

    new_edges = [e for e in edges if idx not in e]
    if len(neighbors) == 2:
        bridge = sorted(neighbors)
        if bridge not in new_edges:
            new_edges.append(bridge)

    # Renumber
    new_verts = verts_px[:idx] + verts_px[idx + 1:]
    def remap(i):
        return i if i < idx else i - 1
    new_edges = sorted([sorted([remap(a), remap(b)]) for a, b in new_edges])

    print(f"  Removed vertex near {target_px} (was v{idx})")
    return new_verts, new_edges


def _add_edge_between(verts_px, edges, px_a, px_b, max_dist=30):
    """Add an edge between the two vertices nearest to px_a and px_b."""
    va = _find_nearest_vertex(verts_px, px_a, max_dist)
    vb = _find_nearest_vertex(verts_px, px_b, max_dist)
    if va is None or vb is None:
        print(f"  WARN: can't add edge {px_a}→{px_b}: vertex not found")
        return edges
    edge = sorted([va, vb])
    edge_set = set(tuple(sorted(e)) for e in edges)
    if tuple(edge) not in edge_set:
        edges = edges + [edge]
        print(f"  Added edge v{va}↔v{vb}")
    return edges


# ─── Per-Map Corrections ───────────────────────────────────────────────────

def _correct_the_bloom_main(verts_px, edges, w, h):
    """Add green path segment connecting two red-line endpoints."""
    # Green segment between (1730, 2559) and (2314, 2761) on the raster.
    # Both endpoints are existing vertices in the red-line graph.
    edges = _add_edge_between(verts_px, edges, (1730, 2559), (2314, 2761),
                              max_dist=50)
    return verts_px, edges


def _correct_the_bloom_site_2_level_3(verts_px, edges, w, h):
    """Remove spurious vertex where a label connector line crosses a graph segment."""
    # At approximately (1534, 1019) in the raster image.
    verts_px, edges = _remove_vertex_near(verts_px, edges, (1534, 1019),
                                          max_dist=40)
    return verts_px, edges


# Register corrections (only maps that need them)
GRAPH_CORRECTIONS = {
    "the_bloom_main": _correct_the_bloom_main,
    "the_bloom_site_2_level_3": _correct_the_bloom_site_2_level_3,
}


def apply_corrections(map_key, verts_px, edges, image_w, image_h):
    """Apply post-extraction corrections for a specific map.

    Returns (verts_px, edges) — possibly modified.
    """
    fn = GRAPH_CORRECTIONS.get(map_key)
    if fn:
        print(f"Applying corrections for {map_key}...")
        verts_px, edges = fn(verts_px, edges, image_w, image_h)
    return verts_px, edges


# ─── Map Metadata (Labels, Entry Nodes, Game Start) ────────────────────────
# This is the source of truth for all non-graph-structure data.
# Vertex references use PIXEL COORDINATES so they survive re-extraction.
# The build_html.py script resolves these to vertex indices at build time.

MAP_METADATA = {
    "central_reef": {
        "name": "Central Reef",
        "GS_px": (3508, 3803),  # Game Start node
        "EN": None,  # Uses GS instead
        "FR": 248,
        "labels_px": {
            # (x, y) → label text. Resolved to nearest vertex at build time.
            (1886, 453): "To The Bloom",
            (4348, 812): "Canopy Growth",
            (2417, 1065): "Waystation",
            (4847, 1089): "To East Reef",
            (3392, 1487): "Fungal Cluster",
            (3711, 1707): "Soothespore",
            (484, 1698): "Bloat Root",
            (3132, 1709): "To East Reef",
            (3437, 2006): "Clouded Shell",
            (3677, 2133): "Stalk Root",
            (3924, 2494): "Cap Section",
            (4324, 3081): "Stalk Spore",
            (3508, 3803): "Game Start",
            (2071, 1467): "Striped Egg",
            (6753, 1707): "Soothespore",
            (2924, 2802): "Stalk Bark",
            (7745, 3081): "Stalk Spore",
        },
    },
    "east_reef": {
        "name": "East Reef",
        "GS_px": None,
        "EN_px": [(926, 685), (138, 1444)],  # Two "To Central Reef" exits
        "FR": 232,
        "labels_px": {
            (926, 685): "To Central Reef",
            (138, 1444): "To Central Reef",
            (2936, 1093): "Silken Strands",
            (3049, 1205): "Chitin Plate",
            (1463, 662): "Canopy Root",
            (1631, 1615): "Bright Pollen",
            (1797, 1355): "Shed Tail",
            (2088, 1999): "Feather Arm",
            (2135, 2000): "Petal Shoot",
            (2132, 2040): "Silken Root",
            (4273, 1055): "Colony Bladder",
            (2713, 1196): "Stalk Segment",
            (4227, 1162): "Colony Tentacle",
            (3488, 1332): "Bright Pollen",
            (3876, 1716): "Shed Feather",
        },
    },
    "the_bloom_main": {
        "name": "The Bloom",
        "GS_px": None,
        "EN_px": [(3955, 2612)],  # "To Central Reef"
        "FR": 208,
        "labels_px": {
            (2510, 641): "Nest Workers",
            (2447, 714): "Sphere Fragment",
            (1218, 717): "Waystation",
            (3955, 2612): "To Central Reef",
            (1578, 2886): "Fan Stem",
            (625, 3467): "Nest Fragment",
            (2133, 1285): "Bivalve Shell",
            (3038, 1813): "Fan Dust",
        },
    },
    "dusk_slopes": {
        "name": "Dusk Slopes",
        "GS_px": None,
        "EN_px": [(773, 212), (1096, 217), (3222, 4676), (921, 5098)],
        "FR": 173,
        "labels_px": {
            (773, 212): "To The Anomaly",
            (1096, 217): "To The Anomaly",
            (197, 475): "Veil Tissue",
            (1759, 611): "Petal Root",
            (353, 1157): "Shed Polyp",
            (1369, 1417): "Ovoid Bud",
            (548, 1459): "Glowing Spine",
            (882, 1477): "Beaded Eggs",
            (1833, 1797): "Tail Segment",
            (1951, 2319): "Deep Pollen",
            (1948, 2361): "Fan Sheath",
            (3222, 4676): "To Brine Pools",
            (1194, 4527): "Digested Remains",
            (921, 5098): "Start",
        },
    },
    "brine_pool": {
        "name": "Brine Pool",
        "GS_px": None,
        "EN_px": [(27, 2670)],  # "To Dusk Slopes"
        "FR": 132,
        # NOTE: Most of these label assignments are WRONG and need a full
        # redo via visual inspection of the raster map. Keeping them as
        # placeholders for now.
        "labels_px": {
            (992, 470): "Crested Shell",
            (2034, 608): "Fan Sheath",
            (1850, 964): "Bristly Limb",
            (2068, 958): "Deep Pollen",
            (966, 1485): "Brine Shell",
            (1681, 1911): "Mucus Bubble",
            (578, 2320): "Brine Mat",
            (1303, 1762): "Mucus Bubble",
            (1380, 2745): "Young Carapace",
            (1580, 2812): "Brine Shell",
            (526, 2401): "Mucus Bubble",
            (516, 2399): "Brine Shell",
        },
        "_label_warning": "Most labels are approximate/wrong. Needs VLM redo.",
    },
    "the_anomaly_lower_level": {
        "name": "Anomaly Lower",
        "GS_px": None,
        "EN_px": [(766, 3663), (1106, 3717)],
        "FR": 131,
        "labels_px": {
            (304, 817): "Spiral Secretion",
            (1636, 1416): "Spiral Secretion",
            (1304, 1815): "Spiral Secretion",
            (1978, 1815): "Molted Skin",
            (766, 3663): "To Dusk Slopes",
            (1106, 3717): "To Dusk Slopes",
            (1263, 1132): "Fan Sheath",
        },
    },
    "the_anomaly_upper_level": {
        "name": "Anomaly Upper",
        "GS_px": None,
        "EN_px": [(2211, 405), (1254, 979), (392, 1860)],
        "FR": 131,
        "labels_px": {
            (2211, 405): "Exit Anomaly",
            (1254, 979): "To Lower Level",
            (392, 1860): "To Lower Level",
        },
    },
    "the_bloom_site_2_level_1": {
        "name": "Bloom Site 2 L1",
        "GS_px": None,
        "EN_px": [(1018, 1044)],
        "FR": 173,
        "labels_px": {
            (1040, 1042): "Bloom Source",
        },
    },
    "the_bloom_site_2_level_2": {
        "name": "Bloom Site 2 L2",
        "GS_px": None,
        "EN_px": [(1670, 539), (1033, 1085)],
        "FR": 173,
        "labels_px": {},
    },
    "the_bloom_site_2_level_3": {
        "name": "Bloom Site 2 L3",
        "GS_px": None,
        "EN_px": [(1006, 1093)],  # bottom endpoint
        "FR": 173,
        "labels_px": {},
    },
    "the_bloom_site_2_level_4": {
        "name": "Bloom Site 2 L4",
        "GS_px": None,
        "EN_px": [(524, 548), (1087, 773), (2576, 827), (1673, 974), (990, 1109)],
        "FR": 173,
        "labels_px": {},
    },
}


# ─── Known Issues ──────────────────────────────────────────────────────────
# For documentation / future reference.

KNOWN_ISSUES = {
    "east_reef": (
        "Creature dot clusters (small dark circles) sit on the red graph "
        "lines and are picked up by fuzzy select, creating spurious skeleton "
        "junctions and missing real edges. Affected areas: Petal Shoot, "
        "Shed Feather, Silken Strands. Best fixed with a VLM correction "
        "pass — analyze numbered overlay, identify spurious vertices and "
        "missing edges, add to GRAPH_CORRECTIONS."
    ),
    "brine_pool": (
        "Triangle detection disabled because creature blobs sit directly "
        "on path edges (< 3px distance). Straight sections may be missing "
        "intermediate waypoints. Labels are mostly wrong — need full redo "
        "via raster map inspection."
    ),
    "the_bloom_main": (
        "Some edges missed in dark background region N of Fan Stem. "
        "Likely a threshold issue — lines are dimmer against darker background."
    ),
    "the_anomaly_upper_level": (
        "Three vertices (v25/v26/v28) clustered within 20px near center "
        "'To Lower Level' exit. May need manual cleanup."
    ),
}


# ─── Coordinate Resolution Helpers ─────────────────────────────────────────
# Used by build_html.py to convert pixel coordinates to vertex indices.

def resolve_labels(map_key, verts_px, max_dist=80):
    """Convert label pixel coords to vertex indices."""
    meta = MAP_METADATA[map_key]
    labels_px = meta.get("labels_px", {})
    result = {}
    for (lx, ly), text in labels_px.items():
        idx = _find_nearest_vertex(verts_px, (lx, ly), max_dist)
        if idx is not None:
            result[idx] = text
        else:
            print(f"  WARN: label '{text}' at ({lx},{ly}) — no vertex within {max_dist}px")
    return result


def resolve_en(map_key, verts_px, max_dist=80):
    """Convert EN pixel coords to vertex indices."""
    meta = MAP_METADATA[map_key]
    en_px = meta.get("EN_px")
    if en_px is None:
        return None
    result = []
    for (ex, ey) in en_px:
        idx = _find_nearest_vertex(verts_px, (ex, ey), max_dist)
        if idx is not None:
            result.append(idx)
        else:
            print(f"  WARN: EN at ({ex},{ey}) — no vertex within {max_dist}px")
    return result


def resolve_gs(map_key, verts_px, max_dist=80):
    """Convert GS pixel coord to vertex index."""
    meta = MAP_METADATA[map_key]
    gs_px = meta.get("GS_px")
    if gs_px is None:
        return None
    return _find_nearest_vertex(verts_px, gs_px, max_dist)
