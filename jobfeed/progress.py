"""Live progress of a search run, written to data/progress.json for the website's Live view.

feed.py, details.py and webapp/gmail.py call these as they work. Writes are throttled and never raise:
progress reporting must not be able to break a run.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import userdata as U  # noqa: E402  (where user data lives)
FILE = U.DATA / "progress.json"
STAGES = [("discover", "Finding new firms (weekly)"), ("boards", "Scanning job boards"), ("filter", "Location + role filters, last 14 days"), ("read", "Reading descriptions"),
          ("screen", "Screening: eligible + interest"), ("gmail", "Checking Gmail")]
_lock = threading.Lock()
_s = None
_last = 0.0


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _load():
    global _s
    if _s is None:
        try:
            _s = json.loads(FILE.read_text())
        except Exception:
            _s = None
    return _s


def _write(force=False):
    global _last
    if _s is None or (not force and time.time() - _last < 0.4):
        return
    _last = time.time()
    try:
        FILE.parent.mkdir(exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_s, ensure_ascii=False))
        os.replace(tmp, FILE)
    except Exception:
        pass


def start(kind, stages=None):
    """Begin a new run. kind: morning | feed | gmail. With JOBAGENT_RUN set (by morning.py), keeps the current run."""
    global _s
    with _lock:
        if os.environ.get("JOBAGENT_RUN"):
            _s = None                     # another process (feed.py) may have written since; re-read the file
            if _load() and _s.get("running"):
                return
        keep = stages or [k for k, _ in STAGES]
        _s = {"kind": kind, "running": True, "started": _now(), "finished": None, "ok": None, "summary": "",
              "current": "", "counts": {}, "events": [],
              "stages": [{"key": k, "label": label, "state": "pending", "detail": ""} for k, label in STAGES if k in keep]}
        _write(True)


def stage(key, state="active", detail=None):
    with _lock:
        if not _load():
            return
        for st in _s["stages"]:
            if st["key"] == key:
                st["state"] = state
                if detail is not None:
                    st["detail"] = detail
            elif state == "active" and st["state"] == "active":
                st["state"] = "done"
        _write(True)


def count(**kw):
    """Set counters, e.g. count(relevant=297)."""
    with _lock:
        if not _load():
            return
        _s["counts"].update(kw)
        _write()


def bump(key, n=1, current=None):
    with _lock:
        if not _load():
            return
        _s["counts"][key] = _s["counts"].get(key, 0) + n
        if current is not None:
            _s["current"] = current
        _write()


def event(kind, title, text="", company=""):
    """kind: pass | fail | info | mail. Keeps the latest 500."""
    with _lock:
        if not _load():
            return
        _s["events"].append({"t": _now(), "kind": kind, "company": company, "title": title, "text": text})
        _s["events"] = _s["events"][-500:]
        _write()


def finish(ok=True, summary="", final=True):
    """final=False: a step inside morning.py finished, but the run continues."""
    with _lock:
        if not _load():
            return
        if not final and os.environ.get("JOBAGENT_RUN"):
            _write(True)
            return
        for st in _s["stages"]:
            if st["state"] == "active":
                st["state"] = "done" if ok else "failed"
        _s.update(running=False, finished=_now(), ok=ok, summary=summary, current="")
        _write(True)
