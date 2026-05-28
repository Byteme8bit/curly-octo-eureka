"""Tests for the Auditor bot module.

Sandbox-locked shell on Windows means we cannot run pytest from the agent.
Run from a PowerShell prompt the user controls:

    .\\.venv\\Scripts\\python.exe -m pytest tests\\test_auditor.py -v

All HTTP is mocked through ``unittest.mock.patch(... urllib.request.urlopen ...)``;
no real network call ever fires from this suite.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bot.auditor.analyzer import analyze_trades
from bot.auditor.config import AuditorConfig
from bot.auditor.forecaster import forecast_pnl
from bot.auditor.news_client import NewsClient, NewsHeadline
from bot.auditor.proposer import (
    ALLOWED_KNOBS,
    ConfigProposal,
    propose_changes,
)
from bot.auditor.report import (
    DISCORD_MAX_LEN,
    render_discord_summary,
    render_markdown_report,
)
from bot.auditor.runtime_overrides import (
    apply_proposal,
    list_overrides,
    revert_override,
)
from bot.auditor.state import AuditorState
from bot.auditor_service import AuditorService
from bot.local_time import format_pacific, pacific_now
from config import _apply_runtime_overrides


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings_stub(**over) -> SimpleNamespace:
    base = dict(
        min_trade_edge=0.006,
        trade_size_pct=0.10,
        min_net_profit_pct=0.0005,
        idle_reeval_hours=2.0,
        strategy_exploration_ratio=0.25,
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        paper_portfolio_file="paper_portfolio.json",
        state_file=".paper_state.json",
        receipts_dir="receipts",
        log_dir="logs",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _trade(
    strategy: str = "cross_momentum",
    symbol: str = "ETH/USD",
    gain: float = 1.0,
    fee: float = 0.10,
    reason: str = "",
    when: datetime | None = None,
    from_asset: str = "USD",
    to_asset: str = "ETH",
) -> dict:
    when = when or datetime.now(timezone.utc)
    return {
        "time": when.isoformat(),
        "symbol": symbol,
        "side": "buy",
        "type": "usd",
        "from_asset": from_asset,
        "to_asset": to_asset,
        "from_qty": 100.0,
        "to_qty": 0.05,
        "price": 2000.0,
        "size_pct": 0.10,
        "fee_quote": fee,
        "fee_usd": fee,
        "reason": reason,
        "gain_loss": gain,
        "strategy_name": strategy,
    }


def _future_proposal(knob: str = "MIN_TRADE_EDGE", minutes: int = 60) -> ConfigProposal:
    now = pacific_now()
    return ConfigProposal(
        id="abc12345",
        knob=knob,
        current_value=0.006,
        proposed_value=0.0075,
        rationale="test",
        created_at=format_pacific(now),
        expires_at=format_pacific(now + timedelta(minutes=minutes)),
        severity="medium",
    )


def _expired_proposal() -> ConfigProposal:
    return ConfigProposal(
        id="expired1",
        knob="MIN_TRADE_EDGE",
        current_value=0.006,
        proposed_value=0.008,
        rationale="test",
        created_at="2020-01-01 11:00:00 PST",
        expires_at="2020-01-01 12:00:00 PST",
        severity="low",
    )


def _mock_urlopen_factory(payload):
    """Build a callable usable as ``urllib.request.urlopen``.

    ``payload`` is either a dict (JSON-encoded once) or a list of items —
    each item can be a dict (success payload) or an Exception class/instance
    (raised when consumed). The factory cycles through items once.
    """
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = list(payload)
    else:
        items = [payload]

    state = {"i": 0}

    def fake_urlopen(request, timeout=10):  # noqa: ARG001 — signature match
        idx = state["i"]
        state["i"] += 1
        if idx >= len(items):
            raise RuntimeError("urlopen called more times than mocked")
        item = items[idx]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("mocked failure")
        if isinstance(item, (bytes, bytearray)):
            body = bytes(item)
        elif isinstance(item, str):
            body = item.encode("utf-8")
        else:
            body = json.dumps(item).encode("utf-8")
        response = MagicMock()
        response.read.return_value = body
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    return fake_urlopen, state


# ---------------------------------------------------------------------------
# analyzer
# ---------------------------------------------------------------------------


def test_analyze_trades_empty_returns_zero_insights() -> None:
    insights = analyze_trades([], {"USD": 100.0}, _settings_stub())
    assert insights.total_trades == 0
    assert insights.total_pnl == 0.0
    assert insights.net_pnl == 0.0
    assert insights.win_rate == 0.0
    assert insights.by_strategy == []
    assert insights.eth_reserve_status["healthy"] is False  # 0 ETH < 0.25 floor
    assert insights.drawdown_max == 0.0


def test_analyze_trades_single_trade_counts_winner() -> None:
    trade = _trade(gain=5.0, fee=0.5, strategy="cross_momentum")
    insights = analyze_trades([trade], {"ETH": 1.0}, _settings_stub())
    assert insights.total_trades == 1
    assert insights.total_pnl == 5.0
    assert insights.total_fees == 0.5
    assert insights.net_pnl == 4.5
    assert insights.win_rate == 1.0
    assert len(insights.by_strategy) == 1
    perf = insights.by_strategy[0]
    assert perf.strategy == "cross_momentum"
    assert perf.wins == 1
    assert perf.losses == 0
    assert perf.best_trade == 5.0


def test_analyze_trades_mixed_strategies_attributes_pnl() -> None:
    trades = [
        _trade(strategy="cross_momentum", gain=10.0, fee=0.5, symbol="ETH/USD"),
        _trade(strategy="cross_momentum", gain=-3.0, fee=0.4, symbol="ETH/USD"),
        _trade(strategy="stat_arb", gain=2.0, fee=0.2, symbol="SOL/USD"),
        _trade(strategy="stat_arb", gain=4.0, fee=0.3, symbol="SOL/USD"),
        _trade(strategy="stat_arb", gain=-1.0, fee=0.2, symbol="SOL/USD"),
    ]
    insights = analyze_trades(
        trades,
        {"ETH": 1.0, "SOL": 50.0, "USD": 0.0},
        _settings_stub(),
        usd_prices={"ETH": 2000.0, "SOL": 100.0},
    )
    assert insights.total_trades == 5
    cross = next(p for p in insights.by_strategy if p.strategy == "cross_momentum")
    stat = next(p for p in insights.by_strategy if p.strategy == "stat_arb")
    assert cross.total_pnl == 7.0
    assert stat.total_pnl == 5.0
    assert cross.win_rate == 0.5
    assert pytest.approx(stat.win_rate, rel=1e-3) == 2 / 3
    # ETH (2000 USD) vs SOL (5000 USD) -> SOL is over-concentrated above 40%
    assert "SOL" in insights.over_concentrated
    assert "ETH" not in insights.over_concentrated  # ETH never in overconcentrated set


def test_analyze_trades_flags_defensive_circuit_breaker_events() -> None:
    trades = [
        _trade(reason="Circuit breaker emergency liquidation"),
        _trade(reason="Re-evaluation defensive sell"),
        _trade(reason="ordinary momentum"),
    ]
    insights = analyze_trades(trades, {}, _settings_stub())
    assert insights.recent_circuit_breaker_events == 2


# ---------------------------------------------------------------------------
# forecaster
# ---------------------------------------------------------------------------


def test_forecast_under_10_trades_returns_insufficient_band() -> None:
    trades = [_trade(gain=1.0) for _ in range(5)]
    insights = analyze_trades(trades, {}, _settings_stub())
    forecast = forecast_pnl(insights, trades)
    assert len(forecast) == 1
    assert forecast[0].method == "insufficient_data"
    assert forecast[0].confidence == 0.0


def test_forecast_10_to_50_trades_uses_trade_rate_extrapolation() -> None:
    start = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    trades = [
        _trade(gain=2.0 if i % 2 else -1.0, fee=0.2, when=start + timedelta(hours=i))
        for i in range(20)
    ]
    insights = analyze_trades(trades, {}, _settings_stub())
    forecast = forecast_pnl(insights, trades)
    horizons = [b.horizon for b in forecast]
    methods = {b.method for b in forecast}
    assert horizons == ["24h", "7d"]
    assert methods == {"trade_rate_extrapolation"}
    for b in forecast:
        assert b.lower_band <= b.expected_pnl <= b.upper_band


def test_forecast_over_50_trades_uses_bootstrap_and_all_horizons() -> None:
    start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    trades = [
        _trade(gain=1.0 if i % 3 else -0.5, fee=0.1, when=start + timedelta(hours=i))
        for i in range(60)
    ]
    insights = analyze_trades(trades, {}, _settings_stub())
    forecast = forecast_pnl(insights, trades, bootstrap_iterations=100, seed=42)
    horizons = [b.horizon for b in forecast]
    assert horizons == ["24h", "7d", "30d"]
    methods = {b.method for b in forecast}
    assert methods == {"bootstrap"}
    # Bootstrap confidence should monotonically shrink as horizon widens.
    confidences = [b.confidence for b in forecast]
    assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# news client
# ---------------------------------------------------------------------------


_RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{feed}</title>
    <item>
      <title>{title_a}</title>
      <link>https://example.com/{slug_a}</link>
      <pubDate>Wed, 27 May 2026 10:00:00 +0000</pubDate>
      <description>{desc_a}</description>
    </item>
    <item>
      <title>{title_b}</title>
      <link>https://example.com/{slug_b}</link>
      <pubDate>Wed, 27 May 2026 09:30:00 +0000</pubDate>
      <description>{desc_b}</description>
    </item>
  </channel>
</rss>
"""


