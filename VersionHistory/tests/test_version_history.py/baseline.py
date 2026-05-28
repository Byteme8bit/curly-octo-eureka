"""Tests for `bot.version_history`.

Every test isolates state in `tmp_path` by pointing the module's
project / history roots at fresh temp dirs via env vars. Git is mocked
where its absence would matter.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return the version_history module with project root pinned to tmp_path."""
    monkeypatch.setenv("BOT_VERSION_HISTORY_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "BOT_VERSION_HISTORY_ROOT", str(tmp_path / "VersionHistory")
    )
    if "bot.version_history" in sys.modules:
        module = importlib.reload(sys.modules["bot.version_history"])
    else:
        from bot import version_history as module  # noqa: WPS433
    # Force git lookups to fail by default - tests opt-in via patching.
    monkeypatch.setattr(module, "_git_show", lambda rel: None)
    return module


@pytest.fixture
def sample_file(tmp_path: Path):
    """Create a sample file under tmp_path and return its absolute path."""
    target = tmp_path / "bot" / "sample.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def greet(name):\n"
        "    print(f'hello {name}')\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Snapshot basics
# ---------------------------------------------------------------------------


def test_first_snapshot_creates_baseline_and_r001(vh, sample_file):
    rev = vh.snapshot(sample_file, "initial capture", request_id="013")
    assert rev is not None
    assert rev.number == 1
    assert rev.patch_path.exists()
    baseline = vh._baseline_path(sample_file)
    assert baseline.exists()
    assert baseline.read_text(encoding="utf-8") == sample_file.read_text(
        encoding="utf-8"
    )
    # Index updated
    index = vh._load_index()
    rel = vh._rel_posix(sample_file)
    assert rel in index
    assert len(index[rel]) == 1
    assert index[rel][0]["request_id"] == "013"


def test_first_snapshot_with_git_baseline(vh, sample_file, monkeypatch):
    head_content = "def greet(name):\n    print('old')\n"
    monkeypatch.setattr(vh, "_git_show", lambda rel: head_content)
    rev = vh.snapshot(sample_file, "git baseline diff", request_id="013")
    assert rev is not None
    assert rev.number == 1
    baseline = vh._baseline_path(sample_file)
    assert baseline.read_text(encoding="utf-8") == head_content
    # Real diff was produced
    patch_text = rev.patch_path.read_text(encoding="utf-8")
    assert "@@" in patch_text
    assert rev.added > 0 or rev.removed > 0


def test_second_snapshot_records_diff_only(vh, sample_file):
    vh.snapshot(sample_file, "first", request_id="013")
    sample_file.write_text(
        "def greet(name):\n"
        "    print(f'hi {name}!!')\n",
        encoding="utf-8",
    )
    rev = vh.snapshot(sample_file, "tweak greeting", request_id="014")
    assert rev is not None
    assert rev.number == 2
    text = rev.patch_path.read_text(encoding="utf-8")
    assert "@@" in text
    assert "hello" in text
    assert "hi" in text
    assert rev.added >= 1
    assert rev.removed >= 1


def test_no_op_snapshot_returns_prior_revision_without_new_patch(vh, sample_file):
    first = vh.snapshot(sample_file, "first capture", request_id="013")
    assert first is not None
    rev = vh.snapshot(sample_file, "unchanged retry", request_id="014")
    file_dir = vh._file_dir(sample_file)
    patches = vh._scan_patch_files(file_dir)
    assert len(patches) == 1
    assert rev is not None
    assert rev.number == first.number
    assert rev.is_noop is True


# ---------------------------------------------------------------------------
# Listing / reconstruction
# ---------------------------------------------------------------------------


def test_list_revisions_ordered(vh, sample_file):
    vh.snapshot(sample_file, "one", request_id="013")
    sample_file.write_text(sample_file.read_text() + "\n# v2\n", encoding="utf-8")
    vh.snapshot(sample_file, "two", request_id="013")
    sample_file.write_text(sample_file.read_text() + "\n# v3\n", encoding="utf-8")
    vh.snapshot(sample_file, "three", request_id="013")
    revs = vh.list_revisions(sample_file)
    assert [r.number for r in revs] == [1, 2, 3]
    assert revs[0].reason == "one"
    assert revs[-1].reason == "three"


def test_reconstruct_matches_each_revision(vh, sample_file):
    v1_text = sample_file.read_text(encoding="utf-8")
    vh.snapshot(sample_file, "v1", request_id="013")

    v2_text = v1_text + "\n# v2 edit\n"
    sample_file.write_text(v2_text, encoding="utf-8")
    vh.snapshot(sample_file, "v2", request_id="013")

    v3_text = v2_text + "def extra():\n    pass\n"
    sample_file.write_text(v3_text, encoding="utf-8")
    vh.snapshot(sample_file, "v3", request_id="013")

    assert vh.reconstruct(sample_file, 1) == v1_text
    assert vh.reconstruct(sample_file, 2) == v2_text
    assert vh.reconstruct(sample_file, 3) == v3_text


