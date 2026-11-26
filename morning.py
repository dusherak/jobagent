"""Morning run (scheduled every other day): find new jobs, screen them, then check Gmail.

1. jobfeed/feed.py reads the job boards, fetches each new posting and screens it (eligibility + whether you'd want it, judged from profile.md).
   Roles that pass appear on the website's Jobs tab with a short description.
2. webapp/gmail.py reads the last 7 days of recruiting email (read-only) and queues status updates for approval.
Models per step are set in <user folder>/config/models.json.
"""

import os
from datetime import date
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "webapp"))
sys.path.insert(0, str(ROOT / "jobfeed"))
import progress  # noqa: E402  (live view on the website)
import userdata as U  # noqa: E402


def main():
    progress.start("morning")
    os.environ["JOBAGENT_RUN"] = "1"          # feed.py and gmail.py add to this run instead of starting their own
    # once a week: look for employers whose own job boards the feed doesn't read yet (adds them to sources.json)
    last = U.STATE / "discovery_last.txt"
    last.parent.mkdir(parents=True, exist_ok=True)
    if not last.exists() or (date.today() - date.fromisoformat(last.read_text().strip())).days >= 7:
        try:
            import discover
            print(discover.main())
            last.write_text(date.today().isoformat())
        except Exception as e:
            print("Discovery: FAILED", str(e)[:200])
    r = subprocess.run([sys.executable, str(ROOT / "jobfeed" / "feed.py")], cwd=ROOT, capture_output=True, text=True, timeout=2400)
    print("Jobs:", (r.stdout.strip().splitlines() or ["no output"])[-1] if r.returncode == 0 else "FAILED " + (r.stderr or r.stdout)[-300:])
    try:
        import gmail
        print("Gmail:", gmail.check(log=lambda m: None))
    except Exception as e:
        print("Gmail: FAILED", str(e)[:300])


if __name__ == "__main__":
    main()
