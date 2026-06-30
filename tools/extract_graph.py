#!/usr/bin/env python3
"""
IOW Map Graph Extractor
=======================
Extracts navigation graph from In Other Waters map images.

Pipeline:
1. Fuzzy select (max-channel distance from seed color, threshold 90)
2. Skeletonize the mask
3. Decompose skeleton into branches between junctions/endpoints
4. Douglas-Peucker simplification (epsilon=5) on each branch
5. Output vertices + edges as JSON

Usage:
  python extract_graph.py east_reef.jpg
  python extract_graph.py --threshold 90 --epsilon 5 --seed "246,0,68" dusk_slopes.jpg
  python extract_graph.py --mask premasked.png   # RGBA with alpha = line pixels
"""
import argparse, json, sys
import numpy as np
from PIL import Image, ImageDraw
from collections import deque
from skimage.morphology import skeletonize, disk, dilation, closing
from skimage.measure import label, regionprops, approximate_polygon
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components


def fuzzy_select(image_array, seed_color, threshold, min_mask_area=200,
                 max_solidity=0.25):
    """GIMP-compatible fuzzy select: max-channel (Chebyshev) distance.
    
    Filters components by both area and solidity to separate thin line
    networks (low solidity) from compact terrain blobs (high solidity).
    """
    h, w = image_array.shape[:2]
    dist = np.max(np.abs(image_array.astype(float) - seed_color), axis=2)
    within = dist < threshold
    within[:int(h * 0.04), :] = False
    labeled = label(within)
    regions = regionprops(labeled)
    if not regions:
        print("ERROR: No pixels matched the seed color", file=sys.stderr)
        sys.exit(1)
    regions.sort(key=lambda r: r.area, reverse=True)
    # Keep components that are large enough AND look like line networks
    # (low solidity = sparse/thin, not compact blobs)
    keep = np.zeros_like(within)
    kept = 0
    dropped_noise = 0
    for r in regions:
        if r.area < min_mask_area:
            continue
        if r.solidity > max_solidity:
            dropped_noise += 1
            continue
        keep |= (labeled == r.label)
        kept += 1
    print(f"  Mask components: {len(regions)} total, {kept} kept "
          f"(>={min_mask_area}px, solidity<={max_solidity}), "
          f"{dropped_noise} noise filtered")
    return keep


