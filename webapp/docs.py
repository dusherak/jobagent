"""HTML builders for the CV and cover letter (no dependencies, used by the server and by render.py).

Default CV styling (classic one-page finance CV): Garamond, 16pt bold name, 9pt contact line,
bold section rules, 9.5pt body, org/location then italic role/dates with right-aligned tabs, US Letter.
"""

import base64
import html
from datetime import date
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import userdata as U  # noqa: E402
SIGNATURE = U.CV_DIR / "signature.png"   # optional
FIT = ("<script>function fit(){var p=document.querySelector('.page');p.style.zoom=Math.min(1,(innerWidth-32)/816);}"
       "addEventListener('resize',fit);addEventListener('load',fit);fit();</script>")
FONTS = '<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">'
e = lambda s: html.escape(str(s or ""))

CV_CSS = """
@page { size: 8.5in 11in; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #fff; color: #000; }
.page { width: 8.5in; height: 11in; padding: 0.92cm 1.32cm 0.71cm; font-family: "EB Garamond", Garamond, "Times New Roman", serif;
        font-size: calc(9.5pt * var(--s, 1)); line-height: 1.2; overflow: hidden; }
h1 { font-size: calc(16pt * var(--s, 1)); font-weight: 700; text-align: center; margin: 0; letter-spacing: 0.02em; text-transform: uppercase; }
.contact { text-align: center; font-size: calc(9pt * var(--s, 1)); margin: 1pt 0 0; }
h2 { font-size: calc(10.5pt * var(--s, 1)); font-weight: 700; text-transform: uppercase; margin: calc(5pt * var(--s, 1)) 0 calc(2pt * var(--s, 1));
     border-bottom: 0.6pt solid #000; padding-bottom: 0.5pt; }
.line { display: flex; justify-content: space-between; gap: 12pt; }
.org { font-weight: 700; } .loc { font-weight: 700; } .role, .dates { font-style: italic; }
.entry { margin-top: calc(2.5pt * var(--s, 1)); }
ul { margin: 0.5pt 0 0; padding-left: 13pt; } li { margin: 0; padding-left: 1pt; }
.skills p { margin: 0.5pt 0; } .skills b { font-weight: 700; }
"""


def cv_html(cv, scale=1.0, for_screen=False):
    parts = [f'<h1>{e(cv["name"])}</h1>', f'<div class="contact">{e(cv["contact"])}</div>']
    for sec in cv["sections"]:
        parts.append(f'<h2>{e(sec["title"])}</h2>')
        for en in sec["entries"]:
            bullets = "".join(f"<li>{e(b)}</li>" for b in en.get("bullets", []) if b.strip())
            parts.append(f'''<div class="entry"><div class="line"><span class="org">{e(en["org"])}</span><span class="loc">{e(en.get("location"))}</span></div>
              <div class="line"><span class="role">{e(en.get("role"))}</span><span class="dates">{e(en.get("dates"))}</span></div>
              {f"<ul>{bullets}</ul>" if bullets else ""}</div>''')
    if cv.get("skills"):
        parts.append('<h2>Skills &amp; Interests</h2><div class="skills">' +
                     "".join(f'<p><b>{e(s["label"])}:</b> {e(s["text"])}</p>' for s in cv["skills"]) + "</div>")
    screen = "body{background:#e7e5e4;padding:16px} .page{margin:0 auto;box-shadow:0 1px 8px rgba(0,0,0,.15)}" if for_screen else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>{CV_CSS}{screen}</style></head>'
            f'<body><div class="page" style="--s:{scale}">{"".join(parts)}</div>{FIT if for_screen else ""}</body></html>')


CL_CSS = """
@page { size: 8.5in 11in; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #fff; color: #000; }
.page { width: 8.5in; min-height: 11in; padding: 2.2cm 2.3cm; font-family: "EB Garamond", Garamond, "Times New Roman", serif; font-size: 11.5pt; line-height: 1.35; }
.from { text-align: right; font-weight: 700; line-height: 1.25; }
.to { font-weight: 700; margin-top: 18pt; line-height: 1.25; }
.salutation { margin-top: 18pt; }
p { margin: 0 0 9pt; text-align: justify; hyphens: auto; }
.close { margin-top: 12pt; } .sig { height: 34pt; margin: 4pt 0 0; } .name { margin-top: 2pt; }
"""


def cl_html(cv, cl, for_screen=False):
    today = cl.get("date") or date.today().strftime("%d/%m/%Y")
    to_lines = "<br>".join(e(x) for x in ([cl.get("company", "")] + cl.get("address_lines", [])) if x)
    sig = ""
    if SIGNATURE.exists():
        sig = f'<img class="sig" src="data:image/png;base64,{base64.b64encode(SIGNATURE.read_bytes()).decode()}" alt="">'
    paras = "".join(f"<p>{e(p)}</p>" for p in cl.get("paragraphs", []) if p.strip())
    screen = "body{background:#e7e5e4;padding:16px} .page{margin:0 auto;box-shadow:0 1px 8px rgba(0,0,0,.15)}" if for_screen else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>{CL_CSS}{screen}</style></head><body><div class="page">'
            f'<div class="from">{e(cv["name"])}<br>{"<br>".join(e(a) for a in cv.get("address", []))}<br>{e(today)}</div>'
            f'<div class="to">{to_lines}</div><p class="salutation">{e(cl.get("salutation") or "Dear Sir or Madam,")}</p>{paras}'
            f'<p class="close">Kind regards,</p>{sig}<div class="name">{e(cv["name"])}</div></div>{FIT if for_screen else ""}</body></html>')