def _rss_payload(feed: str, *, ticker: str = "ETH") -> str:
    return _RSS_TEMPLATE.format(
        feed=feed,
        title_a=f"{ticker} hits new milestone on {feed}",
        slug_a=f"{feed.lower().replace(' ', '-')}-{ticker.lower()}-milestone",
        desc_a=f"{ticker} rally continues per {feed}.",
        title_b=f"BTC sees volume spike via {feed}",
        slug_b=f"{feed.lower().replace(' ', '-')}-btc-volume",
        desc_b=f"BTC trading volume up on {feed}.",
    )


def _cryptopanic_payload() -> dict:
    return {
        "results": [
            {
                "title": "ETH cracks all-time high",
                "url": "https://example.com/eth-ath",
                "source_url": "",
                "published_at": "2026-05-27T10:00:00Z",
                "source": {"title": "CoinJournal"},
                "currencies": [{"code": "ETH"}],
                "votes": {"positive": 10, "negative": 1},
            },
            {
                "title": "BTC chops sideways",
                "url": "https://example.com/btc-flat",
                "published_at": "2026-05-27T09:30:00Z",
                "source": {"title": "MarketWire"},
                "currencies": [{"code": "BTC"}],
                "votes": {"positive": 2, "negative": 2},
            },
        ]
    }


