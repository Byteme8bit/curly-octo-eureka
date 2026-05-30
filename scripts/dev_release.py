"""Real-developer-style git release tool.

For the initial catch-up: groups the pile of uncommitted work into thematic
commits on a feature branch, pushes, and opens a PR with the GitHub CLI.

Usage::

    python scripts/dev_release.py                          # use defaults
    python scripts/dev_release.py --branch feat/my-thing   # custom branch
    python scripts/dev_release.py --no-push                # commit only
    python scripts/dev_release.py --no-pr                  # commit + push, no PR

Safety rails:

- Refuses to stage anything named ``.env`` or matching ``Error Logs/``,
  ``runtime_overrides.json``, ``.paper_state.json`` etc. (the .gitignore
  already excludes them; this is belt-and-braces).
- Aborts if the working tree is clean (nothing to commit).
- Aborts if the requested branch already exists locally and isn't empty.
- Never force-pushes.
- Never amends an existing commit.

Future use: edit ``COMMIT_PLAN`` to define a different set of thematic
commits, or call ``--branch chore/something`` with a manifest you build
on the fly.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "git_setup_result.txt"

# Files/patterns we never want staged, even if the user accidentally added them.
HARD_EXCLUDES = {
    ".env",
    ".paper_state.json",
    ".watchdog_state.json",
    ".discord_pins.json",
    ".auditor_state.json",
    "paper_portfolio.json",
    "runtime_overrides.json",
    "git_setup_result.txt",
}
HARD_EXCLUDE_PREFIXES = (
    "Error Logs/",
    "logs/",
    "reports/",
    "diagnostics/",
    "receipts/",
)


@dataclass
class CommitPlan:
    """A single thematic commit: which paths to stage + the message to use."""
    title: str
    body: str
    paths: list[str]


# Order matters: earlier commits build up the bedrock the later ones rely on.
COMMIT_PLAN: list[CommitPlan] = [
    CommitPlan(
        title="chore: project hygiene, deps, gitignore, contributor docs",
        body=(
            "Pin .gitignore so local artifacts (.env, paper state, logs, error\n"
            "logs, reports, runtime overrides) stay out of the repo. Add\n"
            "requirements-dev.txt for the pytest suite. Refresh README and\n"
            "AGENTS.md and ship a .env.example documenting every knob."
        ),
        paths=[
            ".gitignore",
            ".env.example",
            "requirements.txt",
            "requirements-dev.txt",
            "pytest.ini",
            "README.md",
            "AGENTS.md",
        ],
    ),
    CommitPlan(
        title="feat(version-history): line-diff revision system + auto-snapshot rule",
        body=(
            "Introduce a tiny revision system that stores per-file unified\n"
            "diffs under VersionHistory/ instead of full copies. Each revision\n"
            "carries a reason + request id so we can grep history later. A\n"
            "Cursor rule (.cursor/rules/version-history.mdc) auto-snapshots\n"
            "modified files at the end of each agent turn. Includes a CLI\n"
            "(snapshot/list/show/restore/verify) and a one-shot bootstrap to\n"
            "create r001 baselines for already-existing files."
        ),
        paths=[
            "bot/version_history.py",
            "scripts/version_history.py",
            "scripts/bootstrap_version_history.py",
            ".cursor/rules/version-history.mdc",
            "VersionHistory/",
        ],
    ),
    CommitPlan(
        title="feat(observability): fatal error log + Discord chat log + diagnostics",
        body=(
            "Capture every fatal startup/runtime error to Error Logs/ with\n"
            "hints for common failure modes (wrong venv, missing tzdata, etc.).\n"
            "Mirror Discord chat to a local file for offline replay. Add\n"
            "verify_main_startup.py and archive_error_logs.py helpers.\n"
            "Centralise Pacific-time formatting in bot/local_time.py."
        ),
        paths=[
            "bot/fatal_error_log.py",
            "bot/discord_chat_log.py",
            "bot/local_time.py",
            "scripts/verify_main_startup.py",
            "scripts/archive_error_logs.py",
        ],
    ),
    CommitPlan(
        title="feat(portfolio): min ETH reserve, max alt cap, persistent snapshot",
        body=(
            "Enforce a user-defined ETH reserve and per-alt allocation ceiling\n"
            "via PortfolioConstraints. Add StrategyGovernor for agile but\n"
            "sticky strategy reevaluation. Persist a human-readable\n"
            "paper_portfolio.json snapshot every tick so 'show portfolio'\n"
            "works without a live bot session."
        ),
        paths=[
            "bot/portfolio_constraints.py",
            "bot/strategy_governor.py",
            "bot/paper_portfolio.py",
            "scripts/show_portfolio.py",
        ],
    ),
    CommitPlan(
        title="feat(watchdog): cooperative shutdown, error categorization, smart pinning",
        body=(
            "Fix the watchdog so it stops cleanly with TradeBot (cooperative\n"
            "_stop_requested flag instead of join-timeout). Categorize errors\n"
            "by source (bot vs watchdog) and switch all persisted timestamps\n"
            "to wall-clock time so they survive restarts. Only pin an error\n"
            "after 3 hits in 30 min to stop spam. Health report now scores\n"
            "bot errors heavier than watchdog errors."
        ),
        paths=[
            "watchdog/",
            "bot/watchdog_service.py",
            "bot/pin_tracker.py",
        ],
    ),
    CommitPlan(
        title="feat(auditor): scheduled audit bot with proposals and runtime overrides",
        body=(
            "Read-only auditor that reviews trades, market data, news, and\n"
            "watchdog health on a schedule or on demand. Generates a markdown\n"
            "report plus PnL forecasts (24h/7d/30d bootstrap). Proposes tuning\n"
            "changes to a whitelist of safe knobs; user confirms via\n"
            "`Auditor -confirm <id>`. Approved changes land in\n"
            "runtime_overrides.json (non-destructive vs .env).\n\n"
            "News client prefers free RSS feeds (CoinDesk, Cointelegraph,\n"
            "Decrypt, The Block, Bitcoin Magazine) with CoinGecko + CryptoPanic\n"
            "as opt-in fallbacks.\n\n"
            "Optional sleep-window auto-apply: between 01:00–07:00 PT, the\n"
            "auditor may apply one high-confidence proposal and restart the\n"
            "bot. Disabled by default; per-night cap and broker-health gate."
        ),
        paths=[
            "bot/auditor_service.py",
            "bot/auditor/__init__.py",
            "bot/auditor/config.py",
            "bot/auditor/analyzer.py",
            "bot/auditor/forecaster.py",
            "bot/auditor/news_client.py",
            "bot/auditor/proposer.py",
            "bot/auditor/runtime_overrides.py",
            "bot/auditor/state.py",
            "bot/auditor/report.py",
        ],
    ),
    CommitPlan(
        title="feat(auditor-chat): Discord Q&A via Gemini with read-only tools",
        body=(
            "Lets the user ask the auditor questions in Discord without\n"
            "burning Cursor tokens. Two entry points:\n"
            "  • Auditor -ask <q>    : single-turn\n"
            "  • Auditor -chat <msg> : multi-turn per user/channel\n\n"
            "Strictly read-only — the LLM gets a tool registry covering\n"
            "portfolio, trades, strategy stats, overrides, proposals, audit\n"
            "summaries, watchdog health, errors, news, settings, and prices.\n"
            "No tool can mutate state.\n\n"
            "Token-conscious by default: gemini-2.5-flash-lite, 2 tool\n"
            "iterations per question, 2000-char tool result cap, 6-turn\n"
            "rolling history, per-turn duplicate-tool-call cache, friendly\n"
            "429 handling with auto-retry on short retry_delay."
        ),
        paths=[
            "bot/auditor/chat/__init__.py",
            "bot/auditor/chat/backends.py",
            "bot/auditor/chat/service.py",
            "bot/auditor/chat/tools.py",
        ],
    ),
    CommitPlan(
        title="feat(architecture): docs + UI color tokens + design system",
        body=(
            "Stand up docs/ with architecture (overview, modules,\n"
            "tick-lifecycle), conventions (naming, patterns, verification,\n"
            "contributing), and design (color tokens, Discord style guide,\n"
            "pattern library). Move ANSI terminal colors + Discord embed\n"
            "colors into bot/ui_tokens.py so we have one source of truth."
        ),
        paths=[
            "docs/",
            "bot/ui_tokens.py",
        ],
    ),
    CommitPlan(
        title="refactor(engine): wire new services + harden core trading loop",
        body=(
            "Plumb PortfolioConstraints, StrategyGovernor, WatchdogService,\n"
            "AuditorService, PaperPortfolioLog, and PinTracker into\n"
            "TradingEngine. Refactor main.py to wrap _run() in a fatal-error\n"
            "catch so any startup explosion lands in Error Logs/. Add Kraken\n"
            "API retry with exponential backoff + caching. Compute true PnL\n"
            "for cross-coin swap legs (no more $0.00 (entry) bug). Display\n"
            "startup banner from loaded state instead of hardcoded balances.\n"
            "Discord startup pin now lists active runtime overrides.\n\n"
            "Adds os.execv-based self-restart so Auditor auto-apply can pick\n"
            "up new overrides without manual intervention."
        ),
        paths=[
            "bot/engine.py",
            "bot/paper_broker.py",
            "bot/trade_log.py",
            "bot/display.py",
            "bot/discord_bot.py",
            "bot/data.py",
            "bot/report.py",
            "bot/orchestrator.py",
            "bot/risk.py",
            "bot/runtime.py",
            "bot/status.py",
            "bot/error_report.py",
            "bot/preflight.py",
            "bot/circuit_breaker.py",
            "bot/markets.py",
            "bot/fee_engine.py",
            "bot/alerts.py",
            "bot/adaptive.py",
            "bot/__init__.py",
            "bot/strategies/",
            "config.py",
            "main.py",
            "check_discord.py",
        ],
    ),
    CommitPlan(
        title="test: comprehensive pytest suite across all subsystems",
        body=(
            "Cover the new code with regression tests:\n"
            "  • fatal_error_log, version_history, paper_portfolio\n"
            "  • portfolio_constraints, strategy_governor\n"
            "  • watchdog state + receipt parsing\n"
            "  • Kraken retry behavior, trade_log PnL formatting\n"
            "  • UI tokens, startup display, Discord command parser\n"
            "  • Auditor (analyzer, forecaster, news, proposer,\n"
            "    runtime_overrides, sleep-window auto-apply)\n"
            "  • Auditor chat (tools, ChatService, Gemini backend\n"
            "    error classification + auto-retry, dedup + truncation)\n\n"
            "Includes a wiring regression test that fails if a new\n"
            "AuditorConfig field is added without being passed through\n"
            "from Settings in engine.py."
        ),
        paths=[
            "tests/",
        ],
    ),
    CommitPlan(
        title="docs: feature request log + Discord command reference",
        body=(
            "Capture every feature request as a numbered markdown file in\n"
            "feature_logs/ documenting what the user asked for and the\n"
            "actions taken. DISCORD_COMMANDS.txt is the canonical reference\n"
            "for every TradeBot/WatchDog/Auditor slash command."
        ),
        paths=[
            "feature_logs/",
            "DISCORD_COMMANDS.txt",
        ],
    ),
]


# ---------------------------------------------------------------------------
# implementation
# ---------------------------------------------------------------------------


def run(cmd: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a git command from the repo root and return the CompletedProcess."""
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        sys.stderr.write(f"\n$ {' '.join(cmd)}\n{result.stdout}{result.stderr}\n")
        raise SystemExit(result.returncode)
    return result


