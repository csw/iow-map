#!/usr/bin/env python3
"""Regenerate assets/og-image.jpg from a live render of index.html.

Usage: uv run python tools/gen_og_image.py
"""
import functools
import http.server
import io
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "og-image.jpg"
TARGET_W, TARGET_H = 1200, 630

# BFS out from Central Reef's Game Start to build an interesting explored
# chain: several visited nodes plus a couple of frontier nodes still glowing.
SETUP_JS = """
() => {
  localStorage.clear();
  buildMap('central_reef');
  const start = cur;
  const visited = new Set([start]);
  const queue = [start];
  while (queue.length && visited.size < 9) {
    const n = queue.shift();
    for (const [a, b] of E) {
      let other = null;
      if (a === n) other = b; else if (b === n) other = a;
      if (other != null && !visited.has(other)) { visited.add(other); queue.push(other); }
    }
  }
  vis = visited;
  cur = [...visited][visited.size - 3]; // a node partway along the chain, not the very end
  fog = true;
  save();
  buildMap('central_reef');
}
"""


def main():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(f"http://127.0.0.1:{port}/index.html")
            page.evaluate(SETUP_JS)
            page.wait_for_timeout(300)  # let render()/CSS settle
            map_el = page.query_selector("#map")
            png_bytes = map_el.screenshot()
            browser.close()
    finally:
        server.shutdown()

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    scale = max(TARGET_W / img.width, TARGET_H / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (resized.width - TARGET_W) // 2
    top = (resized.height - TARGET_H) // 2
    cropped = resized.crop((left, top, left + TARGET_W, top + TARGET_H))

    OUT.parent.mkdir(exist_ok=True)
    cropped.save(OUT, "JPEG", quality=87)
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