def _coingecko_payload() -> dict:
    return {
        "data": [
            {
                "title": "Solana ecosystem expands",
                "url": "https://example.com/sol-news",
                "author": "Decrypt",
                "updated_at": "2026-05-27T10:00:00Z",
                "categories": ["SOL"],
                "sentiment": "positive",
            },
        ]
    }


def test_news_client_rss_default_aggregates_feeds() -> None:
    fake_urlopen, state = _mock_urlopen_factory([
        _rss_payload("CoinDesk"),
        _rss_payload("Cointelegraph"),
    ])
    client = NewsClient(
        rss_feeds=[
            ("CoinDesk", "https://coindesk.example/rss"),
            ("Cointelegraph", "https://cointelegraph.example/rss"),
        ],
        urlopen=fake_urlopen,
        max_retries=0,
        backoff_seconds=0,
    )
    headlines = client.fetch_headlines(["ETH", "BTC"], max_items=10)
    assert state["i"] == 2  # both feeds queried
    assert len(headlines) == 4
    sources = {h.source for h in headlines}
    assert sources == {"CoinDesk", "Cointelegraph"}
    assert all(h.sentiment == "unknown" for h in headlines)
    eth_items = [h for h in headlines if "ETH" in h.tickers]
    btc_items = [h for h in headlines if "BTC" in h.tickers]
    assert eth_items and btc_items  # ticker extraction works


def test_news_client_rss_dedupes_repeated_urls_across_feeds() -> None:
    repeat = _RSS_TEMPLATE.format(
        feed="CoinDesk",
        title_a="ETH news", slug_a="eth-news", desc_a="ETH",
        title_b="BTC news", slug_b="btc-news", desc_b="BTC",
    )
    fake_urlopen, _ = _mock_urlopen_factory([repeat, repeat])
    client = NewsClient(
        rss_feeds=[
            ("CoinDesk", "https://coindesk.example/rss"),
            ("Mirror", "https://mirror.example/rss"),
        ],
        urlopen=fake_urlopen,
        max_retries=0,
        backoff_seconds=0,
    )
    headlines = client.fetch_headlines(["ETH"], max_items=10)
    urls = [h.url for h in headlines]
    assert len(urls) == len(set(urls))  # no duplicates


def test_news_client_rss_falls_through_to_coingecko() -> None:
    fake_urlopen, state = _mock_urlopen_factory([
        TimeoutError("rss feed down"),
        _coingecko_payload(),
    ])
    client = NewsClient(
        providers="rss,coingecko",
        rss_feeds=[("CoinDesk", "https://coindesk.example/rss")],
        urlopen=fake_urlopen,
        max_retries=0,
        backoff_seconds=0,
    )
    headlines = client.fetch_headlines(["SOL"], max_items=5)
    assert state["i"] == 2  # tried RSS, then CoinGecko
    assert len(headlines) == 1
    assert headlines[0].sentiment == "positive"
    assert "SOL" in headlines[0].tickers


