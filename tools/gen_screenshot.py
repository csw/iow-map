#!/usr/bin/env python3
"""Regenerate assets/screenshot.png: a full-window screenshot for the README.

Uses a small viewport (so it reads like a phone-sized screen) and a 2x device
scale factor so text renders crisply, saved as PNG (no JPEG artifacts).

Usage: uv run python tools/gen_screenshot.py
"""
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "screenshot.png"
VIEWPORT = {"width": 480, "height": 560}
DEVICE_SCALE_FACTOR = 2

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
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR)
            page.goto(f"http://127.0.0.1:{port}/index.html")
            page.evaluate(SETUP_JS)
            page.wait_for_timeout(300)  # let render()/CSS settle
            page.screenshot(path=str(OUT))
            browser.close()
    finally:
        server.shutdown()

    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
