"""Daily job feed (default preset: graduate finance roles in London).

Usage:
    python3 jobfeed/feed.py            # fetch, filter, write digest of NEW jobs
    python3 jobfeed/feed.py --all      # digest of every currently open match (ignores seen state)

Reads only public job-board endpoints (Greenhouse, Lever, Ashby, SmartRecruiters, Teamtailor, Pinpoint,
Workable, Workday, Oracle, Eightfold) plus the Reed / Adzuna APIs if free keys are
in <user folder>/keys.env. Never logs in anywhere and never applies to anything.

Outputs:
    (all under the user folder, see userdata.py)
    digests/YYYY-MM-DD.md       ranked list of new matches
    applications.csv            new entry-level matches appended with status "found"
    state/seen.json             ids already reported
"""

import base64
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import progress

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import userdata as U  # noqa: E402  (where user data lives)

HERE = Path(__file__).parent
STATE = U.STATE / "seen.json"
CITY = U.city()
LOCATION_FULL = U.settings().get("location_full") or f"{CITY}, United Kingdom"
UA = "Mozilla/5.0 (Macintosh) personal-job-search/0.1 (individual use)"
TODAY = date.today()


# ---------- http ----------

def http(url, data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def job(company, title, location, url, posted=None, source=""):
    return {"company": company or "", "title": (title or "").strip(), "location": (location or "").strip(),
            "url": url, "posted": posted or "", "deadline": "", "source": source}


def iso(ts):
    """Normalise ms/s epoch or ISO-ish strings to YYYY-MM-DD."""
    if ts in (None, ""):
        return ""
    if isinstance(ts, (int, float)):
        ts = ts / 1000 if ts > 1e11 else ts
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(ts))
    if m:
        return m.group(1)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(ts))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


# ---------- sources ----------