def test_news_client_cryptopanic_opt_in_still_works() -> None:
    fake_urlopen, state = _mock_urlopen_factory(_cryptopanic_payload())
    client = NewsClient(
        providers="cryptopanic",
        urlopen=fake_urlopen,
        max_retries=0,
        backoff_seconds=0,
    )
    headlines = client.fetch_headlines(["ETH", "BTC"], max_items=10)
    assert len(headlines) == 2
    assert isinstance(headlines[0], NewsHeadline)
    assert headlines[0].sentiment == "positive"
    assert headlines[1].sentiment == "neutral"
    assert state["i"] == 1


def test_news_client_retries_then_succeeds() -> None:
    fake_urlopen, state = _mock_urlopen_factory([
        TimeoutError("first failure"),
        _rss_payload("CoinDesk"),
    ])
    client = NewsClient(
        rss_feeds=[("CoinDesk", "https://coindesk.example/rss")],
        urlopen=fake_urlopen,
        max_retries=2,
        backoff_seconds=0.5,
    )
    with patch("bot.auditor.news_client.time.sleep") as sleep_mock:
        headlines = client.fetch_headlines(["ETH"], max_items=5)
    assert len(headlines) == 2
    assert state["i"] == 2
    assert sleep_mock.called  # at least one backoff between attempts


def test_news_client_total_failure_returns_empty_without_raising() -> None:
    fake_urlopen, _ = _mock_urlopen_factory([
        TimeoutError("p1"),
        TimeoutError("p2"),
        TimeoutError("p3"),
        TimeoutError("p4"),
        TimeoutError("p5"),
        TimeoutError("p6"),
    ])
    client = NewsClient(
        providers="rss",
        rss_feeds=[("CoinDesk", "https://x.example/rss")],
        urlopen=fake_urlopen,
        max_retries=2,
        backoff_seconds=0,
    )
    with patch("bot.auditor.news_client.time.sleep"):
        result = client.fetch_headlines(["ETH"], max_items=5)
    assert result == []


def test_news_client_cache_hit_avoids_second_network_call() -> None:
    fake_urlopen, state = _mock_urlopen_factory([_rss_payload("CoinDesk")])
    client = NewsClient(
        rss_feeds=[("CoinDesk", "https://coindesk.example/rss")],
        urlopen=fake_urlopen,
        max_retries=0,
        backoff_seconds=0,
        cache_ttl_seconds=600,
    )
    a = client.fetch_headlines(["ETH"], max_items=5)
    b = client.fetch_headlines(["ETH"], max_items=5)
    assert a == b
    assert state["i"] == 1  # second call served from cache


def test_parse_rss_feed_env_handles_blanks_and_pairs() -> None:
    from bot.auditor.news_client import DEFAULT_RSS_FEEDS, parse_rss_feed_env

    assert parse_rss_feed_env("") == DEFAULT_RSS_FEEDS
    parsed = parse_rss_feed_env("CoinDesk|https://a/rss, ,Cointelegraph|https://b/rss")
    assert parsed == (
        ("CoinDesk", "https://a/rss"),
        ("Cointelegraph", "https://b/rss"),
    )


# ---------------------------------------------------------------------------
# proposer
# ---------------------------------------------------------------------------


def test_proposer_high_fee_drag_suggests_tighter_edge() -> None:
    trades = [_trade(gain=0.5, fee=1.0) for _ in range(20)]
    insights = analyze_trades(trades, {}, _settings_stub())
    proposals = propose_changes(insights, [], _settings_stub(), ttl_minutes=30)
    knobs = {p.knob for p in proposals}
    assert "MIN_TRADE_EDGE" in knobs
    assert "MIN_NET_PROFIT_PCT" in knobs


def test_proposer_low_winrate_shrinks_trade_size() -> None:
    trades = []
    for i in range(40):
        gain = 1.0 if i % 5 == 0 else -1.0  # 20% win rate -> well under 0.45
        trades.append(_trade(gain=gain, fee=0.05))
    insights = analyze_trades(trades, {}, _settings_stub())
    proposals = propose_changes(insights, [], _settings_stub(), ttl_minutes=30)
    size_props = [p for p in proposals if p.knob == "TRADE_SIZE_PCT"]
    assert size_props, "low win rate should propose a TRADE_SIZE_PCT cut"
    assert size_props[0].proposed_value < size_props[0].current_value


