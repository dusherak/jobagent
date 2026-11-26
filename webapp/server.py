"""Local job-agent website.

Usage: python3 webapp/server.py      then open http://127.0.0.1:8000
Serves only on this Mac (127.0.0.1). No internet exposure, no logins.
"""

import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import userdata as U  # noqa: E402
import docs  # noqa: E402
import tailor as tailor_mod  # noqa: E402
import gmail as gmail_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DATA_DIR = U.DATA
APPS = DATA_DIR / "applications.json"
JOBS = DATA_DIR / "jobs.json"
JOB_STATE = DATA_DIR / "job_state.json"           # dismissed job ids
GMAIL_OUT = DATA_DIR / "gmail_suggestions.json"
FILES = U.FILES
PACKS = U.PACKS
STAGES = ["Saved", "Applied", "Assessment", "Interview", "Offer", "Rejected"]
EDITABLE = {"stage", "status", "notes", "link", "role", "company", "applied", "deadline"}
LOCK = threading.RLock()


def read_json(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def write_json(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    tmp.replace(p)


def load_apps():
    return read_json(APPS, {"applications": [], "general_files": []})


def now():
    return datetime.now().isoformat(timespec="minutes")


def find_app(d, app_id):
    return next((a for a in d["applications"] if a["id"] == app_id), None)


def add_history(app, **entry):
    app.setdefault("history", []).append({"at": now(), **entry})


def attach(app, name, kind):
    app["files"] = [f for f in app.get("files", []) if f["name"] != name]
    label = re.sub(r"(?i)^" + re.escape(U.file_prefix()) + r" |\.(pdf|docx?)$|resume|cover letter", "", name).strip() or kind
    app["files"].append({"name": name, "kind": kind, "label": label})


# ---------- background tasks ----------

TASKS = {"feed": {"running": False}, "gmail": {"running": False}}


def run_task(name, fn, timeout=1500):
    """Run fn(log) in a thread; fn returns a short message."""
    t = TASKS.setdefault(name, {"running": False})
    if t["running"]:
        return False

    def log(msg):
        t["progress"] = msg

    def work():
        t.update(running=True, started=now(), finished=None, ok=None, message="", progress="")
        try:
            t["message"] = fn(log) or ""
            t["ok"] = True
        except Exception as e:
            t.update(ok=False, message=f"{e}"[:300] or type(e).__name__)
        finally:
            t.update(running=False, finished=now(), progress="")

    threading.Thread(target=work, daemon=True).start()
    return True


def feed_task(log):
    log("Reading ~160 job boards…")
    r = subprocess.run([sys.executable, str(ROOT / "jobfeed" / "feed.py")], cwd=ROOT, capture_output=True, text=True, timeout=1500)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
    return (r.stdout.strip().splitlines() or [""])[-1][:300]


def morning_task(log):              # the full run: jobs + screening + Gmail (same as the scheduled one)
    log("Searching…")
    r = subprocess.run([sys.executable, str(ROOT / "morning.py")], cwd=ROOT, capture_output=True, text=True, timeout=3600)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
    return " · ".join(r.stdout.strip().splitlines()[-2:])[:300]


def gmail_task(log):                # read-only Gmail check, see webapp/gmail.py
    return gmail_mod.check(log)


def tailor_task(app_id):
    def fn(log):
        with LOCK:
            app = dict(find_app(load_apps(), app_id))
        tailor_mod.tailor(app, app.get("link", ""), log)
        finish_pack(app_id)
        return "Documents ready"
    return fn


def rerender_task(app_id):
    def fn(log):
        with LOCK:
            app = dict(find_app(load_apps(), app_id))
        tailor_mod.render(app, PACKS / app_id, log)
        finish_pack(app_id)
        return "PDFs rebuilt"
    return fn


def finish_pack(app_id):
    with LOCK:
        d = load_apps()
        app = find_app(d, app_id)
        company = re.sub(r"[^\w &.-]", "", app["company"]).strip()
        names = tailor_mod.pdf_names(company)
        attach(app, names["cv"], "CV")
        attach(app, names["cl"], "Cover letter")
        app["tailored"] = True
        add_history(app, event="Tailored CV and cover letter generated")
        write_json(APPS, d)


def new_app(company, role="", link="", stage="Saved", status="", **extra):
    return {"id": "n" + hashlib.sha1(f"{company}{role}{time.time()}".encode()).hexdigest()[:10], "company": company.strip(),
            "role": role, "applied": extra.get("applied", ""), "deadline": extra.get("deadline", ""), "stage": stage if stage in STAGES else "Saved",
            "status": status, "referral": False, "link": link, "files": [], "notes": "",
            "history": [{"at": now(), "stage": stage, "status": status or "Created"}]}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/"):]).resolve()
            if f.parent != STATIC.resolve() or not f.is_file():
                return self._send(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain")
        if path == "/api/applications":
            return self._send(200, {**load_apps(), "stages": STAGES})
        if path == "/api/jobs":
            jobs = read_json(JOBS, {"jobs": [], "updated": None, "errors": []})
            dismissed = set(read_json(JOB_STATE, {"dismissed": []})["dismissed"])
            links = {a.get("link"): a["id"] for a in load_apps()["applications"] if a.get("link")}
            for j in jobs["jobs"]:
                j["dismissed"] = j["id"] in dismissed
                j["app_id"] = links.get(j["url"])
            return self._send(200, jobs)
        if path == "/api/settings":               # display name, city, PDF prefix for the UI
            return self._send(200, {"name": U.name(), "city": U.city(), "file_prefix": U.file_prefix(), "home": str(U.HOME)})
        if path == "/api/tasks":
            return self._send(200, TASKS)
        if path == "/api/progress":               # live view of the current / last search run
            return self._send(200, read_json(DATA_DIR / "progress.json", {}))
        if path == "/api/gmail":
            return self._send(200, read_json(GMAIL_OUT, {"updates": [], "new": [], "actions": [], "checked": None}))
        m = re.fullmatch(r"/api/tailor/([\w-]+)(?:/(cv|cl)\.html)?", path)
        if m:
            pack = PACKS / m.group(1)
            if not (pack / "cv.json").exists():
                return self._send(404, {"error": "no tailored documents yet"})
            cv = read_json(pack / "cv.json", {})
            cl = read_json(pack / "cl.json", {})
            if m.group(2) == "cv":
                return self._send(200, docs.cv_html(cv, read_json(pack / "meta.json", {}).get("render", {}).get("scale", 1), for_screen=True), "text/html; charset=utf-8")
            if m.group(2) == "cl":
                return self._send(200, docs.cl_html(cv, cl, for_screen=True), "text/html; charset=utf-8")
            return self._send(200, {"cv": cv, "cover_letter": cl, "meta": read_json(pack / "meta.json", {})})
        if path.startswith("/files/"):
            f = (FILES / path[len("/files/"):]).resolve()
            if f.parent != FILES.resolve() or not f.is_file():   # no path traversal outside applications/files
                return self._send(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/api/jobs/update":
            return self._send(200, {"started": run_task("feed", feed_task)})
        if path == "/api/search/run":
            if any(TASKS.get(k, {}).get("running") for k in ("feed", "gmail", "morning")):
                return self._send(200, {"started": False})
            return self._send(200, {"started": run_task("morning", morning_task, timeout=3600)})
        if path == "/api/gmail/check":
            return self._send(200, {"started": run_task("gmail", gmail_task)})
        if path == "/api/gmail/resolve":            # remove an item from the suggestions once handled
            b = self._body()
            with LOCK:
                g = read_json(GMAIL_OUT, {"updates": [], "new": [], "actions": []})
                lst = g.get(b["list"], [])
                if 0 <= b["index"] < len(lst):
                    lst.pop(b["index"])
                write_json(GMAIL_OUT, g)
            return self._send(200, g)

        m = re.fullmatch(r"/api/applications/([\w-]+)/upload", path)
        if m:
            name = re.sub(r"[^\w .()&-]", "", unquote(parse_qs(url.query).get("name", ["document.pdf"])[0]))[:120]
            if not re.search(r"\.(pdf|docx?)$", name, re.I):
                return self._send(400, {"error": "Only PDF or Word files"})
            size = int(self.headers.get("Content-Length", 0))
            if size > 15 * 1024 * 1024:
                return self._send(400, {"error": "File too large (15 MB max)"})
            data = self.rfile.read(size)
            with LOCK:
                d = load_apps()
                app = find_app(d, m.group(1))
                if not app:
                    return self._send(404, {"error": "unknown application"})
                target = FILES / name
                if target.exists():
                    target = FILES / f"{target.stem} ({int(time.time())}){target.suffix}"
                target.write_bytes(data)
                kind = "Cover letter" if re.search(r"(?i)cover|letter|\bcl\b", name) else "CV" if re.search(r"(?i)cv|resume|résumé", name) else "Document"
                attach(app, target.name, kind)
                add_history(app, event=f"Attached {target.name}")
                write_json(APPS, d)
            return self._send(200, app)

        with LOCK:
            if path == "/api/jobs/dismiss":
                b = self._body()
                st = read_json(JOB_STATE, {"dismissed": []})
                ids = set(st["dismissed"])
                ids.discard(b["id"]) if b.get("undo") else ids.add(b["id"])
                write_json(JOB_STATE, {"dismissed": sorted(ids)})
                return self._send(200, {"ok": True})
            if path == "/api/jobs/save":
                j = self._body()
                d = load_apps()
                app = next((a for a in d["applications"] if a.get("link") == j["url"]), None)
                if not app:
                    app = new_app(j["company"], j["title"], j["url"], "Saved",
                                  f"Saved from Jobs · posted {j.get('date') or '?'}", deadline=j.get("deadline", ""))
                    d["applications"].append(app)
                    write_json(APPS, d)
                if j.get("tailor"):
                    run_task(f"tailor:{app['id']}", tailor_task(app["id"]), timeout=900)
                return self._send(200, app)
            if path == "/api/applications/new":
                b = self._body()
                if not b.get("company", "").strip():
                    return self._send(400, {"error": "Company is required"})
                d = load_apps()
                app = new_app(**{k: b.get(k, "") for k in ("company", "role", "link", "stage", "status", "applied", "deadline")})
                d["applications"].append(app)
                write_json(APPS, d)
                return self._send(200, app)
            m = re.fullmatch(r"/api/tailor/([\w-]+)(/save)?", path)
            if m:
                app_id = m.group(1)
                if not find_app(load_apps(), app_id):
                    return self._send(404, {"error": "unknown application"})
                if m.group(2):                       # save edits, then rebuild PDFs
                    b = self._body()
                    pack = PACKS / app_id
                    if "cv" in b:
                        write_json(pack / "cv.json", b["cv"])
                    if "cover_letter" in b:
                        write_json(pack / "cl.json", b["cover_letter"])
                    return self._send(200, {"started": run_task(f"tailor:{app_id}", rerender_task(app_id), timeout=300)})
                return self._send(200, {"started": run_task(f"tailor:{app_id}", tailor_task(app_id), timeout=900)})
            m = re.fullmatch(r"/api/applications/([\w-]+)(/delete)?", path)
            if m:
                d = load_apps()
                app = find_app(d, m.group(1))
                if not app:
                    return self._send(404, {"error": "unknown application"})
                if m.group(2):
                    d["applications"].remove(app)
                    write_json(APPS, d)
                    return self._send(200, {"deleted": app["id"]})
                b = self._body()
                old_stage, old_status = app.get("stage"), app.get("status")
                for k, v in b.items():
                    if k in EDITABLE and isinstance(v, str) and (k != "stage" or v in STAGES):
                        app[k] = v
                if app.get("stage") != old_stage or app.get("status") != old_status:
                    if app.get("stage") == "Applied" and old_stage == "Saved" and not app.get("applied"):
                        app["applied"] = date.today().isoformat()
                    add_history(app, stage=app["stage"], status=app.get("status", ""), source=b.get("_source", "manual"))
                write_json(APPS, d)
                return self._send(200, app)
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Job agent running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