def greenhouse(company, slug):
    d = http(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return [job(company, j["title"], (j.get("location") or {}).get("name"), j["absolute_url"],
                iso(j.get("first_published") or j.get("updated_at")), "greenhouse") for j in d["jobs"]]


def lever(company, slug):
    try:
        d = http(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    except Exception:
        d = http(f"https://api.eu.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in d:
        c = j.get("categories", {})
        locs = ", ".join(c.get("allLocations") or [c.get("location") or ""])
        out.append(job(company, j["text"], locs, j["hostedUrl"], iso(j.get("createdAt")), "lever"))
    return out


def ashby(company, slug):
    d = http(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in d["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        out.append(job(company, j["title"], ", ".join(filter(None, locs)), j["jobUrl"], iso(j.get("publishedAt")), "ashby"))
    return out


def smartrecruiters(company, slug):
    out, offset = [], 0
    while offset < 1000:
        d = http(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}&country=gb")
        for j in d.get("content", []):
            loc = j.get("location") or {}
            out.append(job(company, j["name"], f"{loc.get('city', '')}, {loc.get('country', '')}",
                           f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", iso(j.get("releasedDate")), "smartrecruiters"))
        offset += 100
        if offset >= d.get("totalFound", 0):
            break
    return out


def workable(company, slug):
    d = http(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    return [job(company, j["title"], f"{j.get('city', '')}, {j.get('country', '')}", j.get("url") or j.get("shortlink"),
                iso(j.get("published_on")), "workable") for j in d.get("jobs", [])]


def _workday_posted(text):
    t = (text or "").lower()
    if "today" in t:
        return TODAY.isoformat()
    if "yesterday" in t:
        return (TODAY - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+? days", t)
    return (TODAY - timedelta(days=int(m.group(1)))).isoformat() if m else ""


def workday(company, url, max_pages=10):
    u = urllib.parse.urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    if "myworkdaysite.com" in u.netloc:          # wd1.myworkdaysite.com/recruiting/<tenant>/<site>
        tenant, site = parts[1], parts[2]
    else:                                         # <tenant>.wdN.myworkdayjobs.com/<site>
        tenant, site = u.netloc.split(".")[0], parts[-1]
    api = f"https://{u.netloc}/wday/cxs/{tenant}/{site}/jobs"
    out = []
    for page in range(max_pages):
        d = http(api, {"limit": 20, "offset": page * 20, "searchText": CITY, "appliedFacets": {}})
        posts = d.get("jobPostings", [])
        for j in posts:
            out.append(job(company, j.get("title"), j.get("locationsText"),
                           f"https://{u.netloc}/{'/'.join(parts)}{j.get('externalPath', '')}",
                           _workday_posted(j.get("postedOn")), "workday"))
        if len(posts) < 20 or (page + 1) * 20 >= d.get("total", 0):
            break
        time.sleep(0.3)
    return out


def oracle(company, spec, pages=8):
    host, site = spec.split("|")
    out = []
    for page in range(pages):
        finder = f"findReqs;siteNumber={site},keyword={urllib.parse.quote(CITY)},limit=25,offset={page * 25},sortBy=POSTING_DATES_DESC"
        d = http(f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                 f"&expand=requisitionList.secondaryLocations&finder={urllib.parse.quote(finder, safe=';=,')}")
        items = d["items"][0]["requisitionList"] if d.get("items") else []
        for r in items:
            locs = [r.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
            out.append(job(company, r.get("Title"), ", ".join(locs),
                           f"{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r.get('Id')}",
                           iso(r.get("PostedDate")), "oracle"))
        if len(items) < 25:
            break
    return out


def eightfold(company, spec):
    host, domain = spec.split("|")
    out = []
    try:
        for start in range(0, 200, 10):
            d = http(f"{host}/api/pcsx/search?domain={domain}&query=&location={urllib.parse.quote(CITY)}&start={start}&sort_by=timestamp")
            pos = (d.get("data") or {}).get("positions", [])
            for p in pos:
                out.append(job(company, p.get("name"), "; ".join(p.get("locations") or []),
                               f"{host}/careers/job/{p.get('id')}", iso(p.get("postedTs")), "eightfold"))
            if len(pos) < 10:
                break
        return out
    except Exception:
        pass
    for start in range(0, 200, 10):
        d = http(f"{host}/api/apply/v2/jobs?domain={domain}&location={urllib.parse.quote(CITY)}&start={start}&num=10&sort_by=timestamp")
        pos = d.get("positions", [])
        for p in pos:
            out.append(job(company, p.get("name"), p.get("location"),
                           p.get("canonicalPositionUrl") or f"{host}/careers/job/{p.get('id')}",
                           iso(p.get("t_create")), "eightfold"))
        if len(pos) < 10:
            break
    return out


def http_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def teamtailor(company, slug):
    x = http_text(f"https://{slug}.teamtailor.com/jobs.rss")
    out = []
    for it in x.split("<item>")[1:]:
        g = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S) or [None, ""])[1].strip()
        locs = ", ".join(re.findall(r"<tt:city>(.*?)</tt:city>", it)) or g("tt:name")
        posted = ""
        if g("pubDate"):
            try:
                posted = datetime.strptime(g("pubDate")[:16], "%a, %d %b %Y").date().isoformat()
            except ValueError:
                pass
        out.append(job(company, g("title"), locs, g("link"), posted, "teamtailor"))
    return out


def pinpoint(company, slug):
    d = http(f"https://{slug}.pinpointhq.com/postings.json")
    out = []
    for p in d.get("data", []):
        loc = p.get("location") or {}
        j = job(company, p.get("title"), f"{loc.get('city', '')}, {loc.get('name', '')}", p.get("url"), "", "pinpoint")
        j["deadline"] = iso(p.get("deadline_at"))
        out.append(j)
    return out


def workable_search(filters, max_pages=4):
    """Workable's public cross-company job search: finds employers we don't track yet."""
    out = []
    for kw in filters.get("search_keywords", []):
        token = None
        for _ in range(max_pages):
            q = {"query": kw, "location": LOCATION_FULL}
            if token:
                q["pageToken"] = token
            d = http(f"https://jobs.workable.com/api/v1/jobs?{urllib.parse.urlencode(q)}")
            for j in d.get("jobs", []):
                out.append(job((j.get("company") or {}).get("title"), j.get("title"), "; ".join(j.get("locations") or []),
                               j.get("url"), iso(j.get("created")), "workable-search"))
            token = d.get("nextPageToken")
            if not token:
                break
            time.sleep(0.3)
    return out


TJ_CACHE = U.STATE / "targetjobs_cache.json"


def targetjobs(filters, max_fetch=500, lookback_days=21):
    """TargetJobs (UK graduate jobs board). Uses its public sitemap, then reads the
    JobPosting structured data on each candidate page. Pages are cached between runs."""
    xml = http_text("https://targetjobs.co.uk/sitemap-0.xml", timeout=120)
    cutoff = (TODAY - timedelta(days=lookback_days)).isoformat()
    cache = json.loads(TJ_CACHE.read_text()) if TJ_CACHE.exists() else {}
    todo = []
    for url, lastmod in re.findall(r"<loc>(https://targetjobs\.co\.uk/jobs/[^<]+)</loc><lastmod>([^<]+)", xml):
        slug_words = url.rsplit("/", 1)[-1].replace("-", " ")
        if url in cache or lastmod[:10] < cutoff:
            continue
        if has(slug_words, filters["role_keywords"]) and not has(slug_words, filters["exclude_keywords"]):
            todo.append(url)
    todo.sort(key=lambda u: -int(re.search(r"-(\d+)$", u).group(1)) if re.search(r"-(\d+)$", u) else 0)

    def parse(url):
        try:
            return _parse(url)
        except Exception:
            return url, None

    def _parse(url):
        h = http_text(url)
        for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', h, re.S):
            try:
                d = json.loads(m.group(1))
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                locs = d.get("jobLocation") or []
                locs = locs if isinstance(locs, list) else [locs]
                places = []
                for l in locs:
                    a = l.get("address") if isinstance(l, dict) else None
                    a = a[0] if isinstance(a, list) and a else a
                    if isinstance(a, dict):
                        places.append(", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion")])))
                    elif isinstance(a, str):
                        places.append(a)
                org = d.get("hiringOrganization") or {}
                org = org[0] if isinstance(org, list) and org else org
                return url, {"company": org.get("name", "") if isinstance(org, dict) else str(org), "title": d.get("title", ""),
                             "location": "; ".join(filter(None, places)), "posted": iso(d.get("datePosted")),
                             "deadline": iso(d.get("validThrough")), "cached": TODAY.isoformat()}
        return url, {"company": "", "title": "", "location": "", "posted": "", "deadline": "", "cached": TODAY.isoformat()}

    with ThreadPoolExecutor(4) as ex:
        for url, rec in ex.map(parse, todo[:max_fetch]):
            if rec:
                cache[url] = rec
    keep_after = (TODAY - timedelta(days=90)).isoformat()
    cache = {u: r for u, r in cache.items() if r.get("cached", "") >= keep_after}
    TJ_CACHE.parent.mkdir(exist_ok=True)
    TJ_CACHE.write_text(json.dumps(cache))
    out = []
    for url, r in cache.items():
        if r["title"] and (not r["deadline"] or r["deadline"] >= TODAY.isoformat()):
            j = job(r["company"], r["title"], r["location"], url, r["posted"], "targetjobs")
            j["deadline"] = r["deadline"]
            out.append(j)
    return out


def mckinsey(company, city):
    d = http(f"https://gateway.mckinsey.com/apigw-x0cceuow60/v1/api/jobs/search?pageSize=100&start=1&lang=en&cities={urllib.parse.quote(city)}")
    return [job(company, j.get("title"), city if city in (j.get("cities") or []) else ", ".join((j.get("cities") or [])[:3]),
                f"https://www.mckinsey.com/careers/search-jobs/jobs/{j.get('friendlyURL', '')}", "", "mckinsey")
            for j in d.get("docs", [])]


def rendered():
    """Pages that need a browser: runs jobfeed/rendered.py in the isolated venv (Playwright + Scrapling parser)."""
    import subprocess
    py = HERE / ".venv" / "bin" / "python"
    if not py.exists():
        return [], ["rendered pages: jobfeed/.venv missing, skipped"]
    r = subprocess.run([str(py), str(HERE / "rendered.py")], capture_output=True, text=True, timeout=600)
    d = json.loads(r.stdout or '{"jobs": [], "errors": ["rendered.py produced no output"]}')
    out = []
    for j in d["jobs"]:
        if "title" in j:                      # card parsers (job boards) give structured fields
            r = job(j["company"], j["title"], j.get("location", ""), j["url"], j.get("posted", ""), "board:" + j["board"])
            r["deadline"] = j.get("deadline", "")
            out.append(r)
            continue
        text = j["text"]
        # link text runs title + location/department together; cut the title at the first marker
        cut = re.search(r"\s+(London\s*·|Management Consulting|Technology & Engineering|Permanent|Contract|Temporary|Internship\s+Full)", text)
        title = text[:cut.start()] if cut else text
        out.append(job(j["company"], title.strip(" -"), text, j["url"], "", "rendered"))
    return out, d["errors"]


SPONSORS = U.STATE / "sponsors.csv"
_SPONSOR_NAMES = None
_SUFFIX = re.compile(r"\b(limited|ltd|llp|plc|lp|inc|llc|group|holdings|uk|international|europe|services|the|and|&|co|company|london|branch|bank)\b")


def _norm(name):
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", re.sub(r"[^a-z0-9& ]", " ", (name or "").lower()))).strip()


def refresh_sponsors(max_age_days=7):
    """Download the Home Office register of licensed visa sponsors (public CSV) about once a week."""
    if SPONSORS.exists() and (time.time() - SPONSORS.stat().st_mtime) < max_age_days * 86400:
        return
    page = http_text("https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers")
    m = re.search(r"https://assets\.publishing\.service\.gov\.uk/[^\"]+\.csv", page)
    if m:
        SPONSORS.parent.mkdir(exist_ok=True)
        SPONSORS.write_text(http_text(m.group(0), timeout=180))


def sponsor_status(company):
    """'yes' if a matching organisation holds a Skilled Worker licence, '?' if no match found."""
    global _SPONSOR_NAMES
    if _SPONSOR_NAMES is None:
        _SPONSOR_NAMES = set()
        if SPONSORS.exists():
            for row in csv.reader(SPONSORS.open(encoding="utf-8", errors="replace")):
                if row and len(row) >= 5 and "Skilled Worker" in row[4]:
                    _SPONSOR_NAMES.add(_norm(row[0]))
    n = _norm(company)
    if not n or not _SPONSOR_NAMES:
        return "?"
    if n in _SPONSOR_NAMES:
        return "yes"
    first = n.split()[0]
    return "likely" if len(first) > 3 and any(s.startswith(n) or s.split()[:1] == [first] and len(n.split()) == 1 for s in _SPONSOR_NAMES) else "?"


def load_keys():
    keys, f = {}, U.KEYS
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def reed(keys, filters):
    if not keys.get("REED_API_KEY"):
        return []
    auth = base64.b64encode(f"{keys['REED_API_KEY']}:".encode()).decode()
    out = []
    for kw in filters["reed_keywords"]:
        q = urllib.parse.urlencode({"keywords": kw, "locationName": CITY, "distanceFromLocation": 15, "resultsToTake": 100})
        d = http(f"https://www.reed.co.uk/api/1.0/search?{q}", headers={"Authorization": f"Basic {auth}"})
        for j in d.get("results", []):
            out.append(job(j.get("employerName"), j.get("jobTitle"), j.get("locationName"), j.get("jobUrl"),
                           iso(j.get("date")), "reed"))
        time.sleep(0.5)
    return out


def adzuna(keys, filters):
    if not (keys.get("ADZUNA_APP_ID") and keys.get("ADZUNA_APP_KEY")):
        return []
    out = []
    for kw in filters["adzuna_keywords"]:
        q = urllib.parse.urlencode({"app_id": keys["ADZUNA_APP_ID"], "app_key": keys["ADZUNA_APP_KEY"], "what": kw,
                                    "where": CITY, "max_days_old": 7, "results_per_page": 50, "sort_by": "date"})
        d = http(f"https://api.adzuna.com/v1/api/jobs/gb/search/1?{q}")
        for j in d.get("results", []):
            out.append(job((j.get("company") or {}).get("display_name"), j.get("title"),
                           (j.get("location") or {}).get("display_name"), j.get("redirect_url"),
                           iso(j.get("created")), "adzuna"))
        time.sleep(0.5)
    return out


ADAPTERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "workable": workable, "workday": workday, "oracle": oracle, "eightfold": eightfold,
            "teamtailor": teamtailor, "pinpoint": pinpoint, "mckinsey": mckinsey}


# ---------- filtering ----------

_PATTERNS = {}


def has(text, words):
    """Whole-word match; a trailing * allows any suffix (financ* -> finance, financial)."""
    key = tuple(words)
    if key not in _PATTERNS:
        alts = [re.escape(w.lower().rstrip("*")) + (r"\w*" if w.endswith("*") else "") for w in words]
        _PATTERNS[key] = re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?![\w])")
    return bool(_PATTERNS[key].search(text.lower()))


AGGREGATORS = {"targetjobs", "workable-search", "reed", "adzuna", "board:eFinancialCareers", "board:Gradcracker"}


def is_dream(company, f):
    c = base_company(company)
    return any(d in c for d in f.get("dream_firms", []))


def classify(j, f, tracked=frozenset()):
    loc, t = j["location"], j["title"]
    in_london = has(loc, f["locations"]) or bool(re.search(r"\d+ locations", loc.lower()))
    if not in_london:
        # elsewhere in the UK only for top roles or dream firms
        if not (has(loc, f["uk_locations"]) and (has(t, f["top_role_keywords"]) or is_dream(j["company"], f))):
            return None
        if has(t, f.get("non_london_excludes", [])):
            return None
    j["ai"] = has(t, f.get("ai_keywords", []))
    if j["ai"]:
        if has(t, f["seniority_excludes"]) or has(t, f.get("ai_excludes", [])):
            return None
    else:
        if not has(t, f["role_keywords"]) or has(t, f["exclude_keywords"]):
            return None
        if j["source"] in AGGREGATORS and base_company(j["company"]) not in tracked and not has(t, f["finance_keywords"]):
            return None
    if has(t, f["intern_keywords"]):
        return "intern"
    return "grad" if has(t, f["grad_keywords"]) else "other"


def job_id(j):
    return j["url"] or f"{j['company']}|{j['title']}|{j['location']}"


def base_company(name):
    return re.sub(r"\s*\(.*\)$", "", name or "").lower()


# ---------- main ----------

def fetch_all(sources):
    tasks = [(ats, name, arg) for ats, d in sources.items() if ats in ADAPTERS for name, arg in d.items()]
    jobs, errors = [], []

    def run(t):
        ats, name, arg = t
        try:
            return ADAPTERS[ats](name, arg), None
        except Exception as e:
            return [], f"{name} ({ats}): {type(e).__name__} {getattr(e, 'code', '')}".strip()

    progress.count(boards_total=len(tasks) + 5, boards_done=0, postings=0)
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(run, t): t for t in tasks}
        for f in as_completed(futs):
            res, err = f.result()
            jobs += res
            progress.bump("postings", len(res))
            progress.bump("boards_done", current=futs[f][1])
            if err:
                errors.append(err)
    return jobs, errors


def main():
    show_all = "--all" in sys.argv
    sources = json.loads(U.config("sources.json").read_text())
    filters = json.loads(U.config("filters.json").read_text())
    max_age = int(filters.get("max_age_days", 14))
    keys = load_keys()
    try:
        refresh_sponsors()
    except Exception as e:
        print(f"sponsor register refresh failed: {type(e).__name__}")

    progress.start("feed", ["boards", "filter", "read", "screen"])
    progress.stage("boards")
    jobs, errors = fetch_all(sources)
    for name, fn in (("Reed", lambda: reed(keys, filters)), ("Adzuna", lambda: adzuna(keys, filters)),
                     ("Workable search", lambda: workable_search(filters)), ("TargetJobs", lambda: targetjobs(filters))):
        progress.bump("boards_done", 0, current=name)
        try:
            got = fn()
            jobs += got
            progress.bump("postings", len(got))
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__} {getattr(e, 'code', '')}".strip())
        progress.bump("boards_done")
    progress.bump("boards_done", 0, current="Goldman, Bain, eFinancialCareers, Gradcracker (browser)")
    try:
        rj, rerr = rendered()
        jobs += rj
        errors += rerr
    except Exception as e:
        errors.append(f"rendered pages: {type(e).__name__}")
    progress.bump("boards_done")
    progress.count(postings=len(jobs))
    progress.stage("boards", "done", f"{len(jobs):,} postings")
    progress.stage("filter")

    # state: job id -> date first seen (older versions stored a plain list)
    raw = json.loads(STATE.read_text()) if STATE.exists() else {}
    seen = raw if isinstance(raw, dict) else {k: "2026-10-14" for k in raw}
    source_start = seen.pop("_source_first_scan", {})        # when each source was first scanned
    for j in jobs:
        source_start.setdefault(j["source"], TODAY.isoformat())
    cutoff = (TODAY - timedelta(days=max_age)).isoformat()

    # merge the same job listed on several sites: newest date, all locations, prefer the employer's own link
    merged = {}
    for j in jobs:
        key = (base_company(j["company"]), re.sub(r"\W+", " ", j["title"].lower()).strip())
        m = merged.get(key)
        if not m:
            merged[key] = dict(j)
            continue
        if j["location"] and j["location"].lower() not in m["location"].lower():
            m["location"] = f"{m['location']}; {j['location']}".strip("; ")
        m["posted"] = max(m["posted"], j["posted"])
        m["deadline"] = m["deadline"] or j["deadline"]
        if m["source"] in AGGREGATORS and j["source"] not in AGGREGATORS:
            m["url"], m["source"] = j["url"], j["source"]
    tracked = frozenset(base_company(n) for d in sources.values() for n in d)

    matches = []
    for j in merged.values():
        tier = classify(j, filters, tracked)
        if not tier:
            continue
        jid = job_id(j)
        j["tier"] = tier
        j["new"] = jid not in seen
        j["first_seen"] = seen.get(jid, TODAY.isoformat())
        j["date"] = j["posted"] or j["first_seen"]          # best estimate of when it went live
        # undated and already there on the first scan of its site: we can't tell how old it is
        j["undated_baseline"] = not j["posted"] and j["first_seen"] <= source_start.get(j["source"], TODAY.isoformat())
        matches.append(j)

    # remember which employers post relevant roles on the broad boards, for discover.py to find their own job boards
    agg_file = U.STATE / "aggregator_companies.json"
    agg = json.loads(agg_file.read_text()) if agg_file.exists() else {}
    for m in matches:
        if m["source"] in AGGREGATORS and m["company"]:
            e = agg.setdefault(m["company"], {"count": 0})
            e["count"] += 1
            e["last_seen"] = TODAY.isoformat()
    agg_file.parent.mkdir(exist_ok=True)
    agg_file.write_text(json.dumps(agg, indent=1, ensure_ascii=False))

    recent = [m for m in matches if m["date"] >= cutoff and not m["undated_baseline"]]
    undated = [m for m in matches if m["undated_baseline"] and m["tier"] in ("grad", "intern") and (show_all or m["new"])]
    report = recent if show_all else [m for m in recent if m["new"]]
    progress.count(relevant=len(matches), recent=len(recent), new=len([m for m in recent if m["new"]]))
    progress.stage("filter", "done", f"{len(recent)} roles, {len([m for m in recent if m['new']])} new")
    order = {"grad": 0, "intern": 1, "other": 2}
    for m in report:
        m["dream"] = is_dream(m["company"], filters)
        m["visa"] = sponsor_status(m["company"])
    report.sort(key=lambda m: (order[m["tier"]], not m["dream"], -int(m["date"].replace("-", "")), m["company"]))

    # data file for the local website: every recent match (not just new ones)
    import hashlib
    site = []
    for m in sorted(recent + [u for u in matches if u["undated_baseline"] and u["tier"] in ("grad", "intern")],
                    key=lambda m: (order[m["tier"]], not is_dream(m["company"], filters), -int(m["date"].replace("-", "")))):
        site.append({"id": hashlib.sha1(job_id(m).encode()).hexdigest()[:12], "company": m["company"], "title": m["title"],
                     "location": m["location"], "url": m["url"], "posted": m["posted"], "date": m["date"],
                     "deadline": m["deadline"], "tier": m["tier"], "ai": bool(m.get("ai")), "dream": is_dream(m["company"], filters),
                     "visa": sponsor_status(m["company"]), "new": m["new"], "undated": m["undated_baseline"], "source": m["source"]})
    # read every posting's full description: hard eligibility rules + short AI summary (cached per job)
    if "--no-details" not in sys.argv:
        try:
            import details
            details.enrich(site, use_ai="--no-ai" not in sys.argv)
        except Exception as e:
            errors.append(f"job details: {type(e).__name__} {e}"[:200])
    # carry the verdicts over to the digest rows
    verdict = {r["id"]: r for r in site}
    for m in report + undated:
        r = verdict.get(hashlib.sha1(job_id(m).encode()).hexdigest()[:12], {})
        m["fit"], m["reason"], m["summary"] = r.get("fit", "check"), r.get("reason", ""), r.get("summary", "")
        if r.get("want") == "no" and m["fit"] != "not_eligible":      # eligible, but not a job the user would want
            m["fit"], m["reason"] = "not_wanted", "Not your kind of role: " + r.get("want_reason", "")
    not_fit = [m for m in report if m["fit"] in ("not_eligible", "not_wanted")]
    report = [m for m in report if m["fit"] not in ("not_eligible", "not_wanted")]

    # digest
    U.DIGESTS.mkdir(parents=True, exist_ok=True)
    out = U.DIGESTS / f"{TODAY.isoformat()}{'-all-recent' if show_all else ''}.md"
    boards = sum(len(v) for v in sources.values())
    extra = ["TargetJobs", "Workable search"] + (["Reed"] if keys.get("REED_API_KEY") else []) + (["Adzuna"] if keys.get("ADZUNA_APP_ID") else [])
    lines = [f"# Job digest {TODAY.isoformat()}", "",
             f"Scanned {len(jobs)} postings from {boards} employer boards + {', '.join(extra)}. "
             f"Showing roles posted in the last {max_age} days{'' if show_all else ' that are new since the last run'}: {len(report)}.",
             "Date = posting date from the site, or the date the feed first saw it when the site gives none (marked *). "
             "★ = dream firm. AI = AI-related role. Visa: yes = employer name matches a UK Skilled Worker sponsor licence (Home Office register); likely = similar name matched; ? = no match (check).", ""]
    for tier, heading in (("grad", "Graduate / full-time analyst / entry-level"),
                          ("intern", "Internships (check eligibility: summer programmes usually want penultimate-year students)"),
                          ("other", "Other relevant (check level)")):
        rows = [m for m in report if m["tier"] == tier]
        lines += [f"## {heading} ({len(rows)})", "", "| Posted | Deadline | Company | Role | Location | Visa |", "|---|---|---|---|---|---|"]
        lines += [f"| {m['date']}{'' if m['posted'] else '*'} | {m['deadline'] or ''} | {'★ ' if m['dream'] else ''}{m['company'].replace('|', '/')} | "
                  f"{'**AI** ' if m.get('ai') else ''}[{m['title'].replace('|', '/')}]({m['url']}){' ⚠ ' + m['reason'] if m.get('fit') == 'check' and m.get('reason') else ''} | {m['location'][:40].replace('|', '/')} | {m['visa']} |" for m in rows]
        lines.append("")
    if not_fit:
        lines += [f"## Not a fit, from the full description ({len(not_fit)})", "",
                  "Hidden from the lists above: the posting rules you out (no sponsorship / Master's / experience / level) or it isn't a role you want.", ""]
        lines += [f"- {m['company']}: [{m['title'].replace('|', '/')}]({m['url']}) — {m['reason']}" for m in not_fit]
        lines.append("")
    if undated:
        lines += [f"## Open on sites with no posting dates, age unknown ({len(undated)})", "",
                  "These sites (e.g. Goldman, McKinsey, Bain) don't publish dates; these were already open when the feed started reading them. Future new ones will appear above.", ""]
        lines += [f"- {m['company']}: [{m['title'].replace('|', '/')}]({m['url']})" for m in undated]
        lines.append("")
    manual = U.config("manual.csv")
    if manual.exists():
        lines += ["## Check by hand (sites that block automated reading)", ""]
        lines += [f"- [{r['name']}]({r['url']}) — {r['note']}" for r in csv.DictReader(manual.open())]
        lines.append("")
    if errors:
        lines += ["## Sources that failed this run", ""] + [f"- {e}" for e in errors] + [""]
    out.write_text("\n".join(lines))

    # applications.csv: append new graduate / entry-level matches
    apps = U.TRACKER_CSV
    existing = {r["link"] for r in csv.DictReader(apps.open())} if apps.exists() else set()
    new_file = not apps.exists()
    with apps.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["company", "role", "link", "date_found", "status", "notes"])
        for m in report:
            if m["tier"] == "grad" and m["url"] not in existing:
                w.writerow([m["company"], m["title"], m["url"], TODAY.isoformat(), "found",
                            f"posted {m['date']}; deadline {m['deadline'] or '?'}; visa sponsor {sponsor_status(m['company'])}; {m['location'][:60]}"])

    U.DATA.mkdir(parents=True, exist_ok=True)
    (U.DATA / "jobs.json").write_text(json.dumps({"updated": datetime.now().isoformat(timespec="minutes"),
                                                         "max_age_days": max_age, "errors": errors, "jobs": site}, indent=1))

    for m in matches:
        seen.setdefault(job_id(m), m["first_seen"])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({**seen, "_source_first_scan": source_start}))
    print(f"{len(jobs)} postings scanned, {len(matches)} relevant, {len(recent)} posted in last {max_age} days, "
          f"{len(report)} in digest -> {out}")
    passed = sum(1 for r in site if r.get("fit") != "not_eligible" and r.get("want") != "no")
    progress.count(passed=passed)
    progress.finish(True, f"{len(jobs):,} postings scanned · {len(recent)} recent {CITY} roles · {passed} pass your filters", final=False)
    if errors:
        print(f"{len(errors)} source errors (listed in digest)")


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        progress.finish(False, f"Job search failed: {type(e).__name__}")
        raise