def test_proposer_empty_history_returns_no_proposals() -> None:
    insights = analyze_trades([], {}, _settings_stub())
    assert propose_changes(insights, [], _settings_stub()) == []


# ---------------------------------------------------------------------------
# runtime_overrides
# ---------------------------------------------------------------------------


def test_runtime_overrides_apply_writes_json(tmp_path: Path) -> None:
    overrides = tmp_path / "runtime_overrides.json"
    apply_proposal(_future_proposal("MIN_TRADE_EDGE"), overrides)
    data = json.loads(overrides.read_text(encoding="utf-8"))
    assert data == {"MIN_TRADE_EDGE": 0.0075}


def test_runtime_overrides_revert_removes_key(tmp_path: Path) -> None:
    overrides = tmp_path / "runtime_overrides.json"
    overrides.write_text(json.dumps({"MIN_TRADE_EDGE": 0.01, "TRADE_SIZE_PCT": 0.08}), encoding="utf-8")
    assert revert_override("MIN_TRADE_EDGE", overrides) is True
    remaining = list_overrides(overrides)
    assert "MIN_TRADE_EDGE" not in remaining
    assert remaining["TRADE_SIZE_PCT"] == pytest.approx(0.08)


def test_runtime_overrides_rejects_disallowed_knob(tmp_path: Path) -> None:
    overrides = tmp_path / "runtime_overrides.json"
    bad = ConfigProposal(
        id="x", knob="MIN_ETH_RESERVE", current_value=0.25, proposed_value=0.1,
        rationale="", created_at="", expires_at="", severity="low",
    )
    with pytest.raises(ValueError):
        apply_proposal(bad, overrides)
    assert not overrides.exists()


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def test_state_add_and_consume_proposal_round_trip() -> None:
    state = AuditorState()
    proposal = _future_proposal()
    state.add_proposal(proposal)
    assert state.get_proposal(proposal.id) is proposal
    consumed = state.consume_proposal(proposal.id)
    assert consumed is proposal
    assert state.get_proposal(proposal.id) is None
    assert state.consume_proposal(proposal.id) is None


def test_state_prune_expired_removes_old_proposals() -> None:
    state = AuditorState()
    state.add_proposal(_expired_proposal())
    state.add_proposal(_future_proposal("TRADE_SIZE_PCT"))
    removed = state.prune_expired()
    assert removed == 1
    assert len(state.pending_proposals) == 1
    remaining = next(iter(state.pending_proposals.values()))
    assert remaining.knob == "TRADE_SIZE_PCT"


def test_state_save_and_load_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / ".auditor_state.json"
    state = AuditorState()
    state.add_proposal(_future_proposal())
    state.mark_scheduled_run()
    state.save(state_file)
    restored = AuditorState.load(state_file)
    assert list(restored.pending_proposals) == list(state.pending_proposals)
    assert restored.last_scheduled_run_at == state.last_scheduled_run_at


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_render_markdown_report_contains_all_sections() -> None:
    insights = analyze_trades([_trade(gain=1.0)], {"ETH": 1.0}, _settings_stub())
    forecast = forecast_pnl(insights, [_trade(gain=1.0)])
    headlines = [
        NewsHeadline(title="ETH up", url="u", published_at="2026-05-27", source="src", tickers=["ETH"], sentiment="positive"),
    ]
    proposals = [_future_proposal()]
    md = render_markdown_report(insights, forecast, headlines, proposals, settings=_settings_stub())
    for header in [
        "# Auditor report",
        "## Headline numbers",
        "## Strategy attribution",
        "## Concentration & ETH reserve",
        "## Forecast",
        "## News headlines",
        "## Proposed config changes",
        "## References",
    ]:
        assert header in md, f"missing section: {header}"
    assert "Auditor -confirm" in md  # confirm syntax surfaced


def test_render_discord_summary_stays_under_1900_chars() -> None:
    trades = [_trade(gain=1.0 if i % 2 else -1.0) for i in range(60)]
    insights = analyze_trades(trades, {"ETH": 1.0}, _settings_stub())
    forecast = forecast_pnl(insights, trades, bootstrap_iterations=50, seed=1)
    headlines = [
        NewsHeadline(
            title="Headline " * 20,  # very long title
            url="u",
            published_at="2026-05-27",
            source="src",
            tickers=["ETH"],
            sentiment="neutral",
        )
        for _ in range(10)
    ]
    proposals = [_future_proposal(k) for k in ALLOWED_KNOBS]
    summary = render_discord_summary(insights, forecast, headlines, proposals)
    assert len(summary) <= DISCORD_MAX_LEN


