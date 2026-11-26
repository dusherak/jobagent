"""Where everything lives.

The code (this folder) holds no personal data. Everything about the user — profile, CV, letters,
tracker, keys, cached job data — lives in the user folder:

    $JOBAGENT_HOME, or ~/.jobagent if that isn't set

Editable config (sources.json, filters.json, models.json, firm lists) ships with defaults in
`defaults/`. The first time a file is needed it is copied into <user folder>/config/, and from then
on the user's copy is the one that is read and written.
"""

import json
import os
import shutil
from pathlib import Path

CODE = Path(__file__).resolve().parent
DEFAULTS = CODE / "defaults"
TEMPLATES = CODE / "templates"

HOME = Path(os.environ.get("JOBAGENT_HOME") or Path.home() / ".jobagent").expanduser()
CONFIG = HOME / "config"
DATA = HOME / "data"            # tracker (applications.json), jobs.json, progress, Gmail suggestions
STATE = HOME / "state"          # caches: seen jobs, sponsor register, job details, discovery
DIGESTS = HOME / "digests"
CV_DIR = HOME / "cv"            # master.json, own_letters.md, tailoring_prompt.md, examples/
FILES = HOME / "applications" / "files"
PACKS = HOME / "applications" / "tailored"
PROFILE = HOME / "profile.md"
SETTINGS = HOME / "settings.json"
TRACKER_CSV = HOME / "applications.csv"
KEYS = HOME / "keys.env"

# files copied from templates/ on `init` (never overwritten)
TEMPLATE_FILES = {
    "profile.md": PROFILE,
    "settings.json": SETTINGS,
    "cv/master.json": CV_DIR / "master.json",
    "cv/own_letters.md": CV_DIR / "own_letters.md",
    "cv/tailoring_prompt.md": CV_DIR / "tailoring_prompt.md",
}


def config(name):
    """Path of an editable config file (sources.json, filters.json, models.json, manual.csv ...).
    Copies the shipped default into the user folder the first time."""
    p = CONFIG / name
    if not p.exists() and (DEFAULTS / name).exists():
        CONFIG.mkdir(parents=True, exist_ok=True)
        shutil.copy(DEFAULTS / name, p)
    return p


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def settings():
    """settings.json merged over the template's defaults."""
    base = read_json(TEMPLATES / "settings.json", {}) or {}
    return {**base, **(read_json(SETTINGS, {}) or {})}


def name():
    return settings().get("name") or "there"


def file_prefix():
    """Start of generated PDF names, e.g. "SMITH Jane"."""
    s = settings()
    return s.get("file_prefix") or s.get("name") or "My"


def city():
    return settings().get("city") or "London"


def model(job, fallback="sonnet"):
    return (read_json(config("models.json"), {}) or {}).get(job, fallback)


def profile():
    return PROFILE.read_text() if PROFILE.exists() else ""


def init(verbose=True):
    """Create the user folder and copy templates + default config into it. Never overwrites."""
    for d in (CONFIG, DATA, STATE, DIGESTS, CV_DIR, FILES, PACKS):
        d.mkdir(parents=True, exist_ok=True)
    made = []
    for src, dst in TEMPLATE_FILES.items():
        if not dst.exists():
            shutil.copy(TEMPLATES / src, dst)
            made.append(dst)
    for f in sorted(DEFAULTS.iterdir()):
        if f.name.endswith(".example"):
            continue
        if not (CONFIG / f.name).exists():
            config(f.name)
            made.append(CONFIG / f.name)
    if not KEYS.exists() and (DEFAULTS / "keys.env.example").exists():
        shutil.copy(DEFAULTS / "keys.env.example", KEYS)
        made.append(KEYS)
    if verbose:
        print(f"User folder: {HOME}")
        for p in made:
            print(f"  created {p.relative_to(HOME)}")
        if not made:
            print("  (already set up, nothing changed)")
        print("Next: edit profile.md, settings.json and cv/master.json there, then run `python3 jobagent.py run`.")
    return made
