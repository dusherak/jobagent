# Job agent

A local, private job-search assistant for graduate roles. It reads employers' public job boards, uses Claude to screen each posting against your profile (eligibility and fit), keeps an application tracker, checks your Gmail for recruiter replies (read-only), and tailors your CV and cover letter for a specific role, without inventing anything.

It ships with a preset for **graduate finance roles in London** (investment banking, asset management, credit, consulting, AI). Every part of that preset is editable config.

## What it will never do
- Submit an application, send an email or message anyone. It drafts; you send.
- Log in to job sites or LinkedIn, solve CAPTCHAs, or get around bot checks. It only reads public job listings and respects robots.txt. Sites that block automated reading are listed for you to check by hand.
- Add experience you don't have. Tailored CVs may only reword and reorder your master CV, and a checker flags any employer or number that isn't in it.

## Requirements
- Python 3.10+ (the core uses only the standard library)
- [Claude Code](https://claude.com/claude-code), installed and signed in (`claude` on your PATH). It's used for screening, tailoring and the Gmail check.
- Optional: Google Chrome plus the venv below, for JavaScript-only job pages and PDF output
- Optional: Gmail connected in Claude, for the read-only inbox check
- Optional: free Reed / Adzuna API keys

## Quick start
```bash
python3 jobagent.py init      # creates ~/.jobagent with templates
```
Then fill in, in `~/.jobagent/`:
- `profile.md`: what you want, what you're eligible for (visa, graduation date) and your deal-breakers
- `settings.json`: your name, the PDF file prefix and your city
- `cv/master.json`: your real CV. This is the only source of facts for tailoring.
- `cv/own_letters.md`: a few of your own cover letters, so drafts match your voice

```bash
python3 jobagent.py run       # find jobs, screen them, check Gmail
python3 jobagent.py serve     # open http://127.0.0.1:8000
```

For JavaScript-only pages and PDFs:
```bash
uv venv jobfeed/.venv --python 3.12
uv pip install --python jobfeed/.venv/bin/python -r requirements.txt
```

## Where things live
| | |
|---|---|
| This repo | Code, `defaults/` (job boards, filters, models, firm lists) and `templates/`. No personal data. |
| `~/.jobagent/` (or `$JOBAGENT_HOME`) | Your profile, CV, letters, tracker, digests, caches, API keys and your editable copy of the config in `config/` |

Change which employers are read in `config/sources.json`, the title and location filters in `config/filters.json`, and the Claude model for each step in `config/models.json`.

## How it works
- `jobfeed/feed.py`: reads public job-board APIs (Greenhouse, Lever, Ashby, Workday, Oracle, SmartRecruiters, Workable, Teamtailor, Eightfold, …) and broad boards. It keeps roles from the last 14 days that match your filters, and checks employers against the UK visa-sponsor register.
- `jobfeed/details.py`: reads each full description. Fixed rules catch "no sponsorship", Master's required and years of experience; then Claude screens the posting against `profile.md`.
- `jobfeed/discover.py`: weekly search for job boards of firms you care about.
- `webapp/`: the local website (Jobs, Applications, Documents, Live tabs), the tailoring studio and the read-only Gmail check.

## Status
Early. The defaults are UK-focused (sponsor register, Reed, TargetJobs). PRs for other countries and presets are welcome.

## License
MIT, see [LICENSE](LICENSE).