# ---------------------------------------------------------------------------
# AuditorService
# ---------------------------------------------------------------------------


def _make_service(
    tmp_path: Path,
    *,
    news_enabled: bool = False,
    trades: list[dict] | None = None,
    autoapply_enabled: bool = False,
    autoapply_window_start_hour: int = 1,
    autoapply_window_end_hour: int = 7,
    autoapply_min_severity: str = "high",
    autoapply_max_per_night: int = 1,
    autoapply_restart_enabled: bool = True,
    clock: object | None = None,
    request_restart: object | None = None,
    discord: object | None = None,
    broker: object | None = None,
) -> AuditorService:
    state_file = tmp_path / ".auditor_state.json"
    reports_dir = tmp_path / "reports"
    cfg = AuditorConfig(
        enabled=True,
        daily_run_hour_pacific=8,
        trade_count_trigger=20,
        pnl_pct_trigger=0.05,
        news_enabled=news_enabled,
        news_provider="rss",
        cryptopanic_api_key="",
        rss_feeds="",
        news_max_items=5,
        proposals_ttl_minutes=60,
        reports_dir=reports_dir,
        state_file=state_file,
        autoapply_enabled=autoapply_enabled,
        autoapply_window_start_hour=autoapply_window_start_hour,
        autoapply_window_end_hour=autoapply_window_end_hour,
        autoapply_min_severity=autoapply_min_severity,
        autoapply_max_per_night=autoapply_max_per_night,
        autoapply_restart_enabled=autoapply_restart_enabled,
    )
    if broker is None:
        broker = SimpleNamespace(
            state=SimpleNamespace(
                trades=list(trades or []),
                balances={"ETH": 1.0, "USD": 100.0},
            ),
            risk=SimpleNamespace(
                peak_portfolio=2000.0,
                state=SimpleNamespace(paused_until=None, hibernate_alert_sent=False),
            ),
        )
    kwargs = dict(
        broker=broker,
        discord=discord,
        overrides_file=tmp_path / "runtime_overrides.json",
    )
    if clock is not None:
        kwargs["clock"] = clock
    if request_restart is not None:
        kwargs["request_restart"] = request_restart
    return AuditorService(_settings_stub(), cfg, **kwargs)


