"""Tests for bot.fee_engine.FeeEngine — verifies the 3-tier fallback chain.

Priority: personalised (auth) -> public market metadata -> env default.
"""

from __future__ import annotations

import ccxt
import pytest

from bot.fee_engine import FeeEngine


class _FakeExchange:
    """Minimal ccxt-shaped stub. Pass kwargs to control which calls succeed."""

    def __init__(
        self,
        *,
        personalised_fees=None,
        personalised_raises: Exception | None = None,
        markets=None,
        markets_raises: Exception | None = None,
    ):
        self._personalised_fees = personalised_fees
        self._personalised_raises = personalised_raises
        self.markets = markets
        self._markets_raises = markets_raises
        self.fetch_calls = 0
        self.load_markets_calls = 0

    def fetch_trading_fees(self):
        self.fetch_calls += 1
        if self._personalised_raises is not None:
            raise self._personalised_raises
        return self._personalised_fees or {}

    def load_markets(self):
        self.load_markets_calls += 1
        if self._markets_raises is not None:
            raise self._markets_raises
        return self.markets or {}


# ---------------------------------------------------------------------------
# Tier 1 — personalised fees succeed
# ---------------------------------------------------------------------------


def test_personalised_fees_used_when_available() -> None:
    ex = _FakeExchange(
        personalised_fees={
            "ETH/USD": {"taker": 0.0016, "maker": 0.0010},
            "BTC/USD": {"taker": 0.0014, "maker": 0.0008},
        },
    )
    engine = FeeEngine(ex, default_taker=0.0026)
    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0016)
    assert engine.taker_fee("BTC/USD") == pytest.approx(0.0014)
    # Public schedule must NOT be consulted when personalised worked.
    assert ex.load_markets_calls == 0


# ---------------------------------------------------------------------------
# Tier 2 — falls back to public market metadata
# ---------------------------------------------------------------------------


def test_falls_back_to_public_schedule_on_auth_error() -> None:
    """No API keys means AuthenticationError; we must fall through to public."""
    ex = _FakeExchange(
        personalised_raises=ccxt.AuthenticationError("EAPI:Invalid key"),
        markets={
            "ETH/USD": {"taker": 0.0026, "maker": 0.0016},
            "SOL/USD": {"taker": 0.0026, "maker": 0.0016},
        },
    )
    engine = FeeEngine(ex, default_taker=0.0099)  # obviously-wrong sentinel
    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0026)
    assert engine.taker_fee("SOL/USD") == pytest.approx(0.0026)
    # Sentinel default must NOT be returned for pairs found in public schedule.
    assert engine.taker_fee("ETH/USD") != pytest.approx(0.0099)


def test_falls_back_to_public_schedule_on_permission_denied() -> None:
    ex = _FakeExchange(
        personalised_raises=ccxt.PermissionDenied("read-only key"),
        markets={"ETH/USD": {"taker": 0.0026}},
    )
    engine = FeeEngine(ex, default_taker=0.0099)
    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0026)


def test_falls_back_to_public_schedule_on_not_supported(caplog) -> None:
    """ccxt raises NotSupported for kraken.fetchTradingFees() — must be silent
    about the failure but report which source ultimately won."""
    ex = _FakeExchange(
        personalised_raises=ccxt.NotSupported(
            "kraken fetchTradingFees() is not supported yet"
        ),
        markets={"ETH/USD": {"taker": 0.0026}},
    )
    engine = FeeEngine(ex, default_taker=0.0099)
    with caplog.at_level("WARNING"):
        assert engine.taker_fee("ETH/USD") == pytest.approx(0.0026)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    # NotSupported itself shouldn't warn, BUT we want a single visible
    # "Fee source: PUBLIC ..." line so the user can see which tier won.
    messages = [r.message for r in warnings]
    assert not any("Personalised fee fetch failed" in m for m in messages), (
        f"NotSupported should not produce 'Personalised fee fetch failed' warning: {messages}"
    )
    assert any("Fee source: PUBLIC" in m for m in messages), (
        f"Expected visible 'Fee source: PUBLIC' message, got: {messages}"
    )


