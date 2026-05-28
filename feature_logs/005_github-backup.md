# 005 — GitHub backup setup

**Requested:** 2026-05-25
**Status:** blocked (shell sandbox prevents agent from running git)

## Request
> Let's start backing up and commiting to GitHub. Here's the repo URL: https://github.com/Byteme8bit/curly-octo-eureka

## Actions taken
- **`.gitignore`** — added `diagnostics/` and `git_setup_result.txt`
- **Created `scripts/git_setup.py`** — one-shot helper that runs `git init`, adds remote, stages all (excluding `.env`), commits with initial message, and pushes `main`
- **`README.md`** — added `## GitHub backup` section with usage instructions
- Subsequent agent retries to push were blocked by Cursor's Windows sandbox helper limitation (see request 007)

## Verification
User must run locally:
```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe .\scripts\git_setup.py
```
If push fails on auth: `gh auth login` then `git push -u origin main`.

## Notes
- Remote: `https://github.com/Byteme8bit/curly-octo-eureka.git`
- Script guarantees `.env` is unstaged before commit (defense-in-depth on top of .gitignore).