def test_show_diff_has_headers_and_changes(vh, sample_file):
    vh.snapshot(sample_file, "v1", request_id="013")
    sample_file.write_text(
        sample_file.read_text() + "\n# extra line\n", encoding="utf-8"
    )
    diff_text = vh.show_diff(sample_file)
    assert "--- a/" in diff_text
    assert "+++ b/" in diff_text
    assert "+# extra line" in diff_text


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------


def test_revert_restores_content_and_creates_backup(vh, sample_file):
    v1_text = sample_file.read_text(encoding="utf-8")
    vh.snapshot(sample_file, "v1", request_id="013")

    sample_file.write_text(v1_text + "\n# bad edit\n", encoding="utf-8")
    vh.snapshot(sample_file, "v2 bad", request_id="013")

    # Simulate the realistic case: user has uncommitted edits on top of the
    # last snapshot when they ask for a revert. The backup must capture that.
    sample_file.write_text(
        v1_text + "\n# bad edit\n# uncommitted scratch\n", encoding="utf-8"
    )

    vh.revert(sample_file, 1, reason="rollback v2")

    assert sample_file.read_text(encoding="utf-8") == v1_text
    revs = vh.list_revisions(sample_file)
    assert len(revs) >= 3
    assert any("pre-revert backup" in r.reason for r in revs)


def test_revert_with_no_uncommitted_changes_still_works(vh, sample_file):
    v1_text = sample_file.read_text(encoding="utf-8")
    vh.snapshot(sample_file, "v1", request_id="013")

    sample_file.write_text(v1_text + "\n# bad edit\n", encoding="utf-8")
    vh.snapshot(sample_file, "v2 bad", request_id="013")

    vh.revert(sample_file, 1, reason="rollback v2")
    assert sample_file.read_text(encoding="utf-8") == v1_text


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------


def test_prune_local_keeps_last_n_patches(vh, sample_file):
    text = sample_file.read_text(encoding="utf-8")
    vh.snapshot(sample_file, "first", request_id="013")
    for i in range(2, 7):
        text = text + f"# bump {i}\n"
        sample_file.write_text(text, encoding="utf-8")
        vh.snapshot(sample_file, f"edit {i}", request_id="013")

    file_dir = vh._file_dir(sample_file)
    assert len(vh._scan_patch_files(file_dir)) == 6

    deleted = vh.prune_local(keep=2)
    rel = vh._rel_posix(sample_file)
    assert deleted.get(rel) == 4
    remaining = vh._scan_patch_files(file_dir)
    assert len(remaining) == 2
    # Baseline still present
    assert vh._baseline_path(sample_file).exists()
    # Highest-numbered patches survived
    nums = [int(vh._PATCH_RE.match(p.name).group(1)) for p in remaining]
    assert nums == [5, 6]


# ---------------------------------------------------------------------------
# Slug sanitisation
# ---------------------------------------------------------------------------


def test_slugify_basic_kebab_case(vh):
    assert vh._slugify("Hello World") == "hello-world"


def test_slugify_strips_specials_and_truncates(vh):
    long_reason = "Bug #42 — won't compile!!! " + ("x" * 80)
    slug = vh._slugify(long_reason)
    assert len(slug) <= 40
    assert "—" not in slug
    assert "#" not in slug
    assert "!" not in slug
    assert "'" not in slug
    assert slug.startswith("bug-42-wont-compile")
    # No leading/trailing dashes
    assert not slug.startswith("-")
    assert not slug.endswith("-")


def test_slugify_empty_returns_edit(vh):
    assert vh._slugify("") == "edit"
    assert vh._slugify("!!!") == "edit"


# ---------------------------------------------------------------------------
# CHANGELOG
# ---------------------------------------------------------------------------


