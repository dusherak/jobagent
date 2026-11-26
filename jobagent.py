#!/usr/bin/env python3
"""Job agent: one command for everything.

    python3 jobagent.py init       create your user folder (~/.jobagent) with templates to fill in
    python3 jobagent.py run        full run: find jobs, AI screening, read-only Gmail check
    python3 jobagent.py feed       just the job feed (add --all for every open match)
    python3 jobagent.py serve      local website at http://127.0.0.1:8000
    python3 jobagent.py where      show where your data lives

Set JOBAGENT_HOME to keep your data somewhere other than ~/.jobagent.
"""

import subprocess
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
import userdata as U  # noqa: E402


def main():
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else "help"), sys.argv[2:]
    if cmd == "init":
        U.init()
        return 0
    if cmd == "where":
        print(U.HOME)
        return 0
    scripts = {"run": "morning.py", "feed": "jobfeed/feed.py", "serve": "webapp/server.py"}
    if cmd not in scripts:
        print(__doc__)
        return 0 if cmd in ("help", "-h", "--help") else 2
    if not U.PROFILE.exists():
        print("No user folder yet. Run `python3 jobagent.py init` first, then fill in profile.md.")
        return 1
    return subprocess.call([sys.executable, str(CODE / scripts[cmd]), *rest], cwd=CODE)


if __name__ == "__main__":
    sys.exit(main())