def test_auditor_service_confirm_happy_path_writes_override(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    proposal = _future_proposal("MIN_TRADE_EDGE")
    service.state.add_proposal(proposal)
    msg = service.confirm_proposal(proposal.id)
    assert "Applied" in msg
    # Explicit restart warning is required so users don't think `stop`/`start` Discord
    # commands reload settings — they don't.
    assert "full process restart" in msg.lower()
    assert "stop" in msg.lower() and "start" in msg.lower()
    data = json.loads((tmp_path / "runtime_overrides.json").read_text(encoding="utf-8"))
    assert data["MIN_TRADE_EDGE"] == pytest.approx(proposal.proposed_value)
    assert proposal.id not in service.state.pending_proposals


def test_auditor_service_confirm_expired_proposal_rejects(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    expired = _expired_proposal()
    service.state.add_proposal(expired)
    msg = service.confirm_proposal(expired.id)
    assert "expired" in msg.lower()
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_auditor_service_run_audit_creates_markdown_in_per_day_subfolder(tmp_path: Path) -> None:
    trades = [_trade(gain=1.0 if i % 2 else -0.5, fee=0.05) for i in range(15)]
    service = _make_service(tmp_path, news_enabled=False, trades=trades)
    report = service.run_audit(trigger="manual")
    assert report.markdown_path is not None
    assert report.markdown_path.exists()
    # Per-day subdirectory pattern: reports/YYYY-MM-DD/audit-HHMMSS.md
    assert report.markdown_path.parent.parent.name == "reports"
    body = report.markdown_path.read_text(encoding="utf-8")
    assert "# Auditor report" in body


def test_auditor_service_revert_returns_helpful_message_when_missing(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert "no active override" in service.revert("MIN_TRADE_EDGE").lower()
    assert "not an auditor-managed knob" in service.revert("FEE_RATE").lower()


# ---------------------------------------------------------------------------
# config._apply_runtime_overrides
# ---------------------------------------------------------------------------


def test_apply_runtime_overrides_overlays_allowed_knobs_only(tmp_path: Path) -> None:
    overrides = tmp_path / "runtime_overrides.json"
    overrides.write_text(
        json.dumps({
            "MIN_TRADE_EDGE": 0.012,
            "TRADE_SIZE_PCT": 0.07,
            "FEE_RATE": 0.99,  # NOT allowed — must be ignored
        }),
        encoding="utf-8",
    )
    settings_dict = {
        "min_trade_edge": 0.006,
        "trade_size_pct": 0.10,
        "fee_rate": 0.0026,
    }
    applied = _apply_runtime_overrides(settings_dict, overrides_file=overrides)
    assert settings_dict["min_trade_edge"] == pytest.approx(0.012)
    assert settings_dict["trade_size_pct"] == pytest.approx(0.07)
    assert settings_dict["fee_rate"] == pytest.approx(0.0026)  # untouched
    assert "MIN_TRADE_EDGE=0.012" in applied
    assert "TRADE_SIZE_PCT=0.07" in applied
    assert not any("FEE_RATE" in a for a in applied)


def test_apply_runtime_overrides_missing_file_is_a_no_op(tmp_path: Path) -> None:
    settings_dict = {"min_trade_edge": 0.006}
    applied = _apply_runtime_overrides(settings_dict, overrides_file=tmp_path / "missing.json")
    assert applied == []
    assert settings_dict["min_trade_edge"] == pytest.approx(0.006)


# ---------------------------------------------------------------------------
# discord parser — auditor extensions
# ---------------------------------------------------------------------------


def test_parser_recognizes_auditor_prefix_with_args() -> None:
    from bot.discord_bot import parse_command

    parsed = parse_command("Auditor -confirm abc123")
    assert parsed is not None
    assert parsed.action == "auditor-confirm abc123"
    assert parsed.deprecated is False


def test_parser_auditor_help_no_args() -> None:
    from bot.discord_bot import parse_command

    parsed = parse_command("Au -help")
    assert parsed is not None
    assert parsed.action == "auditor-help"


def test_parser_rejects_args_on_tradebot_prefix() -> None:
    from bot.discord_bot import parse_command

    assert parse_command("TradeBot -start now") is None


# ---------------------------------------------------------------------------
# Sleep-window auto-apply
# ---------------------------------------------------------------------------


def _high_severity_proposal(knob: str = "MIN_TRADE_EDGE") -> "ConfigProposal":  # type: ignore[name-defined]
    from bot.auditor.proposer import ConfigProposal
    from bot.local_time import format_pacific, pacific_now
    from datetime import timedelta as _td

    now = pacific_now()
    return ConfigProposal(
        id="autoapply-high",
        knob=knob,
        current_value=0.006,
        proposed_value=0.0069,
        rationale="Forecast central tendency negative across horizons",
        created_at=format_pacific(now),
        expires_at=format_pacific(now + _td(minutes=60)),
        severity="high",
    )


def _low_severity_proposal(knob: str = "MIN_TRADE_EDGE") -> "ConfigProposal":  # type: ignore[name-defined]
    from bot.auditor.proposer import ConfigProposal
    from bot.local_time import format_pacific, pacific_now
    from datetime import timedelta as _td

    now = pacific_now()
    return ConfigProposal(
        id="autoapply-low",
        knob=knob,
        current_value=0.006,
        proposed_value=0.0061,
        rationale="Marginal tightening",
        created_at=format_pacific(now),
        expires_at=format_pacific(now + _td(minutes=60)),
        severity="low",
    )


def _pacific_clock(hour: int):
    """Build a clock callable returning a fixed Pacific datetime at ``hour``."""
    from bot.local_time import PACIFIC
    from datetime import datetime as _dt

    fixed = _dt(2026, 5, 27, hour, 0, 0, tzinfo=PACIFIC)

    def _clock():
        return fixed

    return _clock, fixed


def test_autoapply_disabled_by_default_never_applies(tmp_path: Path) -> None:
    clock, _ = _pacific_clock(3)  # 3am — inside default window
    service = _make_service(
        tmp_path,
        autoapply_enabled=False,
        clock=clock,
    )
    service._maybe_auto_apply([_high_severity_proposal()])
    assert service.state.last_auto_apply_at is None
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_autoapply_applies_inside_window_with_high_severity(tmp_path: Path) -> None:
    clock, fixed = _pacific_clock(3)
    restart_calls: list[str] = []
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        clock=clock,
        request_restart=lambda reason: restart_calls.append(reason),
    )
    proposal = _high_severity_proposal()
    service._maybe_auto_apply([proposal])
    data = json.loads((tmp_path / "runtime_overrides.json").read_text(encoding="utf-8"))
    assert data["MIN_TRADE_EDGE"] == pytest.approx(proposal.proposed_value)
    assert service.state.last_auto_apply_knob == "MIN_TRADE_EDGE"
    assert service.state.last_auto_apply_night_key == fixed.strftime("%Y-%m-%d")
    assert service.state.auto_applies_this_night == 1
    assert len(restart_calls) == 1
    assert "MIN_TRADE_EDGE" in restart_calls[0]


def test_autoapply_skipped_outside_window(tmp_path: Path) -> None:
    clock, _ = _pacific_clock(14)  # 2pm — well outside 1-7am window
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        clock=clock,
    )
    service._maybe_auto_apply([_high_severity_proposal()])
    assert service.state.last_auto_apply_at is None
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_autoapply_skips_low_severity(tmp_path: Path) -> None:
    clock, _ = _pacific_clock(3)
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        clock=clock,
    )
    service._maybe_auto_apply([_low_severity_proposal()])
    assert service.state.last_auto_apply_at is None
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_autoapply_enforces_per_night_cap(tmp_path: Path) -> None:
    clock, fixed = _pacific_clock(3)
    night_key = fixed.strftime("%Y-%m-%d")
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        autoapply_max_per_night=1,
        clock=clock,
    )
    # Pre-seed state as if we already auto-applied earlier in this same night.
    service.state.last_auto_apply_night_key = night_key
    service.state.auto_applies_this_night = 1
    service.state.last_auto_apply_knob = "MIN_TRADE_EDGE"
    service._maybe_auto_apply([_high_severity_proposal(knob="TRADE_SIZE_PCT")])
    assert service.state.last_auto_apply_knob == "MIN_TRADE_EDGE"  # unchanged
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_autoapply_refuses_when_broker_paused(tmp_path: Path) -> None:
    clock, _ = _pacific_clock(3)
    paused_broker = SimpleNamespace(
        state=SimpleNamespace(trades=[], balances={"ETH": 1.0}),
        risk=SimpleNamespace(
            peak_portfolio=2000.0,
            state=SimpleNamespace(paused_until=1_700_000_000.0, hibernate_alert_sent=True),
        ),
    )
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        clock=clock,
        broker=paused_broker,
    )
    service._maybe_auto_apply([_high_severity_proposal()])
    assert service.state.last_auto_apply_at is None
    assert not (tmp_path / "runtime_overrides.json").exists()


