# In Other Waters: Map Tracker

**[Open the live map →](https://csw.github.io/iow-map/)**

Interactive fog-of-war map tracker for *In Other Waters*. The game has no in-game map while diving, so this tool lets you track visited nodes, see frontier nodes, and take notes across all 11 map areas.

![Screenshot of the map tracker showing a partially-revealed Central Reef](assets/screenshot.png)

This uses the excellent [maps](https://steamcommunity.com/sharedfiles/filedetails/?id=2784267318) created by, er, [Hugh Janis](https://steamcommunity.com/profiles/76561198128927251) and posted as a Steam community guide.

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
uv sync

# Add map images to maps/ directory, then:
just build-all
```

This runs the full pipeline: extract graphs from map images → apply manual corrections → generate HTML. Both `iow-map.html` and `index.html` are always regenerated together.

After editing `tools/app_template.html` or `tools/corrections.py`, skip re-extraction with `just build`.

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