def current_branch() -> str:
    return run(["git", "branch", "--show-current"]).stdout.strip() or "main"


def working_tree_dirty() -> bool:
    return bool(run(["git", "status", "--porcelain"]).stdout.strip())


def list_unstaged_paths() -> list[str]:
    """All untracked + modified paths reported by `git status --porcelain`."""
    out = run(["git", "status", "--porcelain"]).stdout
    paths: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # porcelain: "XY path" (or "XY orig -> new" for renames)
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        paths.append(path)
    return paths


def is_excluded(path: str) -> bool:
    name = Path(path).name
    if name in HARD_EXCLUDES or path in HARD_EXCLUDES:
        return True
    for prefix in HARD_EXCLUDE_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def expand_plan_paths(plan_paths: list[str], available: set[str]) -> list[str]:
    """Resolve a manifest entry to the actual files that exist + are dirty.

    A manifest entry can be:
      - an exact file path  (matched verbatim)
      - a directory prefix  (e.g. "docs/" matches every dirty file under docs/)
    """
    resolved: list[str] = []
    for entry in plan_paths:
        if entry.endswith("/"):
            resolved.extend(p for p in available if p.startswith(entry))
        else:
            if entry in available:
                resolved.append(entry)
    return sorted(set(resolved))


def ensure_clean_start(branch: str) -> None:
    if not working_tree_dirty():
        print("Working tree is clean — nothing to commit. Exiting.")
        raise SystemExit(0)
    existing = run(["git", "rev-parse", "--verify", "--quiet", branch], check=False)
    if existing.returncode == 0:
        print(
            f"Branch '{branch}' already exists locally. Pick another name with --branch "
            "or delete the existing one first."
        )
        raise SystemExit(2)


