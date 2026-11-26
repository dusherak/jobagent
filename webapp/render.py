"""Render a tailored pack to PDF with headless Chrome (run with jobfeed/.venv/bin/python).

Usage: render.py <pack_dir>   (reads cv.json, cl.json; writes cv.pdf, cl.pdf; prints JSON with scale/overflow)
The CV is shrunk in small steps (down to 90%) until it fits on one page.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docs import cl_html, cv_html  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main(pack):
    pack = Path(pack)
    cv = json.loads((pack / "cv.json").read_text())
    cl = json.loads((pack / "cl.json").read_text()) if (pack / "cl.json").exists() else None
    out = {"scale": 1.0, "overflow": False}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page()
        scale = 1.0
        while True:
            pg.set_content(cv_html(cv, scale), wait_until="networkidle")
            fits = pg.evaluate("() => { const el = document.querySelector('.page'); return el.scrollHeight <= el.clientHeight + 1; }")
            if fits or scale <= 0.9:
                out.update(scale=round(scale, 2), overflow=not fits)
                break
            scale -= 0.02
        pg.pdf(path=str(pack / "cv.pdf"), width="8.5in", height="11in", print_background=True, page_ranges="1")
        if cl:
            pg.set_content(cl_html(cv, cl), wait_until="networkidle")
            out["cl_pages"] = pg.evaluate("() => Math.ceil(document.querySelector('.page').scrollHeight / (11 * 96))")
            pg.pdf(path=str(pack / "cl.pdf"), width="8.5in", height="11in", print_background=True)
        b.close()
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1])
