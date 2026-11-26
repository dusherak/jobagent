"""Read careers pages that only show jobs after JavaScript runs.

Run with the isolated venv (Playwright + Scrapling's parser):
    jobfeed/.venv/bin/python jobfeed/rendered.py

Opens each page in your installed Google Chrome (headless, normal mode: no stealth,
no fingerprint spoofing), waits for it to load, and collects job links. If a page shows
a bot check / CAPTCHA, it is skipped and reported, never bypassed.
Prints a JSON list of jobs to stdout.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from datetime import date, datetime, timedelta

from playwright.sync_api import sync_playwright
from scrapling.parser import Selector

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import userdata as U  # noqa: E402  (where user data lives)
UA = "Mozilla/5.0 (Macintosh) personal-job-search/0.1 (individual use)"
BLOCK_MARKERS = ("just a moment", "quick check", "human verification", "captcha", "attention required", "access denied")


def texts(node):
    return [t.strip() for t in node.css("::text").getall() if t.strip()]


def ago_to_date(text):
    t, today = text.lower(), date.today()
    if "hour" in t or "minute" in t or "today" in t or "just" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*(day|week|month)", t)
    if not m:
        return ""
    n = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
    return (today - timedelta(days=n)).isoformat()


def parse_efc(sel, base):
    """eFinancialCareers job cards: title, company, location, type, salary, 'N days ago'."""
    out = []
    for card in sel.css("efc-job-card"):
        a = next((x for x in card.css("a") if re.search(r"\.id\d+", x.attrib.get("href") or "")), None)
        if not a:
            continue
        parts = [t for t in texts(card) if t not in ("Apply now", "Save", "Easy Apply", "Featured")]
        ago = next((t for t in reversed(parts) if re.search(r"ago|today|yesterday", t, re.I)), "")
        out.append({"title": parts[0] if parts else "", "company": parts[1] if len(parts) > 1 else "",
                    "location": parts[2] if len(parts) > 2 else "", "posted": ago_to_date(ago),
                    "url": urljoin(base, a.attrib["href"].split("?")[0])})
    return out


def parse_gradcracker(sel, base):
    """Gradcracker cards: title in h2, company from the /hub/<id>/<company>/ link, deadline + location in the card."""
    out, seen = [], set()
    for h2 in sel.css("h2"):
        a = h2.css("a") or ([h2.parent] if h2.parent.tag == "a" else [])
        href = a[0].attrib.get("href", "") if a else ""
        m = re.search(r"/hub/(\d+)/([\w-]+)/graduate-job/", href)
        if not m or m.group(1) == "9000001" or href in seen:
            continue
        seen.add(href)
        card = h2
        for _ in range(4):
            card = card.parent
        blob = " ".join(texts(card))
        dl = re.search(r"Deadline\s+([A-Z][a-z]+ \d{1,2})(?:st|nd|rd|th)?,? (\d{4})", blob)
        deadline = ""
        if dl:
            try:
                deadline = datetime.strptime(f"{dl.group(1)} {dl.group(2)}", "%B %d %Y").date().isoformat()
            except ValueError:
                pass
        loc = re.search(r"Location\s+(.*?)(?:\s+Degree required|\s+Salary|$)", blob)
        out.append({"title": " ".join(texts(h2)), "company": m.group(2).replace("-", " ").title(),
                    "location": loc.group(1) if loc else "", "deadline": deadline, "url": urljoin(base, href)})
    return out


PARSERS = {"efc": parse_efc, "gradcracker": parse_gradcracker}


def main():
    sources = json.loads(U.config("sources.json").read_text()).get("rendered", {})
    jobs, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for company, cfg in sources.items():
            page = browser.new_page(user_agent=UA)
            try:
                for url in cfg["urls"]:
                    page.goto(url, wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(cfg.get("wait_ms", 6000))
                    html = page.content()
                    if any(m in (page.title() + html[:3000]).lower() for m in BLOCK_MARKERS):
                        errors.append(f"{company}: bot check shown, skipped")
                        break
                    sel = Selector(html)
                    if cfg.get("parser") in PARSERS:
                        for j in PARSERS[cfg["parser"]](sel, url):
                            j["company"] = j.get("company") or company
                            j["board"] = company
                            jobs.append(j)
                        page.wait_for_timeout(cfg.get("gap_ms", 0))
                        continue
                    pattern = re.compile(cfg["link"])
                    for a in sel.css("a"):
                        href = a.attrib.get("href") or ""
                        if not pattern.search(href):
                            continue
                        text = re.sub(r"\s+", " ", " ".join(a.css("::text").getall())).strip()
                        if not text:
                            continue
                        jobs.append({"company": company, "text": text, "url": urljoin(url, href)})
            except Exception as e:
                errors.append(f"{company}: {type(e).__name__}")
            finally:
                page.close()
        browser.close()
    json.dump({"jobs": jobs, "errors": errors}, sys.stdout)


if __name__ == "__main__":
    main()
