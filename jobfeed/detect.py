"""Find which public job-board system (ATS) each candidate company uses.

Usage: python3 jobfeed/detect.py [candidates.csv] [out.csv]

Tries slug guesses against the public, unauthenticated job-board APIs of
Greenhouse, Lever, Ashby, SmartRecruiters and Workable. Results need a quick
human review: a slug like "bain" can belong to a different company.
"""

import csv
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import userdata as U  # noqa: E402  (where user data lives)
CITY = U.city().lower()
UA = {"User-Agent": "personal-job-search/0.1 (individual use)"}
GENERIC = {"partners", "capital", "group", "management", "international", "consulting",
           "bank", "banking", "co", "company", "the", "and", "markets", "securities",
           "advisory", "associates", "trading", "investors", "research", "technologies",
           "strategy", "consultants", "global", "energy", "equity"}


def get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None, None


def slugs(name):
    base = name.lower().replace("&", " and ").replace(".", "").replace("'", "")
    words = re.findall(r"[a-z0-9]+", base)
    core = [w for w in words if w not in GENERIC] or words
    out = ["".join(words), "-".join(words), "".join(core), "-".join(core)]
    no_and = [w for w in words if w != "and"]
    out += ["".join(no_and), "-".join(no_and)]
    if len(core[0]) >= 4:
        out.append(core[0])
    seen, res = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            res.append(s)
    return res


def london(text):
    return CITY in (text or "").lower()


def try_greenhouse(s):
    st, d = get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs")
    if st == 200 and isinstance(d, dict) and "jobs" in d:
        meta = get(f"https://boards-api.greenhouse.io/v1/boards/{s}")[1] or {}
        jobs = d["jobs"]
        return meta.get("name", ""), len(jobs), sum(london(j.get("location", {}).get("name")) for j in jobs)


def try_lever(s):
    st, d = get(f"https://api.lever.co/v0/postings/{s}?mode=json")
    if st == 200 and isinstance(d, list):
        return "", len(d), sum(london(j.get("categories", {}).get("location")) for j in d)
    st, d = get(f"https://api.eu.lever.co/v0/postings/{s}?mode=json")
    if st == 200 and isinstance(d, list):
        return "(eu)", len(d), sum(london(j.get("categories", {}).get("location")) for j in d)


def try_ashby(s):
    st, d = get(f"https://api.ashbyhq.com/posting-api/job-board/{s}")
    if st == 200 and isinstance(d, dict) and "jobs" in d:
        jobs = d["jobs"]
        return "", len(jobs), sum(london(j.get("location")) for j in jobs)


def try_smartrecruiters(s):
    st, d = get(f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100")
    if st == 200 and isinstance(d, dict) and d.get("totalFound", 0) > 0:
        jobs = d.get("content", [])
        name = (jobs[0].get("company", {}) or {}).get("name", "") if jobs else ""
        return name, d["totalFound"], sum(london((j.get("location") or {}).get("city")) for j in jobs)


def try_workable(s):
    st, d = get(f"https://apply.workable.com/api/v1/widget/accounts/{s}")
    if st == 200 and isinstance(d, dict) and d.get("jobs"):
        jobs = d["jobs"]
        return d.get("name", ""), len(jobs), sum(london(j.get("city")) for j in jobs)


def get_text(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return None, ""


def try_teamtailor(s):
    st, x = get_text(f"https://{s}.teamtailor.com/jobs.rss")
    if st == 200 and "<rss" in x:
        items = x.count("<item>")
        title = re.search(r"<title>([^<]*)", x)
        return title.group(1) if title else "", items, x.lower().count(CITY)


def try_recruitee(s):
    st, d = get(f"https://{s}.recruitee.com/api/offers/")
    if st == 200 and isinstance(d, dict) and d.get("offers"):
        o = d["offers"]
        return o[0].get("company_name", ""), len(o), sum(london(j.get("location")) for j in o)


def try_personio(s):
    for tld in ("de", "com"):
        st, x = get_text(f"https://{s}.jobs.personio.{tld}/xml")
        if st == 200 and "<position>" in x:
            return f"personio.{tld}", x.count("<position>"), x.lower().count(CITY)


def try_bamboohr(s):
    st, d = get(f"https://{s}.bamboohr.com/careers/list")
    if st == 200 and isinstance(d, dict) and d.get("result"):
        r = d["result"]
        return "", len(r), sum(london((j.get("location") or {}).get("city")) for j in r)


def try_pinpoint(s):
    st, d = get(f"https://{s}.pinpointhq.com/postings.json")
    if st == 200 and isinstance(d, dict) and d.get("data"):
        return "", len(d["data"]), sum(london(json.dumps(j.get("location"))) for j in d["data"])


PROBES = [("greenhouse", try_greenhouse), ("lever", try_lever), ("ashby", try_ashby),
          ("smartrecruiters", try_smartrecruiters), ("workable", try_workable),
          ("teamtailor", try_teamtailor), ("recruitee", try_recruitee), ("personio", try_personio),
          ("bamboohr", try_bamboohr), ("pinpoint", try_pinpoint)]


def detect(row):
    hits = []
    for s in slugs(row["name"]):
        for ats, fn in PROBES:
            r = fn(s)
            if r:
                hits.append({**row, "ats": ats, "slug": s, "board_name": r[0],
                             "jobs": r[1], "london_jobs": r[2]})
    return hits


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else U.CONFIG / "candidates.csv"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else U.CONFIG / "detected.csv"
    rows = list(csv.DictReader(src.open()))
    with ThreadPoolExecutor(16) as ex:
        results = [h for hits in ex.map(detect, rows) for h in hits]
    fields = ["name", "sector", "ats", "slug", "board_name", "jobs", "london_jobs"]
    with dst.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    found = {r["name"] for r in results}
    print(f"{len(found)}/{len(rows)} companies matched; {len(results)} board hits -> {dst}")
    print("No match:", ", ".join(r["name"] for r in rows if r["name"] not in found))


if __name__ == "__main__":
    main()