def extract_graph(line_mask, dp_epsilon=5, min_component=3):
    """Extract graph via skeleton decomposition + Douglas-Peucker."""
    h, w = line_mask.shape
    rc = closing(line_mask, disk(3))
    skel = skeletonize(rc)
    print(f"  Skeleton: {skel.sum()} px")

    kernel = np.array([[1,1,1],[1,0,1],[1,1,1]])
    nc = ndimage.convolve(skel.astype(int), kernel, mode='constant', cval=0)

    # Cluster breakpoints (junctions + endpoints)
    bp_mask = skel & ((nc > 2) | (nc == 1))
    bpdil = dilation(bp_mask, disk(8))
    bpl = label(bpdil); bpr = regionprops(bpl)
    bps = [(int(r.centroid[1]), int(r.centroid[0])) for r in bpr]
    print(f"  Breakpoints: {len(bps)}")

    # Mark breakpoint zones
    bp_zone = np.zeros((h,w), dtype=np.int32)
    for bi,(bx,by) in enumerate(bps):
        for dy in range(-10,11):
            for dx in range(-10,11):
                ny,nx = by+dy, bx+dx
                if 0<=ny<h and 0<=nx<w and skel[ny,nx] and ((dx*dx+dy*dy)**.5<=10):
                    bp_zone[ny,nx] = bi+1

    # Remove breakpoint zones → remaining connected components are branches
    branch_skel = skel & (bp_zone == 0)
    branch_labels = label(branch_skel, connectivity=2)
    branch_regions = regionprops(branch_labels)
    print(f"  Branch segments: {len(branch_regions)}")

    # For each branch, find adjacent breakpoints and trace as ordered path
    branches = []
    for r in branch_regions:
        if r.area < 3: continue
        adj_bps = set()
        for cy, cx in r.coords:
            for dy in [-1,0,1]:
                for dx in [-1,0,1]:
                    ny,nx = cy+dy, cx+dx
                    if 0<=ny<h and 0<=nx<w and bp_zone[ny,nx] > 0:
                        adj_bps.add(bp_zone[ny,nx]-1)
        if len(adj_bps) < 2: continue

        # Order pixels as a path
        seg_mask = branch_labels == r.label
        seg_nc = ndimage.convolve(seg_mask.astype(int), kernel, mode='constant', cval=0)
        seg_endps = [(x,y) for y,x in zip(*np.where(seg_mask & (seg_nc <= 1)))]
        if len(seg_endps) < 2: continue

        path = [seg_endps[0]]
        visited = {(seg_endps[0][1], seg_endps[0][0])}
        cy, cx = seg_endps[0][1], seg_endps[0][0]
        while True:
            found = False
            for dy in [-1,0,1]:
                for dx in [-1,0,1]:
                    if dy==0 and dx==0: continue
                    ny,nx = cy+dy, cx+dx
                    if 0<=ny<h and 0<=nx<w and seg_mask[ny,nx] and (ny,nx) not in visited:
                        visited.add((ny,nx)); path.append((nx,ny))
                        cy,cx = ny,nx; found = True; break
                if found: break
            if not found: break

        branches.append((sorted(adj_bps), path))

    # Douglas-Peucker on each branch
    all_verts = list(bps)
    all_edges = []

    for bp_list, path in branches:
        bp_a, bp_b = bp_list[0], bp_list[-1]
        full = [(bps[bp_a][0], bps[bp_a][1])] + path + [(bps[bp_b][0], bps[bp_b][1])]
        if len(full) < 3:
            all_edges.append((bp_a, bp_b)); continue

        simp = approximate_polygon(np.array(full), tolerance=dp_epsilon)
        if len(simp) <= 2:
            all_edges.append((bp_a, bp_b))
        else:
            prev = bp_a
            for pt in simp[1:-1]:
                px, py = int(pt[0]), int(pt[1])
                near = next((vi for vi,(vx,vy) in enumerate(all_verts)
                    if ((vx-px)**2+(vy-py)**2)**.5 < 15), None)
                if near is None:
                    near = len(all_verts); all_verts.append((px, py))
                all_edges.append((prev, near)); prev = near
            all_edges.append((prev, bp_b))

    # Deduplicate, remove self-loops
    edge_set = set(tuple(sorted(e)) for e in all_edges if e[0] != e[1])
    conn = set()
    for a,b in edge_set: conn.add(a); conn.add(b)

    # Connected component analysis
    n = len(all_verts)
    if n == 0:
        return [], []
    rows = [a for a,b in edge_set]+[b for a,b in edge_set]
    cols = [b for a,b in edge_set]+[a for a,b in edge_set]
    graph = csr_matrix(([1]*len(rows), (rows, cols)), shape=(n, n))
    n_comp, comp_labels = connected_components(graph, directed=False)
    # Count vertices per component (only connected vertices)
    conn_labels = comp_labels[list(conn)]
    comp_sizes = np.bincount(conn_labels)
    kept = set()
    for ci, sz in enumerate(comp_sizes):
        if sz >= min_component:
            kept.add(ci)
    dropped = [int(sz) for ci,sz in enumerate(comp_sizes) if sz > 0 and ci not in kept]
    print(f"  Components: {n_comp}, keeping {len(kept)} (dropped {dropped if dropped else 'none'})")

    o2n = {}; nv = []
    for i, v in enumerate(all_verts):
        if i in conn and comp_labels[i] in kept:
            o2n[i] = len(nv); nv.append(v)
    ne = sorted([list(e) for e in set(
        tuple(sorted([o2n[a],o2n[b]]))
        for a,b in edge_set if a in o2n and b in o2n)])

    print(f"  Result: {len(nv)} vertices, {len(ne)} edges")
    return nv, ne


def detect_triangle_markers(image_array, line_mask, vertices, edges,
                            near_threshold=40, min_area=20, max_area=300,
                            buffer_px=25):
    """Detect yellow triangle markers on paths to find mid-segment vertices.
    
    Returns list of (x, y) positions for markers not near any existing vertex.
    """
    h, w = image_array.shape[:2]
    
    # Yellow pixels: high R, high G, low B
    yellow = ((image_array[:,:,0].astype(int) > 160) &
              (image_array[:,:,1].astype(int) > 160) &
              (image_array[:,:,2].astype(int) < 100))
    
    # Keep only yellow pixels near the path
    path_buffer = dilation(line_mask, disk(buffer_px))
    on_path_yellow = yellow & path_buffer
    
    # Cluster
    labeled = label(on_path_yellow)
    regions = regionprops(labeled)
    markers = [(int(r.centroid[1]), int(r.centroid[0]), int(r.area))
               for r in regions if min_area <= r.area <= max_area]
    print(f"  Triangle markers: {len(markers)} (area {min_area}-{max_area})")
    
    # Filter to markers not near existing vertices
    new_markers = []
    for mx, my, area in markers:
        min_d = min(((vx-mx)**2 + (vy-my)**2)**0.5 for vx, vy in vertices)
        if min_d > near_threshold:
            new_markers.append((mx, my))
    
    print(f"  New mid-segment markers: {len(new_markers)} (>{near_threshold}px from existing)")
    return new_markers