def test_fee_source_log_includes_sample_pair_rates(caplog) -> None:
    """The single visible startup line should include sample taker rates so the
    user can sanity-check the loaded values at a glance."""
    ex = _FakeExchange(
        personalised_raises=ccxt.NotSupported("not yet"),
        markets={
            "ETH/USD": {"taker": 0.0026},
            "BTC/USD": {"taker": 0.0026},
            "SOL/USD": {"taker": 0.0030},
        },
    )
    engine = FeeEngine(ex, default_taker=0.0099)
    with caplog.at_level("WARNING"):
        engine.taker_fee("ETH/USD")
    summary = [r.message for r in caplog.records if "Fee source" in r.message]
    assert summary, "Expected a 'Fee source' WARNING line"
    line = summary[0]
    assert "ETH/USD=0.26%" in line
    assert "BTC/USD=0.26%" in line
    assert "SOL/USD=0.30%" in line


# ---------------------------------------------------------------------------
# Tier 3 — env default is the last resort
# ---------------------------------------------------------------------------


def test_unknown_pair_uses_env_default() -> None:
    ex = _FakeExchange(
        personalised_raises=ccxt.AuthenticationError("no key"),
        markets={"ETH/USD": {"taker": 0.0026}},
    )
    engine = FeeEngine(ex, default_taker=0.0026)
    # BTC/USD not in markets -> default
    assert engine.taker_fee("BTC/USD") == pytest.approx(0.0026)


def test_env_default_when_both_personalised_and_public_fail() -> None:
    ex = _FakeExchange(
        personalised_raises=ccxt.AuthenticationError("no key"),
        markets_raises=ccxt.NetworkError("kraken down"),
    )
    engine = FeeEngine(ex, default_taker=0.0026)
    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0026)
    assert engine.taker_fee("BTC/USD") == pytest.approx(0.0026)


def test_fee_schedule_retries_after_transient_public_failure() -> None:
    ex = _FakeExchange(
        personalised_raises=ccxt.AuthenticationError("no key"),
        markets_raises=ccxt.NetworkError("kraken down"),
    )
    engine = FeeEngine(ex, default_taker=0.0010, schedule_retry_sec=0)

    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0010)

    ex._markets_raises = None
    ex.markets = {"ETH/USD": {"taker": 0.0040}}

    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0040)


# ---------------------------------------------------------------------------
# Caching + compounded cost
# ---------------------------------------------------------------------------


def test_load_schedule_runs_only_once() -> None:
    ex = _FakeExchange(
        personalised_fees={"ETH/USD": {"taker": 0.0016}},
    )
    engine = FeeEngine(ex, default_taker=0.0026)
    for _ in range(10):
        engine.taker_fee("ETH/USD")
    # _load_schedule should be a one-shot, not per-call.
    assert ex.fetch_calls == 1


def test_force_static_ignores_live_schedule() -> None:
    """FEE_FORCE_STATIC=1 must use the env default for every pair and never
    consult the exchange — this is the 'roll back the fee bump' lever."""
    ex = _FakeExchange(
        personalised_fees={"ETH/USD": {"taker": 0.0040}},
        markets={"ETH/USD": {"taker": 0.0040}},
    )
    engine = FeeEngine(ex, default_taker=0.0026, force_static=True)
    assert engine.taker_fee("ETH/USD") == pytest.approx(0.0026)
    assert engine.taker_fee("BTC/USD") == pytest.approx(0.0026)
    assert ex.fetch_calls == 0
    assert ex.load_markets_calls == 0


def test_force_static_compounded_cost_uses_default() -> None:
    ex = _FakeExchange(markets={"ETH/BTC": {"taker": 0.0040}})
    engine = FeeEngine(ex, default_taker=0.0026, force_static=True)
    cost = engine.compounded_taker_cost(("ETH/BTC", "BTC/ETH"))
    # 1 - (1 - 0.0026)^2 using the static default, not the 0.0040 live rate.
    assert cost == pytest.approx(0.00519324, abs=1e-7)


def test_compounded_taker_cost_across_three_hops() -> None:
    ex = _FakeExchange(
        personalised_fees={
            "ETH/BTC": {"taker": 0.0026},
            "BTC/AAVE": {"taker": 0.0026},
            "AAVE/ETH": {"taker": 0.0026},
        },
    )
    engine = FeeEngine(ex, default_taker=0.0026)
    cost = engine.compounded_taker_cost(("ETH/BTC", "BTC/AAVE", "AAVE/ETH"))
    # 1 - (1 - 0.0026)^3 ≈ 0.00777976
    assert cost == pytest.approx(0.00777976, abs=1e-7)
