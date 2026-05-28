"""One-time git init, commit, and push helper. Run: python scripts/git_setup.py"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "https://github.com/Byteme8bit/curly-octo-eureka.git"
LOG = ROOT / "git_setup_result.txt"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result


def main() -> int:
    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        lines.append(msg)

    if (ROOT / ".env").exists():
        log("OK: .env exists locally (must stay untracked)")

    r = run(["git", "rev-parse", "--is-inside-work-tree"], check=False)
    if r.returncode != 0:
        r = run(["git", "init"])
        log(r.stdout.strip() or r.stderr.strip() or "git init")
    else:
        log("Already a git repository")

    r = run(["git", "remote", "get-url", "origin"], check=False)
    if r.returncode != 0:
        run(["git", "remote", "add", "origin", REMOTE])
        log(f"Added remote origin -> {REMOTE}")
    else:
        url = r.stdout.strip()
        if url != REMOTE:
            run(["git", "remote", "set-url", "origin", REMOTE])
            log(f"Updated remote origin -> {REMOTE}")
        else:
            log(f"Remote origin already set -> {REMOTE}")

    run(["git", "add", "-A"])
    run(["git", "reset", "HEAD", "--", ".env"], check=False)

    staged = run(["git", "diff", "--cached", "--name-only"], check=False)
    staged_files = [f for f in staged.stdout.splitlines() if f.strip()]
    if ".env" in staged_files:
        log("ERROR: .env is staged — aborting")
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return 1

    log(f"Staged {len(staged_files)} files")
    for name in staged_files:
        log(f"  + {name}")

    msg = (
        "Initial commit: Kraken paper trading bot\n\n"
        "Multi-strategy orchestrator with cross-momentum, stat arb, and triangular "
        "arbitrage. Includes Discord integration, watchdog monitoring, portfolio "
        "constraints, and strategy governance. Secrets and runtime state stay local."
    )
    commit = run(["git", "commit", "-m", msg], check=False)
    log(commit.stdout.strip() or commit.stderr.strip() or "commit done")
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return commit.returncode

    branch = run(["git", "branch", "--show-current"], check=False)
    current = branch.stdout.strip() or "main"
    if not current:
        run(["git", "checkout", "-b", "main"])
        current = "main"
        log("Created branch main")

    push = run(["git", "push", "-u", "origin", current], check=False)
    log(push.stdout.strip() or push.stderr.strip() or f"push origin {current}")
    if push.returncode != 0:
        log("Push failed — you may need: gh auth login  or  git credential setup")
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return push.returncode

    log(f"SUCCESS: pushed to {REMOTE} on branch {current}")
    LOG.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