def insert_mid_segment_vertices(vertices, edges, new_points):
    """Insert new vertices into the graph by splitting the nearest edge."""
    verts = list(vertices)
    edge_set = set(tuple(sorted(e)) for e in edges)
    
    for px, py in new_points:
        # Find nearest edge (point-to-segment distance)
        best_edge = None
        best_dist = float('inf')
        best_proj = None
        
        for a, b in edge_set:
            ax, ay = verts[a]
            bx, by = verts[b]
            # Project point onto line segment
            dx, dy = bx - ax, by - ay
            len_sq = dx*dx + dy*dy
            if len_sq == 0:
                continue
            t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy) / len_sq))
            proj_x = ax + t * dx
            proj_y = ay + t * dy
            d = ((px - proj_x)**2 + (py - proj_y)**2)**0.5
            if d < best_dist and 0.05 < t < 0.95:  # not too close to endpoints
                best_dist = d
                best_edge = (a, b)
                best_proj = t
        
        if best_edge and best_dist < 80:
            a, b = best_edge
            new_idx = len(verts)
            verts.append((px, py))
            edge_set.discard(best_edge)
            edge_set.add(tuple(sorted((a, new_idx))))
            edge_set.add(tuple(sorted((new_idx, b))))
            print(f"    Inserted vertex {new_idx} at ({px},{py}) splitting edge {a}-{b}")
        else:
            print(f"    Skipped ({px},{py}): no suitable edge (dist={best_dist:.0f})")
    
    new_edges = sorted([list(e) for e in edge_set])
    print(f"  After insertion: {len(verts)} vertices, {len(new_edges)} edges")
    return verts, new_edges


def merge_close_vertices(vertices, edges, radius=30):
    """Merge vertices within `radius` pixels of each other, but ONLY if
    they are directly connected by an edge.
    
    This prevents merging vertices that are spatially close but
    topologically distant (e.g. Bloat Root and a nearby junction that's
    4 hops away on the graph).
    
    Uses union-find to group nearby edge-connected vertices into clusters,
    replaces each cluster with its centroid, and remaps all edges.
    """
    n = len(vertices)
    if n == 0:
        return vertices, edges
    
    # Build adjacency from edges
    edge_set = set(tuple(sorted(e)) for e in edges)
    
    # Union-find
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a
    
    # Only merge pairs that share an edge AND are within radius
    merges = 0
    for a, b in edge_set:
        dx = vertices[a][0] - vertices[b][0]
        dy = vertices[a][1] - vertices[b][1]
        if abs(dx) <= radius and abs(dy) <= radius:
            if (dx*dx + dy*dy)**0.5 <= radius:
                union(a, b)
                merges += 1
    
    if merges == 0:
        print(f"  Vertex merge: no clusters found (radius={radius})")
        return vertices, edges
    
    # Build clusters
    clusters = {}
    for i in range(n):
        root = find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(i)
    
    multi = {r: members for r, members in clusters.items() if len(members) > 1}
    print(f"  Vertex merge: {len(multi)} clusters ({sum(len(m) for m in multi.values())} vertices -> {len(multi)})")
    
    # Build new vertex list: centroid of each cluster
    old_to_new = {}
    new_verts = []
    for i in range(n):
        root = find(i)
        if root not in old_to_new:
            members = clusters[root]
            cx = int(round(sum(vertices[m][0] for m in members) / len(members)))
            cy = int(round(sum(vertices[m][1] for m in members) / len(members)))
            old_to_new[root] = len(new_verts)
            new_verts.append((cx, cy))
        old_to_new[i] = old_to_new[root]
    
    # Remap edges, remove self-loops and duplicates
    new_edge_set = set()
    for a, b in edges:
        na, nb = old_to_new[a], old_to_new[b]
        if na != nb:
            new_edge_set.add(tuple(sorted((na, nb))))
    
    new_edges = sorted([list(e) for e in new_edge_set])
    print(f"  After merge: {len(new_verts)} vertices, {len(new_edges)} edges")
    return new_verts, new_edges


