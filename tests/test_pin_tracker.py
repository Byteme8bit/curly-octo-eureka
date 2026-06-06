"""Tests for bot.pin_tracker — Discord pin retention bookkeeping.

PinTracker persists which messages the bot has pinned and enforces Discord's
50-pin ceiling by rotating the oldest entries. The startup pin is special: it
is exempt from rotation and tracked separately. Bugs here either leak pins
(hitting Discord's hard limit and breaking future pins) or accidentally rotate
the startup pin, so these tests cover the retention cap, startup-pin exemption,
JSON persistence/recovery, and the reconcile merge against live Discord state.
"""

from __future__ import annotations

import json
from pathlib import Path

from bot.pin_tracker import PinTracker


def _tracker(tmp_path: Path, channel_id: str = "chan-1", max_retain: int = 5) -> PinTracker:
    return PinTracker(tmp_path / "pins.json", channel_id, max_retain)


# ---------------------------------------------------------------------------
# Construction / max_retain clamping
# ---------------------------------------------------------------------------

def test_max_retain_clamped_to_floor(tmp_path):
    assert _tracker(tmp_path, max_retain=0).max_retain == 1
    assert _tracker(tmp_path, max_retain=-10).max_retain == 1


def test_max_retain_clamped_to_ceiling(tmp_path):
    # Discord allows 50 pins; tracker caps at 49 to leave room.
    assert _tracker(tmp_path, max_retain=100).max_retain == 49


# ---------------------------------------------------------------------------
# register / dedupe / ordering
# ---------------------------------------------------------------------------

def test_register_appends_in_order(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.register("2")
    assert t.ids() == ["1", "2"]


def test_register_coerces_to_string(tmp_path):
    t = _tracker(tmp_path)
    t.register(123)
    assert t.ids() == ["123"]


def test_register_dedupes_and_moves_to_end(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.register("2")
    t.register("1")  # re-registering moves it to the most-recent slot
    assert t.ids() == ["2", "1"]


def test_register_ignores_startup_pin(tmp_path):
    t = _tracker(tmp_path)
    t.set_startup_pin("99")
    t.register("99")
    assert t.ids() == []
    assert t.startup_pin_id() == "99"


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def test_remove_drops_id(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.register("2")
    t.remove("1")
    assert t.ids() == ["2"]


def test_remove_unknown_is_noop(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.remove("nope")
    assert t.ids() == ["1"]


def test_remove_never_drops_startup_pin(tmp_path):
    t = _tracker(tmp_path)
    t.set_startup_pin("99")
    t.remove("99")
    assert t.startup_pin_id() == "99"


# ---------------------------------------------------------------------------
# pop_oldest
# ---------------------------------------------------------------------------

def test_pop_oldest_fifo(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.register("2")
    assert t.pop_oldest() == "1"
    assert t.ids() == ["2"]


def test_pop_oldest_empty_returns_none(tmp_path):
    t = _tracker(tmp_path)
    assert t.pop_oldest() is None


def test_pop_oldest_skips_startup_pin(tmp_path):
    t = _tracker(tmp_path)
    # Force a startup pin id into the rotation list via persistence, then ensure
    # pop_oldest never returns it.
    t.register("1")
    t._ids.insert(0, "startup")  # simulate stale duplicate
    t._startup_pin_id = "startup"
    assert t.pop_oldest() == "1"


# ---------------------------------------------------------------------------
# startup pin lifecycle
# ---------------------------------------------------------------------------

def test_set_startup_pin_returns_previous(tmp_path):
    t = _tracker(tmp_path)
    assert t.set_startup_pin("a") is None
    assert t.set_startup_pin("b") == "a"
    assert t.startup_pin_id() == "b"


def test_set_startup_pin_removes_from_rotation(tmp_path):
    t = _tracker(tmp_path)
    t.register("5")
    t.set_startup_pin("5")
    assert t.ids() == []
    assert t.startup_pin_id() == "5"


def test_clear_startup_pin_returns_previous(tmp_path):
    t = _tracker(tmp_path)
    t.set_startup_pin("a")
    assert t.clear_startup_pin() == "a"
    assert t.startup_pin_id() is None


# ---------------------------------------------------------------------------
# at_capacity / clear_all
# ---------------------------------------------------------------------------

def test_at_capacity(tmp_path):
    t = _tracker(tmp_path, max_retain=2)
    assert t.at_capacity() is False
    t.register("1")
    t.register("2")
    assert t.at_capacity() is True


def test_clear_all_empties_everything(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.set_startup_pin("99")
    t.clear_all()
    assert t.ids() == []
    assert t.startup_pin_id() is None


# ---------------------------------------------------------------------------
# Persistence and recovery
# ---------------------------------------------------------------------------

def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "pins.json"
    t1 = PinTracker(path, "chan-1", 5)
    t1.register("1")
    t1.register("2")
    t1.set_startup_pin("99")

    t2 = PinTracker(path, "chan-1", 5)
    assert t2.ids() == ["1", "2"]
    assert t2.startup_pin_id() == "99"


def test_load_ignores_other_channel(tmp_path):
    path = tmp_path / "pins.json"
    PinTracker(path, "chan-1", 5).register("1")
    # A tracker for a different channel must not inherit the old channel's pins.
    other = PinTracker(path, "chan-2", 5)
    assert other.ids() == []


def test_load_recovers_from_corrupt_json(tmp_path):
    path = tmp_path / "pins.json"
    path.write_text("{not valid json", encoding="utf-8")
    t = PinTracker(path, "chan-1", 5)
    assert t.ids() == []
    assert t.startup_pin_id() is None


def test_load_strips_startup_pin_from_rotation_list(tmp_path):
    path = tmp_path / "pins.json"
    path.write_text(
        json.dumps(
            {
                "channel_id": "chan-1",
                "startup_pin_message_id": "99",
                # "99" erroneously also in the rotation list.
                "pinned_message_ids": ["1", "99", "2"],
            }
        ),
        encoding="utf-8",
    )
    t = PinTracker(path, "chan-1", 5)
    assert t.ids() == ["1", "2"]
    assert t.startup_pin_id() == "99"


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------

def test_reconcile_drops_stale_and_merges_new(tmp_path):
    t = _tracker(tmp_path)
    t.register("1")
    t.register("2")
    # Discord reports: "1" still pinned, "3" newly pinned, "2" gone.
    t.reconcile(["1", "3"])
    assert t.ids() == ["1", "3"]


def test_reconcile_drops_startup_pin_when_not_live(tmp_path):
    t = _tracker(tmp_path)
    t.set_startup_pin("99")
    t.reconcile(["1"])  # 99 no longer pinned on Discord
    assert t.startup_pin_id() is None
    assert t.ids() == ["1"]


def test_reconcile_keeps_startup_pin_separate(tmp_path):
    t = _tracker(tmp_path)
    t.set_startup_pin("99")
    t.reconcile(["99", "1"])  # startup pin still live
    assert t.startup_pin_id() == "99"
    # Startup pin stays out of the rotation list.
    assert t.ids() == ["1"]


def test_reconcile_trims_to_max_retain(tmp_path):
    t = _tracker(tmp_path, max_retain=2)
    t.reconcile(["1", "2", "3", "4"])
    # Oldest entries trimmed to satisfy the retention cap.
    assert len(t.ids()) == 2
    assert t.ids() == ["3", "4"]
