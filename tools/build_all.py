#!/usr/bin/env python3
"""
IOW Map Tracker — Master Build Script
======================================

Runs the full pipeline:
  1. Extract graphs from map images using per-map config
  2. Apply post-extraction corrections
  3. Resolve metadata (labels, EN, GS) to vertex indices
  4. Generate iow-map.html (S3 URLs) and index.html (relative paths)

Usage:
  python tools/build_all.py                    # full rebuild
  python tools/build_all.py --maps central_reef east_reef  # specific maps
  python tools/build_all.py --skip-extract     # rebuild HTML from existing graphs
  python tools/build_all.py --overlay-dir overlays/  # save debug overlays

Requires: scikit-image, Pillow, scipy, numpy
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Add tools/ to path so we can import corrections
sys.path.insert(0, str(Path(__file__).parent))
from corrections import (
    EXTRACTION_CONFIG, MAP_METADATA, KNOWN_ISSUES,
    apply_corrections, resolve_labels, resolve_en, resolve_gs,
)

ROOT = Path(__file__).parent.parent
MAPS_DIR = ROOT / "maps"
GRAPHS_DIR = ROOT / "graphs"
TOOLS_DIR = ROOT / "tools"
EXTRACT_SCRIPT = TOOLS_DIR / "extract_graph.py"

IMG_BASE_S3 = "https://csw-public-data.s3.us-east-1.amazonaws.com/IOW/maps"

MAP_ORDER = [
    "central_reef", "east_reef", "the_bloom_main", "dusk_slopes",
    "brine_pool", "the_anomaly_lower_level", "the_anomaly_upper_level",
    "the_bloom_site_2_level_1", "the_bloom_site_2_level_2",
    "the_bloom_site_2_level_3", "the_bloom_site_2_level_4",
]


def extract_map(map_key, overlay_dir=None):
    """Run extract_graph.py for a single map. Returns (map_key, ok, lines)."""
    cfg = EXTRACTION_CONFIG[map_key]
    img_path = MAPS_DIR / f"{map_key}.jpg"
    out_path = GRAPHS_DIR / f"{map_key}_graph.json"

    if not img_path.exists():
        return (map_key, False, [f"  SKIP: {img_path} not found"])

    cmd = [
        sys.executable, str(EXTRACT_SCRIPT), str(img_path),
        "--seed", cfg["seed"],
        "--threshold", str(cfg["threshold"]),
        "--epsilon", str(cfg["epsilon"]),
        "--merge-radius", str(cfg["merge_radius"]),
        "--output", str(out_path),
    ]
    if cfg.get("seed2"):
        cmd.extend(["--seed2", cfg["seed2"]])
    if cfg.get("detect_triangles"):
        cmd.extend(["--detect-triangles"])
    if overlay_dir:
        overlay_path = Path(overlay_dir) / f"{map_key}_overlay.png"
        cmd.extend(["--overlay", str(overlay_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = [f"  Extracting {map_key}..."]
    if result.returncode != 0:
        lines.append(f"  ERROR: {result.stderr[:200]}")
        return (map_key, False, lines)

    for line in result.stdout.split("\n"):
        if any(k in line for k in ["Result:", "After merge:", "After insertion:"]):
            lines.append(f"    {line.strip()}")

    return (map_key, True, lines)


def apply_corrections_to_graph(map_key):
    """Load graph JSON, apply corrections in memory. Returns corrected data
    without modifying the JSON file (keeps it as raw extraction output)."""
    graph_path = GRAPHS_DIR / f"{map_key}_graph.json"
    if not graph_path.exists():
        return None

    with open(graph_path) as f:
        data = json.load(f)

    verts_px = data["vertices_px"]
    edges = data["edges"]
    w, h = data["image_w"], data["image_h"]

    verts_px, edges = apply_corrections(map_key, verts_px, edges, w, h)

    verts_norm = [[round(x / w, 4), round(y / h, 4)] for x, y in verts_px]

    data["vertices"] = verts_norm
    data["vertices_px"] = verts_px
    data["edges"] = edges

    return data


def build_html(output_path, corrected_graphs, use_relative_paths=False):
    """Generate the HTML app from corrected graph data + metadata."""
    template_path = TOOLS_DIR / "app_template.html"
    if not template_path.exists():
        print(f"ERROR: {template_path} not found")
        return False

    with open(template_path) as f:
        template = f.read()

    maps_entries = []
    for key in MAP_ORDER:
        if key not in corrected_graphs:
            print(f"  SKIP: {key} not available")
            continue

        g = corrected_graphs[key]
        meta = MAP_METADATA[key]
        verts_px = g["vertices_px"]
        iw, ih = g["image_w"], g["image_h"]

        # Resolve metadata to vertex indices
        lbl = resolve_labels(key, verts_px)
        en = resolve_en(key, verts_px)
        gs = resolve_gs(key, verts_px)

        if use_relative_paths:
            img_url = f"maps/{key}.jpg"
        else:
            img_url = f"{IMG_BASE_S3}/{key}.jpg"

        parts = [f'name:"{meta["name"]}"']
        if en is not None:
            parts.append(f"EN:{json.dumps(en)}")
        parts.append(f'img:"{img_url}"')
        parts.append(f"IW:{iw},IH:{ih}")
        parts.append(f"GS:{gs if gs is not None else 'null'}")
        parts.append(f"FR:{meta['FR']}")

        lbl_js = (
            "{"
            + ",".join(
                f'{k}:"{v}"' for k, v in sorted(lbl.items(), key=lambda x: x[0])
            )
            + "}"
        )
        parts.append(f"LBL:{lbl_js}")
        parts.append(f"V:{json.dumps(g['vertices'])}")
        parts.append(f"E:{json.dumps(g['edges'])}")

        maps_entries.append(f"  {key}:{{{','.join(parts)}}}")

        print(f"  {meta['name']:25s} {len(g['vertices']):3d}v {len(g['edges']):3d}e "
              f" {len(lbl)} labels  EN={en}  GS={gs}")

    maps_js = "const MAPS={\n" + ",\n".join(maps_entries) + "\n};"
    html = template.replace("/* __MAPS_DATA__ */", maps_js)

    with open(output_path, "w") as f:
        f.write(html)

    print(f"\nWrote {output_path} ({len(html)} chars)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build IOW Map Tracker")
    parser.add_argument("--maps", nargs="*", help="Specific maps to extract")
    parser.add_argument("--skip-extract", action="store_true",
                        help="Skip extraction, just rebuild HTML from existing graphs")
    parser.add_argument("--overlay-dir", help="Save debug overlays to this directory")
    args = parser.parse_args()

    maps_to_process = args.maps or MAP_ORDER
    GRAPHS_DIR.mkdir(exist_ok=True)

    if args.overlay_dir:
        Path(args.overlay_dir).mkdir(parents=True, exist_ok=True)

    # Step 1: Extract (parallel — each map is an independent subprocess)
    if not args.skip_extract:
        print("=== Step 1: Extract graphs ===")
        extract_keys = [k for k in maps_to_process if k in EXTRACTION_CONFIG]
        unknown = [k for k in maps_to_process if k not in EXTRACTION_CONFIG]
        for k in unknown:
            print(f"  SKIP: unknown map '{k}'")

        workers = min(len(extract_keys), os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(extract_map, k, args.overlay_dir): k
                for k in extract_keys
            }
            results = {}
            for fut in as_completed(futures):
                key, ok, lines = fut.result()
                results[key] = (ok, lines)

        for key in extract_keys:
            ok, lines = results[key]
            for line in lines:
                print(line)

    # Step 2: Apply corrections (in memory only — graph JSONs stay as raw extraction output)
    print("\n=== Step 2: Apply corrections ===")
    corrected = {}
    for key in MAP_ORDER:
        data = apply_corrections_to_graph(key)
        if data:
            corrected[key] = data
            print(f"  {key}: {len(data['vertices'])}v {len(data['edges'])}e")

    # Step 3: Build HTML
    print("\n=== Step 3: Build HTML ===")
    build_html(ROOT / "iow-map.html", corrected, use_relative_paths=False)
    build_html(ROOT / "index.html", corrected, use_relative_paths=True)

    # Print known issues
    issues = {k: v for k, v in KNOWN_ISSUES.items() if k in maps_to_process}
    if issues:
        print("\n=== Known Issues ===")
        for key, desc in issues.items():
            print(f"  {key}: {desc[:100]}...")


if __name__ == "__main__":
    main()