def main():
    parser = argparse.ArgumentParser(description="Extract navigation graph from IOW map")
    parser.add_argument("image", help="Map image file (JPEG/PNG)")
    parser.add_argument("--mask", action="store_true",
        help="Treat image as pre-masked RGBA (alpha = line pixels)")
    parser.add_argument("--seed", default="246,0,68",
        help="Seed color R,G,B for fuzzy select (default: 246,0,68)")
    parser.add_argument("--seed2", default=None,
        help="Optional second seed color R,G,B (masks are OR-ed)")
    parser.add_argument("--threshold", type=int, default=90,
        help="Max-channel distance threshold (default: 90)")
    parser.add_argument("--epsilon", type=int, default=5,
        help="Douglas-Peucker tolerance in pixels (default: 5)")
    parser.add_argument("--output", help="Output JSON file (default: <image>_graph.json)")
    parser.add_argument("--min-component", type=int, default=3,
        help="Drop connected components with fewer than N vertices (default: 3)")
    parser.add_argument("--max-solidity", type=float, default=0.25,
        help="Max solidity for mask components (filters compact terrain blobs, default: 0.25)")
    parser.add_argument("--overlay", help="Save overlay visualization")
    parser.add_argument("--detect-triangles", action="store_true",
        help="Detect yellow triangle markers to find mid-segment vertices")
    parser.add_argument("--tri-threshold", type=int, default=40,
        help="Min distance from existing vertex to count as new (default: 40)")
    parser.add_argument("--merge-radius", type=int, default=30,
        help="Merge vertices within this distance in pixels (0=off, default: 30)")
    args = parser.parse_args()

    img = Image.open(args.image)
    arr = np.array(img)
    h, w = arr.shape[:2] if arr.ndim >= 2 else (arr.shape[0], 1)

    if args.mask:
        if arr.ndim == 3 and arr.shape[2] == 4:
            line_mask = arr[:,:,3] > 0
        else:
            line_mask = np.any(arr < 250, axis=2) if arr.ndim == 3 else arr < 250
    else:
        seed = np.array([float(x) for x in args.seed.split(",")])
        print(f"Fuzzy select: seed={seed}, threshold={args.threshold}")
        line_mask = fuzzy_select(arr, seed, args.threshold,
                                max_solidity=args.max_solidity)
        if args.seed2:
            seed2 = np.array([float(x) for x in args.seed2.split(",")])
            print(f"Fuzzy select 2: seed={seed2}, threshold={args.threshold}")
            line_mask2 = fuzzy_select(arr, seed2, args.threshold,
                                     max_solidity=args.max_solidity)
            line_mask = line_mask | line_mask2

    print(f"Mask: {w}x{h}, {line_mask.sum()} line pixels")
    nv, ne = extract_graph(line_mask, dp_epsilon=args.epsilon, min_component=args.min_component)

    if args.detect_triangles and not args.mask:
        new_pts = detect_triangle_markers(arr, line_mask, nv, ne,
                                          near_threshold=args.tri_threshold)
        if new_pts:
            nv, ne = insert_mid_segment_vertices(nv, ne, new_pts)

    if args.merge_radius > 0:
        nv, ne = merge_close_vertices(nv, ne, radius=args.merge_radius)

    out = args.output or args.image.rsplit('.', 1)[0] + '_graph.json'
    vn = [[round(x/w, 4), round(y/h, 4)] for x, y in nv]
    with open(out, 'w') as f:
        json.dump({"vertices": vn, "vertices_px": nv, "edges": ne,
                   "image_w": w, "image_h": h}, f, indent=2)
    print(f"Saved: {out}")

    # Also print compact JS
    print(f"\nconst V={json.dumps(vn)};")
    print(f"const E={json.dumps(ne)};")

    if args.overlay:
        orig = Image.open(args.image).convert('RGB')
        draw = ImageDraw.Draw(orig)
        for a,b in ne:
            draw.line([nv[a], nv[b]], fill=(255,255,0), width=5)
        for x,y in nv:
            draw.ellipse([x-10,y-10,x+10,y+10], fill=(0,255,255),
                        outline=(255,255,255), width=2)
        orig.save(args.overlay)
        print(f"Overlay: {args.overlay}")


if __name__ == "__main__":
    main()
