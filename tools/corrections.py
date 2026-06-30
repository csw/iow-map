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
        "merge_radius": 30, "detect_triangles": True,
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


def _remove_edge_between(verts_px, edges, px_a, px_b, max_dist=30):
    """Remove the edge between the two vertices nearest to px_a and px_b."""
    va = _find_nearest_vertex(verts_px, px_a, max_dist)
    vb = _find_nearest_vertex(verts_px, px_b, max_dist)
    if va is None or vb is None:
        print(f"  WARN: can't remove edge {px_a}→{px_b}: vertex not found")
        return edges
    target = tuple(sorted([va, vb]))
    new_edges = [e for e in edges if tuple(sorted(e)) != target]
    if len(new_edges) < len(edges):
        print(f"  Removed edge v{va}↔v{vb}")
    else:
        print(f"  WARN: edge v{va}↔v{vb} not found")
    return new_edges


# ─── Per-Map Corrections ───────────────────────────────────────────────────

def _correct_east_reef(verts_px, edges, w, h):
    """No corrections currently needed — raster-aware edge validation handles
    the spurious diagonals that previously required manual removal."""
    return verts_px, edges


def _correct_the_bloom_main(verts_px, edges, w, h):
    """Fix edges in dark background area north of Fan Stem."""
    # Green segment between (1730, 2559) and (2314, 2761) on the raster.
    edges = _add_edge_between(verts_px, edges, (1730, 2559), (2314, 2761),
                              max_dist=50)
    # Spurious vertex cluster at dark background transition (~1170,2340):
    # three vertices where raster lines converge at one point.
    # Remove two, reconnect their external neighbors to the survivor.
    verts_px, edges = _remove_vertex_near(verts_px, edges, (1163, 2350))
    verts_px, edges = _remove_vertex_near(verts_px, edges, (1190, 2350))
    edges = _add_edge_between(verts_px, edges, (1166, 2330), (1091, 2410))
    edges = _add_edge_between(verts_px, edges, (1166, 2330), (1321, 2445))
    edges = _add_edge_between(verts_px, edges, (1166, 2330), (1188, 2476))
    # Gap at dark background transition on east side
    edges = _add_edge_between(verts_px, edges, (3242, 2594), (3221, 2616))
    return verts_px, edges


def _correct_brine_pool(verts_px, edges, w, h):
    """No corrections currently needed — spurious label-text vertex now
    handled by the extraction pipeline's solidity filter."""
    return verts_px, edges


def _correct_the_bloom_site_2_level_3(verts_px, edges, w, h):
    """No corrections currently needed — spurious label-connector vertex now
    handled by the extraction pipeline."""
    return verts_px, edges


# Register corrections (only maps that need them)
def _correct_the_anomaly_upper_level(verts_px, edges, w, h):
    """Fix spurious vertex cluster at To Lower Level transition (~1240,990):
    three degree-1 vertices where raster lines converge at one point."""
    verts_px, edges = _remove_vertex_near(verts_px, edges, (1228, 984))
    verts_px, edges = _remove_vertex_near(verts_px, edges, (1244, 1000))
    edges = _add_edge_between(verts_px, edges, (1254, 980), (1060, 960),
                              max_dist=40)
    edges = _add_edge_between(verts_px, edges, (1254, 980), (1272, 1129),
                              max_dist=40)
    return verts_px, edges


