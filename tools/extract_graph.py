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
                            near_threshold=40, min_area=20, max_area=80,
                            buffer_px=25):
    """Detect yellow triangle markers on paths to find mid-segment vertices.

    Triangle markers are uniform equilateral triangles drawn underneath the
    red annotation.  Their visible yellow portions (tips flanking the red
    line) are solid crescents directly adjacent to the red mask.

    Three kinds of yellow features appear near the path and must be rejected:
      1. Creature-dot clusters — diamond-shaped, hollow center (Euler ≤ 0),
         area typically 100-200 px.
      2. In-game navigation lines — very elongated (eccentricity ≈ 1).
      3. Stray dots — not adjacent to the red mask (min distance > 2 px).

    Returns list of (x, y) positions for markers not near any existing vertex.
    """
    from scipy.ndimage import distance_transform_edt

    h, w = image_array.shape[:2]

    yellow = ((image_array[:,:,0].astype(int) > 160) &
              (image_array[:,:,1].astype(int) > 160) &
              (image_array[:,:,2].astype(int) < 100))

    path_buffer = dilation(line_mask, disk(buffer_px))
    on_path_yellow = yellow & path_buffer

    labeled = label(on_path_yellow)
    regions = regionprops(labeled)
    dist_to_red = distance_transform_edt(~line_mask)

    candidates = []
    n_area = n_euler = n_ecc = n_dist = 0
    for r in regions:
        area = int(r.area)
        if area < min_area or area > max_area:
            n_area += 1
            continue
        if int(r.euler_number) <= 0:
            n_euler += 1
            continue
        if float(r.eccentricity) > 0.98:
            n_ecc += 1
            continue
        region_dists = dist_to_red[labeled == r.label]
        if region_dists.min() > 1:
            n_dist += 1
            continue
        candidates.append((int(r.centroid[1]), int(r.centroid[0])))

    print(f"  Triangle markers: {len(candidates)} candidates "
          f"(rejected: {n_area} area, {n_euler} hollow, "
          f"{n_ecc} elongated, {n_dist} off-path)")

    new_markers = []
    for mx, my in candidates:
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


def _raster_connected(line_mask, x0, y0, x1, y1, max_dist=40):
    """Check if two points are connected via line_mask pixels.

    BFS on line_mask pixels starting from (x0,y0), limited to a bounding
    box around both points.  Returns True if we reach (x1,y1).
    """
    from collections import deque
    h, w = line_mask.shape
    pad = 10
    bx0 = max(0, min(x0, x1) - pad)
    by0 = max(0, min(y0, y1) - pad)
    bx1 = min(w, max(x0, x1) + pad + 1)
    by1 = min(h, max(y0, y1) + pad + 1)

    # Find nearest mask pixel to start
    best_start = None
    best_sd = 999
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            ny, nx = y0 + dy, x0 + dx
            if 0 <= ny < h and 0 <= nx < w and line_mask[ny, nx]:
                d = abs(dx) + abs(dy)
                if d < best_sd:
                    best_sd = d
                    best_start = (nx, ny)
    if best_start is None:
        return False

    visited = set()
    visited.add(best_start)
    queue = deque([best_start])
    target_r = 5

    while queue:
        cx, cy = queue.popleft()
        if abs(cx - x1) <= target_r and abs(cy - y1) <= target_r:
            return True
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if (bx0 <= nx < bx1 and by0 <= ny < by1
                        and line_mask[ny, nx] and (nx, ny) not in visited):
                    visited.add((nx, ny))
                    queue.append((nx, ny))
    return False


def merge_close_vertices(vertices, edges, radius=30, line_mask=None):
    """Merge vertices within `radius` pixels of each other.

    Pass 1: merge edge-connected pairs within radius (original behavior).
    Pass 2 (if line_mask provided): merge unconnected pairs within radius
    that are connected via raster pixels.  This catches skeleton junction
    artifacts while preserving cases like Bloat Root where two vertices
    are close but on separate raster paths.
    """
    n = len(vertices)
    if n == 0:
        return vertices, edges

    edge_set = set(tuple(sorted(e)) for e in edges)

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

    # Pass 1: merge edge-connected pairs within radius
    merges = 0
    for a, b in edge_set:
        dx = vertices[a][0] - vertices[b][0]
        dy = vertices[a][1] - vertices[b][1]
        if abs(dx) <= radius and abs(dy) <= radius:
            if (dx*dx + dy*dy)**0.5 <= radius:
                union(a, b)
                merges += 1

    # Pass 2: merge unconnected pairs within radius IF raster-connected
    raster_merges = 0
    if line_mask is not None:
        for a in range(n):
            for b in range(a + 1, n):
                if find(a) == find(b):
                    continue
                dx = vertices[a][0] - vertices[b][0]
                dy = vertices[a][1] - vertices[b][1]
                dist = (dx*dx + dy*dy)**0.5
                if dist <= radius:
                    ax, ay = vertices[a]
                    bx, by = vertices[b]
                    if _raster_connected(line_mask, ax, ay, bx, by):
                        union(a, b)
                        raster_merges += 1

    if merges == 0 and raster_merges == 0:
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
    msg = f"  Vertex merge: {len(multi)} clusters ({sum(len(m) for m in multi.values())} vertices -> {len(multi)})"
    if raster_merges:
        msg += f" ({raster_merges} raster-connected)"
    print(msg)

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


def validate_edges(vertices, edges, line_mask, min_coverage=0.3, sample_step=3,
                    buffer_px=4):
    """Remove edges that don't follow raster lines.

    For each edge, sample points along the straight line between the two
    vertices and check what fraction falls within `buffer_px` of the
    line_mask.  Edges below `min_coverage` are spurious.
    """
    from scipy.ndimage import distance_transform_edt

    h, w = line_mask.shape
    dt = distance_transform_edt(~line_mask)

    kept = []
    removed = 0
    for a, b in edges:
        ax, ay = vertices[a]
        bx, by = vertices[b]
        dx, dy = bx - ax, by - ay
        length = max(1, int((dx * dx + dy * dy) ** 0.5))
        n_samples = max(3, length // sample_step)
        on_mask = 0
        for s in range(n_samples):
            t = s / (n_samples - 1)
            sx = int(round(ax + dx * t))
            sy = int(round(ay + dy * t))
            if 0 <= sy < h and 0 <= sx < w and dt[sy, sx] <= buffer_px:
                on_mask += 1
        coverage = on_mask / n_samples
        if coverage >= min_coverage:
            kept.append([a, b])
        else:
            removed += 1

    if removed:
        print(f"  Edge validation: removed {removed} spurious edges "
              f"(coverage < {min_coverage}, buffer={buffer_px}px)")
    return kept


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
        nv, ne = merge_close_vertices(nv, ne, radius=args.merge_radius,
                                      line_mask=line_mask)

    ne = validate_edges(nv, ne, line_mask)

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
