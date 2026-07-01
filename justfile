# Rebuild index.html from tools/app_template.html
# (index.html is a generated file -- never edit it directly, see CLAUDE.md)
build:
    uv run python tools/build.py --skip-extract

# Full rebuild: re-extract graphs from maps/ then rebuild index.html
build-all:
    uv run python tools/build.py

# Regenerate assets/og-image.jpg from a live render of the app
og-image:
    uv run python tools/gen_og_image.py

# Regenerate assets/screenshot.png (README) from a live render of the app
screenshot:
    uv run python tools/gen_screenshot.py

# Install the pre-commit hook that checks index.html is up to date
install-hooks:
    cp tools/hooks/pre-commit .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
