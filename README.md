# In Other Waters — Map Tracker

Interactive fog-of-war map tracker for *In Other Waters*. The game has no in-game map while diving, so this tool lets you track visited nodes, see frontier nodes, and take notes across all 11 map areas.

This uses the excellent [maps](https://steamcommunity.com/sharedfiles/filedetails/?id=2784267318) created by, er, Hugh Janis and posted on the Steam forums.

## Quick Start

**Use directly:** Download `iow-map.html` and open it (images load from S3).

**GitHub Pages:** Push to main → auto-deploys. Add your map JPEGs to `maps/`.

### Controls

- **Tap** a frontier node (orange outline) to visit it
- **Drag** to pan, **pinch** to zoom
- **Fog toggle** reveals/hides unexplored areas
- **Note mode** lets you annotate any node
- **Undo** reverts the last action (30-deep stack)

## Building from Source

```bash
pip install scikit-image Pillow scipy numpy

# Add map images to maps/ directory, then:
python tools/build_all.py
```

This runs the full pipeline: extract graphs from map images → apply manual corrections → generate HTML.

See `docs/HANDOFF.md` for full architecture documentation.

## Project Structure

| Path | Description |
|------|-------------|
| `iow-map.html` | Standalone app (S3 image URLs, for phone use) |
| `index.html` | GitHub Pages app (relative `maps/` paths) |
| `tools/corrections.py` | **Source of truth** for all manual adjustments and metadata |
| `tools/extract_graph.py` | Graph extraction: fuzzy select → skeletonize → Douglas-Peucker |
| `tools/build_all.py` | Master build script |
| `graphs/*.json` | Extracted + corrected graph data |

## License

MIT
