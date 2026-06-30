---
name: verify-map-labels
description: Re-verify label-to-vertex assignments for IOW map tracker maps (this repo, csw/iow-map) by visually tracing each map's connector lines from label text to the graph node it points at, then fixing tools/corrections.py. Use this whenever the user asks to check, fix, redo, or audit map labels, "labels_px", label assignments, or work item 10 from docs/HANDOFF.md, for any map (central_reef, east_reef, the_bloom_main, dusk_slopes, brine_pool, the_anomaly_lower_level, the_anomaly_upper_level, or the bloom_site_2 levels). Also use it proactively after any change to extract_graph.py or corrections.py that could shift vertex indices, since label assignments are pixel-coordinate-based and can silently snap to the wrong vertex.
---

# Verify Map Labels

## Why this exists

`tools/corrections.py` stores each label as `(x, y): "Label Name"` in
`MAP_METADATA[key]["labels_px"]`. At build time, `resolve_labels()` snaps
`(x, y)` to the nearest extracted vertex (within 80px). The bug pattern this
skill exists to catch and fix: many entries were placed near the **label
text** on the map image instead of near the **vertex the connector line
actually points to** — so they silently resolve to the wrong (often nearby
but topologically distinct) vertex. There's no build-time error for this;
it only shows up as a visually wrong label in the rendered app.

Some `labels_px` entries are **synthetic** — markers we invented for
entry/exit/start nodes (e.g. "Game Start", "To The Bloom") that have no
real text/line on the raster map. Don't go hunting for a connector line
that doesn't exist; leave these alone unless something else is wrong.

**A label currently resolving cleanly (small or even zero snap distance) is
not proof it's correct.** That only means the stored coordinate is close to
*some* vertex — it says nothing about whether that coordinate was placed
correctly in the first place. Every entry needs an independent visual trace
of its connector line; don't skip entries just because they "look fine" in
`corrections.py`.

## Workflow

This works directly from the map JPEG and the structured vertex data — no
browser or interactive viewer needed for the core loop. Use `Bash` to crop
with PIL, `Read` to view the crop, and the bundled script to turn a traced
pixel position into an exact vertex.

1. **List the map's `labels_px` entries.** Read the relevant
   `_correct_<map_key>` / `MAP_METADATA[key]["labels_px"]` block in
   `tools/corrections.py` to get the current `(x, y): "Label Name"` pairs
   you're about to verify.

