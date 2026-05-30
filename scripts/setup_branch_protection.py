"""Configure branch protection rules on `main` via the GitHub API.

Run once after the initial push. Requires `gh` CLI installed + authenticated.

What it enforces:
  - Pull request required before merge (>= 1 approving review)
  - Stale review dismissal when new commits land
  - Conversation resolution required
  - Force pushes blocked
  - Branch deletion blocked
  - Status checks required (the CI workflow this repo will ship)

This is safe to run multiple times — GitHub treats it as upsert.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "Byteme8bit"
REPO = "curly-octo-eureka"
BRANCH = "main"

# Status checks we want enforced — these must match the CI workflow's job names.
REQUIRED_CHECKS = ["pytest"]


def gh(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=stdin,
    )


def must(result: subprocess.CompletedProcess, action: str) -> None:
    if result.returncode != 0:
        sys.stderr.write(
            f"\n!! `{action}` failed (exit {result.returncode}):\n"
            f"{result.stdout}{result.stderr}\n"
        )
        sys.exit(result.returncode)


def main() -> int:
    auth = gh(["auth", "status"])
    if auth.returncode != 0:
        print("`gh` is not authenticated. Run `gh auth login` first, then re-run this.")
        return 1
    print("OK: gh CLI authenticated.")

    payload = {
        "required_status_checks": {
            "strict": True,  # branch must be up-to-date before merging
            "contexts": REQUIRED_CHECKS,
        },
        "enforce_admins": False,  # admin (you) can bypass in emergencies
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
            "require_last_push_approval": False,
        },
        "restrictions": None,  # required field; null = allow anyone with push access
        "required_linear_history": True,        # no merge commits, only squash/rebase
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
        "lock_branch": False,
        "allow_fork_syncing": False,
    }

    print(f"Applying branch protection to {OWNER}/{REPO}@{BRANCH}...")
    result = gh(
        [
            "api",
            "--method", "PUT",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            f"/repos/{OWNER}/{REPO}/branches/{BRANCH}/protection",
            "--input", "-",
        ],
        stdin=json.dumps(payload),
    )
    if result.returncode != 0:
        body = result.stdout + result.stderr
        if "Upgrade" in body or "advanced security" in body.lower():
            print(
                "\n!! GitHub returned an upgrade-required error. Branch\n"
                "   protection is FREE on public repos but some features\n"
                "   require GitHub Pro on private repos. If your repo is\n"
                "   private, either:\n"
                "     1) Make it public:  gh repo edit "
                f"{OWNER}/{REPO} --visibility public\n"
                "     2) Or upgrade your GitHub account (separate from Cursor Pro).\n"
            )
            return 1
        must(result, "branch protection PUT")

    print(f"\nProtection active on {BRANCH}:")
    print("  • PR required (>= 1 approving review)")
    print("  • Stale reviews dismissed on new push")
    print("  • Required status checks: " + ", ".join(REQUIRED_CHECKS))
    print("  • Force pushes blocked")
    print("  • Deletions blocked")
    print("  • Conversations must be resolved")
    print("  • Linear history only (squash/rebase merges)")
    print()
    print("From now on, push directly to main will be REJECTED.")
    print("Workflow:  git checkout -b feat/x  →  push  →  gh pr create  →  merge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
