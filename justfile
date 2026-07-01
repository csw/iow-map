# Rebuild iow-map.html and index.html from tools/app_template.html
# (both are generated files -- never edit them directly, see CLAUDE.md)
build:
    uv run python tools/build_all.py --skip-extract

# Full rebuild: re-extract graphs from maps/ then rebuild both HTML files
build-all:
    uv run python tools/build_all.py

# Regenerate assets/og-image.jpg from a live render of the app
og-image:
    uv run python tools/gen_og_image.py

# Regenerate assets/screenshot.png (README) from a live render of the app
screenshot:
    uv run python tools/gen_screenshot.py