def test_autoapply_state_round_trips_through_disk(tmp_path: Path) -> None:
    clock, fixed = _pacific_clock(3)
    service = _make_service(tmp_path, autoapply_enabled=True, clock=clock)
    service._maybe_auto_apply([_high_severity_proposal()])
    # Force reload from disk.
    from bot.auditor.state import AuditorState
    reloaded = AuditorState.load(service.config.state_file)
    assert reloaded.last_auto_apply_knob == "MIN_TRADE_EDGE"
    assert reloaded.last_auto_apply_value == pytest.approx(0.0069)
    assert reloaded.last_auto_apply_night_key == fixed.strftime("%Y-%m-%d")
    assert reloaded.auto_applies_this_night == 1


def test_autoapply_restart_disabled_still_applies_but_no_restart(tmp_path: Path) -> None:
    clock, _ = _pacific_clock(3)
    restart_calls: list[str] = []
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        autoapply_restart_enabled=False,
        clock=clock,
        request_restart=lambda reason: restart_calls.append(reason),
    )
    service._maybe_auto_apply([_high_severity_proposal()])
    assert (tmp_path / "runtime_overrides.json").exists()
    assert restart_calls == []  # no restart requested when disabled


def test_inside_sleep_window_handles_cross_midnight(tmp_path: Path) -> None:
    # Window 23:00 - 07:00 (cross-midnight). 02:00 should be inside, anchored to
    # *yesterday's* date as the night key.
    clock, fixed_2am = _pacific_clock(2)
    service = _make_service(
        tmp_path,
        autoapply_enabled=True,
        autoapply_window_start_hour=23,
        autoapply_window_end_hour=7,
        clock=clock,
    )
    inside, night_key = service._inside_sleep_window(fixed_2am)
    assert inside is True
    yesterday = (fixed_2am - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
    assert night_key == yesterday
    # 22:00 should still be OUTSIDE this window (just before start).
    from datetime import datetime as _dt
    from bot.local_time import PACIFIC
    pm_10 = _dt(2026, 5, 27, 22, 0, 0, tzinfo=PACIFIC)
    inside_2, _ = service._inside_sleep_window(pm_10)
    assert inside_2 is False