2. **For each label, crop and look.** Crop a generous region (roughly
   ±400-600px) of `maps/<key>.jpg` around the label's current coordinate
   with PIL, and view it with `Read`:
   ```python
   from PIL import Image
   im = Image.open('maps/central_reef.jpg')
   crop = im.crop((x0, y0, x1, y1))
   crop.save('/tmp/crops/some_label.png')
   ```
   Find the label text (color and connector-line color vary per map, and
   sometimes per label within a map — e.g. gray lines mark "object of
   interest" labels on some maps — don't assume white text / white lines).
   Follow the connector line from the text to wherever it appears to end.

   **Then crop tight around just that apparent endpoint** (a ~150-300px
   box, optionally resized 2-3x with `Image.NEAREST` for a pixelated
   close-up) and confirm the line actually *terminates* there — typically
   at a yellow triangle vertex marker — rather than merely passing near a
   junction on its way somewhere else. A line can cross close to a vertex
   without stopping there; only the tight crop reveals the difference.
   Lines this thin are also where most past mistakes came from — when in
   doubt, crop tighter rather than trusting a wide view.

   If two labels share the same name, expect two separate connector lines
   diverging from text that's positioned between/near both — trace each
   one individually to its own distinct terminus (see "Duplicate label
   names are normal" below).

3. **Snap your traced point to the real vertex.** Don't hand-type the
   vertex's coordinates by eyeballing the crop — feed your approximate
   endpoint into the bundled script and use its exact answer:
   ```
   uv run python .claude/skills/verify-map-labels/scripts/nearest_vertex.py <map_key> <x> <y> [N]
   ```
   This prints the N nearest extracted vertices (default 5) with their
   exact pixel coordinates, distance from your point, and whatever label
   (if any) is currently resolved there. Use the distances and the
   currently-resolved labels as a sanity check — e.g. if the nearest
   vertex is already claimed by a clearly-unrelated label, you may have
   the wrong cluster and should re-examine the crop.

4. **Write the correction back into `corrections.py`.** Use the exact
   vertex coordinates from step 3, and add a trailing comment recording
   where the label text itself sits (eyeballed from the wide crop is fine
   for this part, it's just documentation):
   ```python
   (2417, 1065): "Waystation",   # text@(2390, 1010)
   ```
   This comment doesn't affect resolution, but it means a future
   verification pass can jump straight to the text instead of re-scanning
   the whole map image.

5. **Rebuild and check for warnings.**
   ```
   uv run python tools/build_all.py --skip-extract --maps <map_key>
   ```
   Watch for `WARN: label '...' — no vertex within 80px` — that means your
   corrected coordinate landed too far from any real vertex (typo, wrong
   map, or the vertex really doesn't exist in the extracted graph — check
   the raw graph in `overlays/viewer.html` if so). A clean rebuild with no
   warnings is necessary but not sufficient — it confirms every coordinate
   snapped to *some* vertex, not that it's the *right* one, so it doesn't
   replace the visual trace in steps 2-3.

### Optional: visual overview pass

For a final whole-map spot-check (or if you want to eyeball many labels at
once rather than crop-and-trace one at a time), there's a bundled debug
viewer:

```
uv run python .claude/skills/verify-map-labels/scripts/gen_debug_data.py
cp .claude/skills/verify-map-labels/assets/label_debug_viewer.html .
python3 -m http.server 8765 &
```

Then open `http://localhost:8765/label_debug_viewer.html`, pick the map,
and use the "Focus" dropdown to inspect one resolved label at a time (it
draws that label's text + leader line + target ring; everything else
collapses to a small unlabeled ring so dense clusters of nearby labels
don't pile their text boxes on top of each other). Hover any vertex for an
exact-pixel-coordinate tooltip. Re-run `gen_debug_data.py` after any
`corrections.py` edit to keep the viewer in sync.

This is a good way to *notice* something looks off, but the crop-and-trace
workflow above (steps 1-5) is what actually confirms and fixes it — the
viewer shows you the *currently resolved* vertex, not the ground truth.

**If markers in the viewer look like giant solid blobs covering the map**,
its marker-sizing got reverted/broken. The fix: marker/text size in
image-space must be `constant_screen_px / scale` (shrinks as you zoom out,
since the draw call is wrapped in `ctx.scale(scale, scale)`). A
`Math.max(floor, constant / scale)` pattern is the bug — the floor stops it
from ever shrinking, so markers stay pinned to a large fixed *screen* size
at every zoom level and bury the map underneath them.

## Duplicate label names are normal

The game reuses item/creature names across multiple distinct nodes on the
same map — e.g. Central Reef has two separate "Soothespore" nodes and two
separate "Stalk Spore" nodes; Brine Pool has three separate "Mucus Bubble"
nodes. Don't treat a repeated name as evidence of a duplicate/erroneous
entry — verify each occurrence independently by tracing its own connector
line, and keep all of them if each genuinely points at a distinct vertex.
Only flag one as spurious if its connector line doesn't actually exist or
doesn't terminate at any real vertex.

When two same-named labels' connector lines both originate near the same
text, they can look at low zoom like one line that bends — tight-crop each
apparent terminus separately and confirm with `nearest_vertex.py`; a stray
vertex that happens to sit close to where one line *passes* (but doesn't
end) is an easy false match.

## Doing this across multiple maps

Each map's label set, color scheme, and connector-line style is
independent and idiosyncratic — re-derive what "the label text" and "the
connector line" look like per map rather than carrying assumptions from
the last one. One agent per map (in parallel) works well once you've
validated the process end-to-end on a single map first — don't fan out to
all maps before confirming the workflow above actually produces a sane,
checkable result on one map.

If delegating to a subagent: state explicitly that it should perform real
tool calls (crop, read, trace) right now and report findings — an agent
resumed via an async message can otherwise reply with an
acknowledgment/plan instead of doing the visual work.

## Output format (when reporting findings, e.g. from a subagent)

```
LABEL: "Name" | TEXT: (tx,ty) | TARGET: OK | reason
LABEL: "Name" | TEXT: (tx,ty) | TARGET: (x,y) | reason for the change
LABEL: "Name" | TEXT: N/A | TARGET: OK | synthetic marker, no real connector line
```

## Reference: `corrections.py` shape

- `MAP_METADATA[key]["labels_px"]`: `{(x, y): "Label Name", ...}` — the
  thing this skill fixes.
- `resolve_labels(map_key, verts_px, max_dist=80)`: snaps each `labels_px`
  coordinate to the nearest vertex within `max_dist` pixels; this is what
  actually runs at build time.
- Pixel coordinates are against the full-resolution source image in
  `maps/<key>.jpg`, not the downscaled/display version.