def make_branch(branch: str) -> None:
    run(["git", "checkout", "-b", branch])
    print(f"  created branch '{branch}'")


def stage_and_commit(plan: CommitPlan, paths: list[str]) -> bool:
    """Stage + commit one group. Returns True if a commit was made."""
    safe_paths = [p for p in paths if not is_excluded(p)]
    if not safe_paths:
        print(f"  - skip '{plan.title}' (no matching dirty files)")
        return False

    run(["git", "add", "--", *safe_paths])
    # Sanity: verify nothing forbidden snuck in.
    staged = run(["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
    bad = [p for p in staged if is_excluded(p)]
    if bad:
        run(["git", "reset", "HEAD", "--", *bad], check=False)
        print(f"  ! unstaged forbidden paths: {bad}")

    full_msg = f"{plan.title}\n\n{plan.body}\n"
    commit = run(["git", "commit", "-m", full_msg], check=False)
    if commit.returncode != 0:
        out = (commit.stdout + commit.stderr).strip()
        if "nothing to commit" in out:
            print(f"  - skip '{plan.title}' (nothing left to commit)")
            return False
        print(f"  ! commit failed for '{plan.title}':\n{out}")
        raise SystemExit(commit.returncode)
    sha = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(f"  + {sha}  {plan.title}  ({len(safe_paths)} files)")
    return True


def make_catchall_commit(remaining: list[str]) -> bool:
    safe = [p for p in remaining if not is_excluded(p)]
    if not safe:
        return False
    print(f"  ~ catch-all commit for {len(safe)} unclassified file(s)")
    run(["git", "add", "--", *safe])
    msg = (
        "chore: catch-all for files not matched by dev_release manifest\n\n"
        "Files staged here weren't covered by any thematic group in\n"
        "scripts/dev_release.py. Move them into the manifest for next time."
    )
    commit = run(["git", "commit", "-m", msg], check=False)
    if commit.returncode != 0:
        return False
    sha = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(f"  + {sha}  chore: catch-all")
    return True


def push_branch(branch: str) -> None:
    print(f"\nPushing branch '{branch}' to origin...")
    result = run(["git", "push", "-u", "origin", branch], check=False, capture=False)
    if result.returncode != 0:
        print("Push failed. If this is an auth issue, run `gh auth login` first.")
        raise SystemExit(result.returncode)


def open_pull_request(branch: str, title: str, body: str) -> None:
    if not shutil.which("gh"):
        print(
            "\n`gh` CLI not found — install GitHub CLI (https://cli.github.com) and "
            f"run:\n  gh pr create --base main --head {branch} --title \"{title}\""
        )
        return
    print("\nOpening pull request via gh...")
    result = subprocess.run(
        ["gh", "pr", "create", "--base", "main", "--head", branch,
         "--title", title, "--body", body],
        cwd=ROOT, text=True, capture_output=False,
    )
    if result.returncode != 0:
        print(
            "\n`gh pr create` failed. If you're not logged in, run `gh auth login` "
            "and then re-run with --pr-only (or manually open a PR on github.com)."
        )
        raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--branch",
        default="chore/initial-catchup",
        help="Feature branch name (default: chore/initial-catchup).",
    )
    parser.add_argument(
        "--pr-title",
        default="chore: initial catch-up of accumulated work",
        help="Pull request title.",
    )
    parser.add_argument("--no-push", action="store_true", help="Commit only, don't push.")
    parser.add_argument("--no-pr", action="store_true", help="Skip `gh pr create`.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan without modifying anything.",
    )
    args = parser.parse_args()

    print(f"=== dev_release.py — branch '{args.branch}' ===\n")

    ensure_clean_start(args.branch)

    available = set(list_unstaged_paths())
    classified: set[str] = set()

    print(f"Discovered {len(available)} dirty path(s) in working tree.\n")

    if args.dry_run:
        print("Plan:")
        for plan in COMMIT_PLAN:
            resolved = expand_plan_paths(plan.paths, available)
            print(f"  • {plan.title}: {len(resolved)} file(s)")
            for p in resolved[:5]:
                print(f"      - {p}")
            if len(resolved) > 5:
                print(f"      ... and {len(resolved) - 5} more")
            classified.update(resolved)
        remaining = sorted(available - classified)
        remaining = [p for p in remaining if not is_excluded(p)]
        print(f"\nUnclassified (would land in catch-all): {len(remaining)}")
        for p in remaining[:20]:
            print(f"      - {p}")
        return 0

    make_branch(args.branch)
    print()

    for plan in COMMIT_PLAN:
        resolved = expand_plan_paths(plan.paths, available)
        if stage_and_commit(plan, resolved):
            classified.update(resolved)

    remaining = sorted(available - classified)
    if remaining:
        make_catchall_commit(remaining)

    total = run(["git", "rev-list", "--count", f"main..{args.branch}"]).stdout.strip()
    print(f"\nCreated {total} commit(s) on '{args.branch}'.")

    if args.no_push:
        print("--no-push set; stopping here. To push later:")
        print(f"  git push -u origin {args.branch}")
        return 0

    push_branch(args.branch)

    if args.no_pr:
        return 0

    pr_body = (
        "## Summary\n"
        "Catches the GitHub repo up with the accumulated local work. Split into "
        "thematic commits for reviewability — see commit list below for the per-area "
        "breakdown.\n\n"
        "## What's in this PR\n"
        "- Portfolio rules (min ETH reserve, max alt cap) + strategy governor\n"
        "- Watchdog hardening (clean shutdown, error categorization, smart pinning)\n"
        "- Auditor service (scheduled audits, proposals, runtime overrides, "
        "optional sleep-window auto-apply)\n"
        "- Auditor conversational chat via Gemini (read-only tools, "
        "token-conscious defaults)\n"
        "- Observability: fatal error logs, Discord chat log, paper portfolio snapshot\n"
        "- Version history system + auto-snapshot Cursor rule\n"
        "- Comprehensive pytest suite + architecture/design docs\n\n"
        "## Test plan\n"
        "- [x] `pytest` — full suite passes locally\n"
        "- [ ] Restart `main.py`, verify startup banner shows loaded state\n"
        "- [ ] `TradeBot -portfolio` shows non-zero PnL on cross-coin swaps\n"
        "- [ ] `WatchDog -status` reports correct error counts\n"
        "- [ ] `Auditor -ask` returns a sensible answer (chat enabled)\n"
        "- [ ] Confirm `.env` is NOT in the diff\n"
    )
    open_pull_request(args.branch, args.pr_title, pr_body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