def test_changelog_records_one_block_per_snapshot(vh, sample_file):
    vh.snapshot(sample_file, "first capture", request_id="013")
    sample_file.write_text(sample_file.read_text() + "\n# tweak\n", encoding="utf-8")
    vh.snapshot(sample_file, "tiny tweak", request_id="014")

    changelog = (vh._history_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "r001" in changelog
    assert "r002" in changelog
    assert "first capture" in changelog
    assert "tiny tweak" in changelog
    assert "013" in changelog
    assert "014" in changelog


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_unicode_and_quotes_in_reason(vh, sample_file):
    reason = 'fix "quoted" — naïve résumé café 测试'
    rev = vh.snapshot(sample_file, reason, request_id="013")
    assert rev is not None
    # Slug must still be ASCII / kebab-case
    name = rev.patch_path.name
    assert name.endswith(".patch")
    middle = name.rsplit("--", 1)[-1].removesuffix(".patch")
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in middle)
    # Changelog keeps the original (UTF-8) reason
    changelog = (vh._history_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "naïve" in changelog


def test_empty_diff_after_initial_no_op(vh, sample_file):
    """Two no-op snapshots back-to-back still leave just r001."""
    first = vh.snapshot(sample_file, "first", request_id="013")
    again = vh.snapshot(sample_file, "no-op", request_id="013")
    assert first is not None and again is not None
    assert first.number == again.number
    patches = vh._scan_patch_files(vh._file_dir(sample_file))
    assert len(patches) == 1


def test_reconstruct_then_modify_then_snapshot_chain(vh, sample_file):
    """Round-trip stress test: 5 revisions, reconstruct each, verify exact bytes."""
    history: list[str] = []
    text = sample_file.read_text(encoding="utf-8")
    history.append(text)
    vh.snapshot(sample_file, "rev 1", request_id="013")

    for i in range(2, 6):
        text = text + f"# stage {i}\n"
        if i % 2 == 0:
            text = text.replace("greet", f"greet_v{i}")
        sample_file.write_text(text, encoding="utf-8")
        vh.snapshot(sample_file, f"rev {i}", request_id="013")
        history.append(text)

    for n, expected in enumerate(history, start=1):
        got = vh.reconstruct(sample_file, n)
        assert got == expected, f"r{n:03d} mismatch:\nexpected={expected!r}\ngot={got!r}"


def test_auto_snapshot_handles_multiple_files(vh, tmp_path):
    a = tmp_path / "bot" / "a.py"
    b = tmp_path / "bot" / "b.py"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")
    revs = vh.auto_snapshot("bootstrap", [a, b], request_id="013")
    assert len(revs) == 2
    assert {r.path.name for r in revs} == {"a.py", "b.py"}


def test_verify_all_round_trip(vh, sample_file):
    vh.snapshot(sample_file, "v1", request_id="013")
    sample_file.write_text(sample_file.read_text() + "more\n", encoding="utf-8")
    vh.snapshot(sample_file, "v2", request_id="013")
    ok, errors = vh.verify_all()
    assert ok == 1
    assert errors == []


def test_initial_baseline_placeholder_when_no_git(vh, sample_file):
    """No git => baseline is the current file and r001 is a placeholder patch."""
    rev = vh.snapshot(sample_file, "initial", request_id="013")
    assert rev is not None
    patch_text = rev.patch_path.read_text(encoding="utf-8")
    assert "initial baseline" in patch_text
    assert rev.added == 0
    assert rev.removed == 0


def test_revisions_are_zero_padded_three_digits(vh, sample_file):
    text = sample_file.read_text(encoding="utf-8")
    vh.snapshot(sample_file, "v1", request_id="013")
    for i in range(2, 5):
        text = text + f"# v{i}\n"
        sample_file.write_text(text, encoding="utf-8")
        vh.snapshot(sample_file, f"v{i}", request_id="013")
    patches = vh._scan_patch_files(vh._file_dir(sample_file))
    for p in patches:
        assert vh._PATCH_RE.match(p.name) is not None, p.name
        prefix = p.name[:4]
        assert prefix.startswith("r")
        assert prefix[1:].isdigit()
        assert len(prefix[1:]) == 3


# ---------------------------------------------------------------------------
# CLI messaging
# ---------------------------------------------------------------------------


def _load_cli_module():
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "version_history_cli",
        root / "scripts" / "version_history.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_snapshot_no_op_message(vh, sample_file, capsys, monkeypatch):
    import argparse

    cli = _load_cli_module()
    monkeypatch.setattr(cli, "vh", vh)
    vh.snapshot(sample_file, "first", request_id="013")
    args = argparse.Namespace(paths=[sample_file], reason="retry", request_id="014")
    assert cli._cmd_snapshot(args) == 0
    out = capsys.readouterr().out
    assert "No changes — previous revision is r001" in out
    assert "Recorded r001" not in out


def test_cli_snapshot_recorded_message(vh, sample_file, capsys, monkeypatch):
    import argparse

    cli = _load_cli_module()
    monkeypatch.setattr(cli, "vh", vh)
    args = argparse.Namespace(paths=[sample_file], reason="first", request_id="013")
    assert cli._cmd_snapshot(args) == 0
    out = capsys.readouterr().out
    assert "Recorded r001" in out
    assert "No changes" not in out


def test_cli_snapshot_batch_multiple_paths(vh, sample_file, tmp_path, capsys, monkeypatch):
    """Batch snapshot writes one revision per path and shares reason/request-id."""
    import argparse

    second = tmp_path / "second.py"
    second.write_text("print('hi')\n", encoding="utf-8")

    cli = _load_cli_module()
    monkeypatch.setattr(cli, "vh", vh)
    args = argparse.Namespace(
        paths=[sample_file, second], reason="batch", request_id="020"
    )
    assert cli._cmd_snapshot(args) == 0
    out = capsys.readouterr().out
    # Both files should appear in the output, each recorded as r001.
    assert out.count("Recorded r001") == 2
