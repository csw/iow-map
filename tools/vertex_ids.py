"""
Stable Vertex ID Reconciliation
================================

The deployed app's saved fog-of-war progress (localStorage) references
graph vertices by array index. Raw extraction order is only guaranteed
stable for a fixed image + fixed EXTRACTION_CONFIG + fixed library
versions — tweaking thresholds/epsilon, upgrading scikit-image, or
touching the source map image can all reorder vertices coming out of
extract_graph.py, even though corrections.py's coordinate-based lookups
keep applying correctly.

To stay stable across all of that, each map's vertex identity is pinned in
a canonical snapshot file, graphs/<map>_vertex_ids.json: a list of pixel
coordinates, one per stable index (some possibly null — a tombstoned index
whose vertex is no longer produced by extraction, or was retired by a
correction). This file is NOT purely derived from the map image — it is
the durable source of truth for "which index is this vertex" and must be
committed to git.

Every build, after extraction + corrections produce a fresh (verts_px,
edges), reconcile_stable_ids() fuzzy-matches those vertices against the
snapshot by nearest pixel coordinate and returns a re-indexed
(verts_px, edges, dead) that keeps every previously-known vertex at its
existing index:
  - matched vertices keep their canonical index (refreshed to the new
    coordinate, which may drift a few px between extraction runs)
  - unmatched fresh vertices are genuinely new — appended with a brand
    new index
  - unmatched canonical slots (a previously-known vertex that vanished
    from this extraction) keep their index reserved/tombstoned rather
    than being reused, and are reported as "dead"

First run for a map bootstraps the snapshot from whatever (verts_px,
edges) it's given, so introducing this system doesn't itself change any
already-deployed index.
"""

import json
import math
from pathlib import Path

MAX_DIST = 25  # px; well under EXTRACTION_CONFIG merge_radius (30) to avoid
                # matching two distinct nearby vertices to the same slot


def _snapshot_path(graphs_dir, map_key):
    return Path(graphs_dir) / f"{map_key}_vertex_ids.json"


def _load_snapshot(path):
    with open(path) as f:
        data = json.load(f)
    return [tuple(p) if p is not None else None for p in data]


def _write_snapshot(path, canonical):
    with open(path, "w") as f:
        json.dump([list(p) if p is not None else None for p in canonical], f)
        f.write("\n")


def reconcile_stable_ids(map_key, verts_px, edges, graphs_dir, max_dist=MAX_DIST):
    """Re-index (verts_px, edges) so every vertex keeps the same array
    index it has always had. Returns (stable_verts_px, stable_edges,
    dead_indices)."""
    path = _snapshot_path(graphs_dir, map_key)

    if not path.exists():
        _write_snapshot(path, verts_px)
        print(f"  [{map_key}] bootstrapped vertex-id snapshot ({len(verts_px)} vertices)")
        return verts_px, edges, []

    canonical = _load_snapshot(path)

    candidates = []
    for cid, cpos in enumerate(canonical):
        if cpos is None:
            continue
        for ni, npos in enumerate(verts_px):
            d = math.hypot(npos[0] - cpos[0], npos[1] - cpos[1])
            if d <= max_dist:
                candidates.append((d, cid, ni))
    candidates.sort(key=lambda t: t[0])

    claimed_cid, claimed_ni = set(), set()
    ni_to_cid = {}
    for d, cid, ni in candidates:
        if cid in claimed_cid or ni in claimed_ni:
            continue
        ni_to_cid[ni] = cid
        claimed_cid.add(cid)
        claimed_ni.add(ni)

    disappeared = sorted(
        cid for cid in range(len(canonical))
        if canonical[cid] is not None and cid not in claimed_cid
    )
    leftover_ni = sorted(ni for ni in range(len(verts_px)) if ni not in claimed_ni)

    next_id = len(canonical)
    for ni in leftover_ni:
        ni_to_cid[ni] = next_id
        next_id += 1
    new_ids = list(range(len(canonical), next_id))

    stable_verts = list(canonical) + [None] * len(new_ids)
    for ni, cid in ni_to_cid.items():
        stable_verts[cid] = tuple(verts_px[ni])

    stable_edges = sorted(sorted([ni_to_cid[a], ni_to_cid[b]]) for a, b in edges)

    if disappeared:
        print(f"  WARNING [{map_key}]: {len(disappeared)} previously-known vertex(es) "
              f"not found in this extraction — index(es) {disappeared} tombstoned as "
              f"dead. Review before committing (map image or extraction params may "
              f"have changed unexpectedly).")
    if new_ids:
        print(f"  [{map_key}]: {len(new_ids)} new vertex(es) assigned index(es) {new_ids}")

    _write_snapshot(path, stable_verts)

    return [list(p) for p in stable_verts], stable_edges, disappeared