GRAPH_CORRECTIONS = {
    "east_reef": _correct_east_reef,
    "the_bloom_main": _correct_the_bloom_main,
    "brine_pool": _correct_brine_pool,
    "the_anomaly_upper_level": _correct_the_anomaly_upper_level,
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
            # (x, y) near TARGET VERTEX. Resolved to nearest vertex at build time.
            (1886, 453): "To The Bloom",
            (4348, 812): "Canopy Growth",
            (2417, 1065): "Waystation",
            (4847, 1089): "To East Reef",
            (3392, 1487): "Fungal Cluster",
            (3711, 1707): "Soothespore",
            (484, 1698): "Bloat Root",
            (4011, 1820): "To East Reef",
            (3437, 2006): "Clouded Shell",
            (2486, 2012): "Stalk Root",
            (3502, 2437): "Cap Section",
            (2796, 3198): "Stalk Spore",
            (3508, 3803): "Game Start",
            (797, 1130): "Striped Egg",
            (3645, 1834): "Soothespore",
            (2924, 2802): "Stalk Bark",
            (2816, 3459): "Stalk Spore",
        },
    },
    "east_reef": {
        "name": "East Reef",
        "GS_px": None,
        "EN_px": [(926, 685), (138, 1444)],  # Two "To Central Reef" exits
        "FR": 232,
        "labels_px": {
            # (x, y) near TARGET VERTEX. Resolved to nearest vertex at build time.
            (926, 685): "To Central Reef",
            (138, 1444): "To Central Reef",
            (2936, 1093): "Silken Strands",
            (3049, 1205): "Chitin Plate",
            (588, 1391): "Canopy Root",
            (1014, 1520): "Bright Pollen",
            (2198, 1717): "Shed Tail",
            (2088, 1999): "Feather Arm",
            (2135, 2000): "Petal Shoot",
            (2132, 2040): "Silken Root",
            (4273, 1055): "Colony Bladder",
            (2713, 1196): "Stalk Segment",
            (4227, 1162): "Colony Tentacle",
            (1170, 1473): "Bright Pollen",
            (2339, 1649): "Shed Feather",
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
        "EN_px": [(773, 212), (1096, 217), (3436, 3406), (921, 5098)],
        "FR": 173,
        "labels_px": {
            # (x, y) near TARGET VERTEX. Resolved to nearest vertex at build time.
            (773, 212): "To The Anomaly",
            (1096, 217): "To The Anomaly",
            (197, 475): "Veil Tissue",
            (1759, 611): "Petal Root",
            (353, 1157): "Shed Polyp",
            (1369, 1417): "Ovoid Bud",
            (548, 1459): "Glowing Spine",
            (1152, 1665): "Beaded Eggs",
            (1833, 1797): "Tail Segment",
            (1951, 2319): "Deep Pollen",
            (1948, 2361): "Fan Sheath",
            (3436, 3406): "To Brine Pools",
            (1576, 4312): "Digested Remains",
            (921, 5098): "Start",
        },
    },
    "brine_pool": {
        "name": "Brine Pool",
        "GS_px": None,
        "EN_px": [(27, 2670)],  # "To Dusk Slopes"
        "FR": 132,
        "labels_px": {
            (992, 470): "Crested Shell",       # v2
            (2034, 606): "Fan Sheath",          # v3
            (1098, 1259): "Fan Sheath",         # v7
            (1159, 1326): "Deep Pollen",        # v8
            (2203, 787): "Bristly Limb",        # v5
            (966, 1485): "Brine Shell",         # v10
            (1684, 1926): "Mucus Bubble",       # v23
            (1101, 2065): "Brine Mat",          # v29
            (471, 2406): "Brine Mat",           # v41
            (831, 2314): "Mucus Bubble",        # v36
            (906, 2367): "Brine Shell",         # v38
            (563, 2732): "Mucus Bubble",        # v49
            (1714, 2788): "Mucus Bubble",       # v51
            (1583, 2841): "Young Carapace",     # v52
            (1780, 2950): "Brine Shell",        # v53
        },
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
        "EN_px": [(1006, 1093), (1637, 577), (1651, 969)],
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
        "Triangle detection false positives (creature dots, yellow nav lines) "
        "now handled by shape filters in detect_triangle_markers(). 4 spurious "
        "diagonal edges still corrected manually. Some labeled vertices "
        "(Canopy Root, Bright Pollen, Shed Tail, Shed Feather) have no vertex "
        "within 80px."
    ),
    "the_bloom_main": (
        "Some edges missed in dark background region N of Fan Stem. "
        "Likely a threshold issue — lines are dimmer against darker background."
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
