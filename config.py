import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
RUNTIME_OVERRIDES_FILE = ROOT / "runtime_overrides.json"

logger = logging.getLogger(__name__)

# Knobs the Auditor is allowed to override at runtime.
# Map env-var name -> Settings attribute name.
RUNTIME_OVERRIDE_KNOBS: dict[str, str] = {
    "MIN_TRADE_EDGE": "min_trade_edge",
    "TRADE_SIZE_PCT": "trade_size_pct",
    "MIN_NET_PROFIT_PCT": "min_net_profit_pct",
    "IDLE_REEVAL_HOURS": "idle_reeval_hours",
    "STRATEGY_EXPLORATION_RATIO": "strategy_exploration_ratio",
}

WATCH_ASSETS: tuple[str, ...] = (
    "BTC", "ETH", "SOL", "ADA", "XRP", "DOT", "LINK", "AVAX",
    "ATOM", "LTC", "DOGE", "BNB", "UNI", "AAVE", "ARB", "OP", "POL",
)

# USD pairs used for momentum scoring and display
SYMBOL_ASSETS: dict[str, str] = {f"{asset}/USD": asset for asset in WATCH_ASSETS}
ASSET_USD_SYMBOLS: dict[str, str] = {asset: f"{asset}/USD" for asset in WATCH_ASSETS}
# Legacy alias
ASSET_SYMBOLS = ASSET_USD_SYMBOLS

DEFAULT_SYMBOLS = ",".join(SYMBOL_ASSETS.keys())
DEFAULT_CORE_ASSETS = "ADA,ETH,BTC"
DEFAULT_PREFERRED_START_ASSETS = "ADA"
DEFAULT_STRATEGIES = "cross_momentum,triangular_arbitrage,stat_arb"
DEFAULT_SAFE_ASSETS = "USD,ETH,BTC"
DEFAULT_STAT_ARB_PAIRS = "ETH/BTC,SOL/ETH,LINK/ETH,AVAX/ETH"
DEFAULT_MOMENTUM_TIMEFRAMES = "15m,1h"
DEFAULT_EQUITY_WATCHLIST = "AAPLx,TSLAx,SPYx"
DEFAULT_MAX_EQUITY_ALLOCATION_PCT = "0.15"


@dataclass(frozen=True)
class Settings:
    watch_assets: tuple[str, ...]
    usd_symbols: tuple[str, ...]
    core_assets: tuple[str, ...]
    preferred_start_assets: tuple[str, ...]
    initial_balances: dict[str, float]
    poll_interval: int
    fee_rate: float
    candle_timeframe: str
    candle_limit: int
    ema_fast: int
    ema_slow: int
    momentum_sell: float
    trade_size_pct: float
    expansion_size_pct: float
    min_usd_trade: float
    diversify_bonus: float
    dust_usd: float
    drawdown_hibernate_pct: float
    hibernate_hours: float
    trade_cooldown_seconds: int
    max_trades_per_hour: int
    min_trade_edge: float
    leader_stable_seconds: int
    fee_safety_multiplier: float
    reset_paper_state: bool
    alerts_enabled: bool
    alert_discord_webhook: str
    discord_enabled: bool
    discord_webhook: str
    discord_bot_token: str
    discord_channel_id: str
    discord_allowed_user_ids: tuple[str, ...]
    discord_heartbeat_minutes: int
    discord_quiet_mode: bool
    discord_whale_skip_to_discord: bool
    discord_trade_summary_interval_minutes: int
    discord_major_move_pct: float
    discord_major_move_cooldown_minutes: int
    trade_verify_discord_tag: bool
    trade_verify_skip_kraken: bool
    whale_follow_skip_log_file: Path
    discord_error_cooldown_minutes: int
    discord_error_pin_count: int
    discord_error_pin_window_minutes: int
    discord_pin_enabled: bool
    discord_pin_pnl_pct: float
    discord_pin_trade_usd: float
    discord_max_pins_retain: int
    discord_chat_log_enabled: bool
    discord_chat_log_file: str
    alert_telegram_bot_token: str
    alert_telegram_chat_id: str
    alert_smtp_host: str
    alert_smtp_port: int
    alert_smtp_user: str
    alert_smtp_password: str
    alert_email_from: str
    alert_email_to: str
    alert_twilio_sid: str
    alert_twilio_token: str
    alert_twilio_from: str
    alert_sms_to: str
    api_key: str
    api_secret: str
    state_file: Path
    paper_portfolio_file: Path
    log_dir: Path
    receipts_dir: Path
    log_rotate_hours: int
    strategies: tuple[str, ...]
    slippage_buffer_pct: float
    min_net_profit_pct: float
    safe_assets: tuple[str, ...]
    stat_arb_zscore_threshold: float
    stat_arb_lookback: int
    stat_arb_pairs: tuple[tuple[str, str], ...]
    momentum_timeframes: tuple[str, ...]
    circuit_breaker_enabled: bool
    diagnostic_dir: Path
    idle_reeval_hours: float
    idle_reeval_max_attempts: int
    idle_probe_force_minutes: float
    idle_probe_size_pct: float
    fee_force_static: bool
    min_eth_reserve: float
    max_alt_allocation_pct: float
    strategy_growth_window_hours: float
    strategy_min_growth_pct: float
    strategy_strong_growth_pct: float
    strategy_switch_edge_margin: float
    strategy_exploration_ratio: float
    kraken_request_timeout_ms: int
    kraken_max_retries: int
    kraken_retry_backoff_sec: float
    auditor_enabled: bool
    auditor_daily_run_hour_pacific: int
    auditor_trade_count_trigger: int
    auditor_pnl_pct_trigger: float
    auditor_news_enabled: bool
    auditor_news_provider: str
    auditor_cryptopanic_api_key: str
    auditor_rss_feeds: str
    auditor_news_max_items: int
    auditor_proposals_ttl_minutes: int
    auditor_reports_dir: Path
    auditor_state_file: Path
    auditor_autoapply_enabled: bool
    auditor_autoapply_window_start_hour: int
    auditor_autoapply_window_end_hour: int
    auditor_autoapply_min_severity: str
    auditor_autoapply_max_per_night: int
    auditor_autoapply_restart_enabled: bool
    auditor_confirm_restart_enabled: bool
    auditor_chat_enabled: bool
    auditor_chat_backend: str
    auditor_chat_model: str
    auditor_chat_api_key: str
    auditor_chat_max_turns: int
    auditor_chat_max_tokens: int
    auditor_chat_temperature: float
    auditor_chat_tool_iterations: int
    auditor_chat_tool_result_max_chars: int
    auditor_discord_quiet: bool
    whale_watch_enabled: bool
    whale_watch_min_usd: float
    whale_watch_spike_min_usd: float
    whale_watch_assets: tuple[str, ...]
    whale_watch_poll_seconds: int
    whale_watch_volume_spike_ratio: float
    whale_watch_max_events: int
    whale_watch_state_file: Path
    whale_watch_discord_alerts: bool
    whale_watch_log_file: Path
    whale_follow_enabled: bool
    whale_follow_size_pct: float
    whale_follow_cooldown_sec: int
    whale_follow_max_per_hour: int
    whale_follow_min_net_profit: float
    goal_evolution_enabled: bool
    goal_state_file: Path
    goal_milestones_usd: tuple[float, ...]
    goal_tier0_strategies: tuple[str, ...]
    goal_tier1_strategies: tuple[str, ...]
    goal_tier2_strategies: tuple[str, ...]
    goal_tier3_strategies: tuple[str, ...]
    goal_tier2_exploration_ratio: float | None
    goal_tier3_exploration_ratio: float | None
    goal_tier3_whale_follow_size_mult: float
    crash_hold_enabled: bool
    crash_hold_drawdown_pct: float
    crash_hold_session_drawdown_pct: float
    crash_hold_recovery_drawdown_pct: float
    crash_hold_momentum_threshold: float
    crash_hold_momentum_asset_ratio: float
    crash_hold_watchdog_drawdown_pct: float
    crash_hold_min_minutes: float
    live_enabled: bool
    live_trading_confirm: str
    live_allowed_assets: tuple[str, ...]
    live_allow_triangular: bool
    live_max_route_legs: int
    live_max_usd_per_route: float
    live_state_file: Path
    live_max_usd_per_trade: float
    live_drawdown_halt_pct: float
    live_min_eth_reserve: float
    live_max_trades: int
    live_strict_profit: bool
    reset_live_state: bool
    live_mirror_paper: bool
    live_mirror_min_confidence: str
    live_mirror_uncertain: bool
    live_mirror_skip_log_file: Path
    prop_enabled: bool
    enable_equities: bool
    equity_watchlist: tuple[str, ...]
    equity_assets: frozenset[str]
    equity_usd_symbols: tuple[str, ...]
    symbol_assets: dict[str, str]
    asset_usd_symbols: dict[str, str]
    max_equity_allocation_pct: float


def _parse_usd_symbols(raw: str) -> tuple[str, ...]:
    symbols = tuple(s.strip() for s in raw.split(",") if s.strip())
    for symbol in symbols:
        if symbol not in SYMBOL_ASSETS:
            raise ValueError(f"Unsupported symbol: {symbol}")
    return symbols


def _parse_equity_watchlist(raw: str) -> tuple[str, ...]:
    from bot.equities import parse_equity_watchlist

    return parse_equity_watchlist(raw or DEFAULT_EQUITY_WATCHLIST)


def _build_trading_symbol_maps(
    crypto_usd_symbols: tuple[str, ...],
    equity_usd_symbols: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    symbol_assets: dict[str, str] = {}
    for symbol in crypto_usd_symbols:
        symbol_assets[symbol] = SYMBOL_ASSETS[symbol]
    for symbol in equity_usd_symbols:
        symbol_assets[symbol] = symbol.split("/", 1)[0]
    asset_usd = {asset: sym for sym, asset in symbol_assets.items()}
    return symbol_assets, asset_usd


def _parse_core_assets(raw: str) -> tuple[str, ...]:
    return tuple(a.strip() for a in raw.split(",") if a.strip())


def _parse_live_mirror_min_confidence(raw: str) -> str:
    val = (raw or "confirm").strip().lower()
    allowed = ("confirm", "uncertain_ok", "always")
    if val not in allowed:
        raise ValueError(
            f"LIVE_MIRROR_MIN_CONFIDENCE must be one of {allowed}; got {raw!r}"
        )
    return val


def _parse_preferred_start_assets(
    raw: str | None,
    core_assets: tuple[str, ...],
) -> tuple[str, ...]:
    """Assets to spend first when funding rotations; defaults to CORE_ASSETS order."""
    if raw and str(raw).strip():
        return _parse_core_assets(raw)
    preferred = tuple(a for a in core_assets if a not in ("USD", "BTC", "ETH"))
    if preferred:
        return preferred
    return _parse_core_assets(DEFAULT_PREFERRED_START_ASSETS)


def _parse_initial_balances(raw: str) -> dict[str, float]:
    balances = {k: float(v) for k, v in json.loads(raw).items()}
    if "USD" not in balances:
        balances["USD"] = 0.0
    return balances


def _parse_user_ids(raw: str) -> tuple[str, ...]:
    return tuple(uid.strip() for uid in raw.split(",") if uid.strip())


def _parse_strategies(raw: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _parse_milestones(raw: str) -> tuple[float, ...]:
    return tuple(float(x.strip()) for x in raw.split(",") if x.strip())


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    return float(raw)


def _parse_stat_arb_pairs(raw: str) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "/" not in item:
            raise ValueError(f"Invalid stat arb pair (use BASE/QUOTE): {item}")
        base, quote = item.split("/", 1)
        pairs.append((base.strip(), quote.strip()))
    return tuple(pairs)


def _apply_runtime_overrides(
    settings_dict: dict,
    overrides_file: Path | None = None,
) -> list[str]:
    """Overlay ``runtime_overrides.json`` onto an in-flight settings dict.

    Auditor-applied tier-2 changes live in the JSON file (NOT `.env`) so the
    user can revert by removing the key. We log a WARNING listing every
    knob that's currently overridden so the active configuration is never a
    surprise.

    Returns the list of ``"KNOB=value"`` strings that were applied — primarily
    for tests to assert the right keys won.
    """
    path = overrides_file if overrides_file is not None else RUNTIME_OVERRIDES_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("runtime_overrides.json unreadable (%s) — ignored", exc)
        return []
    if not isinstance(raw, dict):
        return []
    active: list[str] = []
    for knob, field_name in RUNTIME_OVERRIDE_KNOBS.items():
        if knob not in raw:
            continue
        try:
            value = float(raw[knob])
        except (TypeError, ValueError):
            continue
        settings_dict[field_name] = value
        active.append(f"{knob}={value}")
    if active:
        logger.warning(
            "Auditor runtime overrides active (from runtime_overrides.json): %s",
            ", ".join(active),
        )
    return active


def _env_int(name: str, default: str, *, quiet: bool = False, quiet_default: str | None = None) -> int:
    raw = os.getenv(name)
    if raw is not None and str(raw).strip() != "":
        return int(raw)
    if quiet and quiet_default is not None:
        return int(quiet_default)
    return int(default)


def load_settings() -> Settings:
    enable_equities = os.getenv("ENABLE_EQUITIES", "0") == "1"
    equity_watchlist = _parse_equity_watchlist(
        os.getenv("EQUITY_WATCHLIST", DEFAULT_EQUITY_WATCHLIST)
    )
    crypto_usd_symbols = _parse_usd_symbols(os.getenv("SYMBOLS", DEFAULT_SYMBOLS))
    equity_usd_symbols: tuple[str, ...] = ()
    if enable_equities:
        from bot.equities import resolve_watchlist_pairs

        equity_usd_symbols = resolve_watchlist_pairs(equity_watchlist)
    usd_symbols = crypto_usd_symbols + equity_usd_symbols
    symbol_assets, asset_usd_symbols = _build_trading_symbol_maps(
        crypto_usd_symbols, equity_usd_symbols
    )
    watch_assets = tuple(symbol_assets[s] for s in usd_symbols)
    equity_assets = frozenset(equity_watchlist) if enable_equities else frozenset()
    discord_quiet_mode = os.getenv("DISCORD_QUIET_MODE", "0") == "1"
    # "Day-trader mode" — opt-in aggressive profile (DAY_TRADER_MODE=1). It only
    # changes the *defaults* for the cadence/sizing knobs below; any explicit
    # env var still overrides. Edges remain fee-protected by preflight, so
    # "aggressive" means more/larger trades, not unprofitable ones.
    day_trader = os.getenv("DAY_TRADER_MODE", "0") == "1"

    def _dt(aggressive: str, normal: str) -> str:
        return aggressive if day_trader else normal

    fields: dict = dict(
        watch_assets=watch_assets,
        usd_symbols=usd_symbols,
        core_assets=_parse_core_assets(os.getenv("CORE_ASSETS", DEFAULT_CORE_ASSETS)),
        preferred_start_assets=_parse_preferred_start_assets(
            os.getenv("PREFERRED_START_ASSETS"),
            _parse_core_assets(os.getenv("CORE_ASSETS", DEFAULT_CORE_ASSETS)),
        ),
        initial_balances=_parse_initial_balances(
            os.getenv("INITIAL_BALANCES", '{"ETH": 1.0, "ADA": 83.0, "USD": 0.0}')
        ),
        poll_interval=int(os.getenv("POLL_INTERVAL", "15")),
        fee_rate=float(os.getenv("FEE_RATE", "0.0026")),
        candle_timeframe=os.getenv("CANDLE_TIMEFRAME", "5m"),
        candle_limit=int(os.getenv("CANDLE_LIMIT", "60")),
        ema_fast=int(os.getenv("EMA_FAST", "9")),
        ema_slow=int(os.getenv("EMA_SLOW", "21")),
        momentum_sell=float(os.getenv("MOMENTUM_SELL", "-0.002")),
        trade_size_pct=float(os.getenv("TRADE_SIZE_PCT", _dt("0.20", "0.10"))),
        expansion_size_pct=float(os.getenv("EXPANSION_SIZE_PCT", "0.15")),
        min_usd_trade=float(os.getenv("MIN_USD_TRADE", "10.0")),
        diversify_bonus=float(os.getenv("DIVERSIFY_BONUS", "0.0015")),
        dust_usd=float(os.getenv("DUST_USD", "25.0")),
        drawdown_hibernate_pct=float(
            os.getenv("DRAWDOWN_HIBERNATE_PCT") or os.getenv("DRAWDOWN_PAUSE_PCT", "0.15")
        ),
        hibernate_hours=float(os.getenv("HIBERNATE_HOURS") or os.getenv("PAUSE_HOURS", "12")),
        trade_cooldown_seconds=int(os.getenv("TRADE_COOLDOWN_SECONDS", _dt("45", "180"))),
        max_trades_per_hour=int(os.getenv("MAX_TRADES_PER_HOUR", _dt("40", "12"))),
        min_trade_edge=float(os.getenv("MIN_TRADE_EDGE", _dt("0.004", "0.006"))),
        leader_stable_seconds=int(os.getenv("LEADER_STABLE_SECONDS", _dt("120", "600"))),
        fee_safety_multiplier=float(os.getenv("FEE_SAFETY_MULTIPLIER", "2.0")),
        reset_paper_state=os.getenv("RESET_PAPER_STATE", "0") == "1",
        alerts_enabled=os.getenv("ALERTS_ENABLED", "0") == "1",
        alert_discord_webhook=os.getenv("ALERT_DISCORD_WEBHOOK", ""),
        discord_enabled=os.getenv("DISCORD_ENABLED", "0") == "1",
        discord_webhook=(os.getenv("DISCORD_WEBHOOK", "") or os.getenv("ALERT_DISCORD_WEBHOOK", "")).strip(),
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        discord_channel_id=os.getenv("DISCORD_CHANNEL_ID", "").strip(),
        discord_allowed_user_ids=_parse_user_ids(os.getenv("DISCORD_ALLOWED_USER_IDS", "")),
        discord_heartbeat_minutes=_env_int(
            "DISCORD_HEARTBEAT_MINUTES",
            "30",
            quiet=discord_quiet_mode,
            quiet_default="60",
        ),
        discord_quiet_mode=discord_quiet_mode,
        discord_whale_skip_to_discord=os.getenv("DISCORD_WHALE_SKIP_TO_DISCORD", "0") == "1",
        discord_trade_summary_interval_minutes=_env_int(
            "DISCORD_TRADE_SUMMARY_INTERVAL_MINUTES",
            "0",
            quiet=discord_quiet_mode,
            quiet_default="60",
        ),
        discord_major_move_pct=float(os.getenv("DISCORD_MAJOR_MOVE_PCT", "0.05")),
        discord_major_move_cooldown_minutes=_env_int(
            "DISCORD_MAJOR_MOVE_COOLDOWN_MINUTES", "60"
        ),
        trade_verify_discord_tag=os.getenv("TRADE_VERIFY_DISCORD_TAG", "1") == "1",
        trade_verify_skip_kraken=os.getenv("TRADE_VERIFY_SKIP_KRAKEN", "0") == "1",
        whale_follow_skip_log_file=ROOT / os.getenv(
            "WHALE_FOLLOW_SKIP_LOG_FILE", "logs/whale_follow_skips.log"
        ),
        discord_error_cooldown_minutes=int(os.getenv("DISCORD_ERROR_COOLDOWN_MINUTES", "15")),
        discord_error_pin_count=int(os.getenv("DISCORD_ERROR_PIN_COUNT", "3")),
        discord_error_pin_window_minutes=int(os.getenv("DISCORD_ERROR_PIN_WINDOW_MINUTES", "30")),
        discord_pin_enabled=os.getenv("DISCORD_PIN_ENABLED", "1") == "1",
        discord_pin_pnl_pct=float(os.getenv("DISCORD_PIN_PNL_PCT", "0.05")),
        discord_pin_trade_usd=float(os.getenv("DISCORD_PIN_TRADE_USD", "25")),
        discord_max_pins_retain=int(os.getenv("DISCORD_MAX_PINS_RETAIN", "15")),
        discord_chat_log_enabled=os.getenv("DISCORD_CHAT_LOG_ENABLED", "1") == "1",
        discord_chat_log_file=os.getenv("DISCORD_CHAT_LOG_FILE", "logs/discord_chat.log"),
        alert_telegram_bot_token=os.getenv("ALERT_TELEGRAM_BOT_TOKEN", ""),
        alert_telegram_chat_id=os.getenv("ALERT_TELEGRAM_CHAT_ID", ""),
        alert_smtp_host=os.getenv("ALERT_SMTP_HOST", ""),
        alert_smtp_port=int(os.getenv("ALERT_SMTP_PORT", "587")),
        alert_smtp_user=os.getenv("ALERT_SMTP_USER", ""),
        alert_smtp_password=os.getenv("ALERT_SMTP_PASSWORD", ""),
        alert_email_from=os.getenv("ALERT_EMAIL_FROM", ""),
        alert_email_to=os.getenv("ALERT_EMAIL_TO", ""),
        alert_twilio_sid=os.getenv("ALERT_TWILIO_SID", ""),
        alert_twilio_token=os.getenv("ALERT_TWILIO_TOKEN", ""),
        alert_twilio_from=os.getenv("ALERT_TWILIO_FROM", ""),
        alert_sms_to=os.getenv("ALERT_SMS_TO", ""),
        api_key=os.getenv("KRAKEN_API_KEY", ""),
        api_secret=os.getenv("KRAKEN_API_SECRET", ""),
        state_file=ROOT / ".paper_state.json",
        paper_portfolio_file=ROOT / os.getenv("PAPER_PORTFOLIO_FILE", "paper_portfolio.json"),
        log_dir=ROOT / "logs",
        receipts_dir=ROOT / "receipts",
        log_rotate_hours=int(os.getenv("LOG_ROTATE_HOURS", "4")),
        strategies=_parse_strategies(os.getenv("STRATEGIES", DEFAULT_STRATEGIES)),
        slippage_buffer_pct=float(os.getenv("SLIPPAGE_BUFFER_PCT", "0.0005")),
        min_net_profit_pct=float(os.getenv("MIN_NET_PROFIT_PCT", "0.0005")),
        safe_assets=_parse_core_assets(os.getenv("SAFE_ASSETS", DEFAULT_SAFE_ASSETS)),
        stat_arb_zscore_threshold=float(os.getenv("STAT_ARB_ZSCORE_THRESHOLD", "2.5")),
        stat_arb_lookback=int(os.getenv("STAT_ARB_LOOKBACK", "48")),
        stat_arb_pairs=_parse_stat_arb_pairs(
            os.getenv("STAT_ARB_PAIRS", DEFAULT_STAT_ARB_PAIRS)
        ),
        momentum_timeframes=tuple(
            tf.strip()
            for tf in os.getenv("MOMENTUM_TIMEFRAMES", DEFAULT_MOMENTUM_TIMEFRAMES).split(",")
            if tf.strip()
        ),
        circuit_breaker_enabled=os.getenv("CIRCUIT_BREAKER_ENABLED", "1") == "1",
        diagnostic_dir=ROOT / "diagnostics",
        idle_reeval_hours=float(os.getenv("IDLE_REEVAL_HOURS", "2")),
        idle_reeval_max_attempts=int(os.getenv("IDLE_REEVAL_MAX_ATTEMPTS", "3")),
        idle_probe_force_minutes=float(os.getenv("IDLE_PROBE_FORCE_MINUTES", "0")),
        idle_probe_size_pct=float(os.getenv("IDLE_PROBE_SIZE_PCT", "0.05")),
        fee_force_static=os.getenv("FEE_FORCE_STATIC", "0") == "1",
        min_eth_reserve=float(os.getenv("MIN_ETH_RESERVE", "0.25")),
        max_alt_allocation_pct=float(os.getenv("MAX_ALT_ALLOCATION_PCT", "0.40")),
        strategy_growth_window_hours=float(os.getenv("STRATEGY_GROWTH_WINDOW_HOURS", "4")),
        strategy_min_growth_pct=float(os.getenv("STRATEGY_MIN_GROWTH_PCT", "0.005")),
        strategy_strong_growth_pct=float(os.getenv("STRATEGY_STRONG_GROWTH_PCT", "0.015")),
        strategy_switch_edge_margin=float(os.getenv("STRATEGY_SWITCH_EDGE_MARGIN", "0.002")),
        strategy_exploration_ratio=float(os.getenv("STRATEGY_EXPLORATION_RATIO", "0.25")),
        kraken_request_timeout_ms=int(os.getenv("KRAKEN_REQUEST_TIMEOUT_MS", "5000")),
        kraken_max_retries=int(os.getenv("KRAKEN_MAX_RETRIES", "2")),
        kraken_retry_backoff_sec=float(os.getenv("KRAKEN_RETRY_BACKOFF_SEC", "0.75")),
        auditor_enabled=os.getenv("AUDITOR_ENABLED", "1") == "1",
        auditor_daily_run_hour_pacific=int(os.getenv("AUDITOR_DAILY_HOUR_PACIFIC", "8")),
        auditor_trade_count_trigger=int(os.getenv("AUDITOR_TRADE_COUNT_TRIGGER", "20")),
        auditor_pnl_pct_trigger=float(os.getenv("AUDITOR_PNL_PCT_TRIGGER", "0.05")),
        auditor_news_enabled=os.getenv("AUDITOR_NEWS_ENABLED", "1") == "1",
        auditor_news_provider=os.getenv("AUDITOR_NEWS_PROVIDER", "rss,coingecko"),
        auditor_cryptopanic_api_key=os.getenv("AUDITOR_CRYPTOPANIC_KEY", "").strip(),
        auditor_rss_feeds=os.getenv("AUDITOR_RSS_FEEDS", "").strip(),
        auditor_news_max_items=int(os.getenv("AUDITOR_NEWS_MAX_ITEMS", "10")),
        auditor_proposals_ttl_minutes=int(os.getenv("AUDITOR_PROPOSAL_TTL_MINUTES", "60")),
        auditor_reports_dir=ROOT / os.getenv("AUDITOR_REPORTS_DIR", "reports"),
        auditor_state_file=ROOT / ".auditor_state.json",
        auditor_autoapply_enabled=os.getenv("AUDITOR_AUTOAPPLY_ENABLED", "0") == "1",
        auditor_autoapply_window_start_hour=int(os.getenv("AUDITOR_AUTOAPPLY_WINDOW_START_HOUR", "1")),
        auditor_autoapply_window_end_hour=int(os.getenv("AUDITOR_AUTOAPPLY_WINDOW_END_HOUR", "7")),
        auditor_autoapply_min_severity=os.getenv("AUDITOR_AUTOAPPLY_MIN_SEVERITY", "high").lower().strip(),
        auditor_autoapply_max_per_night=int(os.getenv("AUDITOR_AUTOAPPLY_MAX_PER_NIGHT", "1")),
        auditor_autoapply_restart_enabled=os.getenv("AUDITOR_AUTOAPPLY_RESTART_ENABLED", "1") == "1",
        auditor_confirm_restart_enabled=os.getenv("AUDITOR_CONFIRM_RESTART", "1") == "1",
        auditor_chat_enabled=os.getenv("AUDITOR_CHAT_ENABLED", "0") == "1",
        auditor_chat_backend=os.getenv("AUDITOR_CHAT_BACKEND", "gemini").lower().strip(),
        auditor_chat_model=os.getenv("AUDITOR_CHAT_MODEL", "gemini-2.5-flash-lite").strip(),
        auditor_chat_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        auditor_chat_max_turns=int(os.getenv("AUDITOR_CHAT_MAX_TURNS", "6")),
        auditor_chat_max_tokens=int(os.getenv("AUDITOR_CHAT_MAX_TOKENS", "1000")),
        auditor_chat_temperature=float(os.getenv("AUDITOR_CHAT_TEMPERATURE", "0.3")),
        auditor_chat_tool_iterations=int(os.getenv("AUDITOR_CHAT_TOOL_ITERATIONS", "2")),
        auditor_chat_tool_result_max_chars=int(os.getenv("AUDITOR_CHAT_TOOL_RESULT_MAX_CHARS", "2000")),
        auditor_discord_quiet=os.getenv(
            "AUDITOR_DISCORD_QUIET", "1" if discord_quiet_mode else "0"
        ) == "1",
        whale_watch_enabled=os.getenv("WHALE_WATCH_ENABLED", "0") == "1",
        whale_watch_min_usd=float(os.getenv("WHALE_WATCH_MIN_USD", "1000000")),
        whale_watch_spike_min_usd=float(
            os.getenv("WHALE_WATCH_SPIKE_MIN_USD", os.getenv("WHALE_WATCH_MIN_USD", "1000000"))
        ),
        whale_watch_assets=_parse_core_assets(os.getenv("WHALE_WATCH_ASSETS", "ETH,BTC,SOL")),
        whale_watch_poll_seconds=int(os.getenv("WHALE_WATCH_POLL_SECONDS", "60")),
        whale_watch_volume_spike_ratio=float(os.getenv("WHALE_WATCH_VOLUME_SPIKE_RATIO", "3.0")),
        whale_watch_max_events=int(os.getenv("WHALE_WATCH_MAX_EVENTS", "100")),
        whale_watch_state_file=ROOT / ".whale_watch_state.json",
        whale_watch_discord_alerts=os.getenv("WHALE_WATCH_DISCORD_ALERTS", "0") == "1",
        whale_watch_log_file=ROOT / os.getenv("WHALE_WATCH_LOG_FILE", "logs/whale_watch.log"),
        whale_follow_enabled=os.getenv("WHALE_FOLLOW_ENABLED", "0") == "1",
        whale_follow_size_pct=float(os.getenv("WHALE_FOLLOW_SIZE_PCT", "0.15")),
        whale_follow_cooldown_sec=int(os.getenv("WHALE_FOLLOW_COOLDOWN_SEC", "300")),
        whale_follow_max_per_hour=int(os.getenv("WHALE_FOLLOW_MAX_PER_HOUR", "2")),
        whale_follow_min_net_profit=float(os.getenv("WHALE_FOLLOW_MIN_NET_PROFIT", "0.0005")),
        goal_evolution_enabled=os.getenv("GOAL_EVOLUTION_ENABLED", "1") == "1",
        goal_state_file=ROOT / os.getenv("GOAL_STATE_FILE", ".tradebot_goals_state.json"),
        goal_milestones_usd=_parse_milestones(
            os.getenv("GOAL_MILESTONES_USD", "10000,100000,1000000")
        ),
        goal_tier0_strategies=_parse_strategies(
            os.getenv(
                "GOAL_TIER0_STRATEGIES",
                "cross_momentum,stat_arb,triangular_arbitrage",
            )
        ),
        goal_tier1_strategies=_parse_strategies(
            os.getenv("GOAL_TIER1_STRATEGIES", "cross_momentum,stat_arb")
        ),
        goal_tier2_strategies=_parse_strategies(
            os.getenv("GOAL_TIER2_STRATEGIES", "cross_momentum,stat_arb,triangular_arbitrage")
        ),
        goal_tier3_strategies=_parse_strategies(
            os.getenv(
                "GOAL_TIER3_STRATEGIES",
                "cross_momentum,stat_arb,triangular_arbitrage",
            )
        ),
        goal_tier2_exploration_ratio=_parse_optional_float(
            os.getenv("GOAL_TIER2_EXPLORATION_RATIO", "0.35")
        ),
        goal_tier3_exploration_ratio=_parse_optional_float(
            os.getenv("GOAL_TIER3_EXPLORATION_RATIO", "0.40")
        ),
        goal_tier3_whale_follow_size_mult=float(
            os.getenv("GOAL_TIER3_WHALE_FOLLOW_SIZE_MULT", "1.25")
        ),
        crash_hold_enabled=os.getenv("CRASH_HOLD_ENABLED", "1") == "1",
        crash_hold_drawdown_pct=float(os.getenv("CRASH_HOLD_DRAWDOWN_PCT", "0.08")),
        crash_hold_session_drawdown_pct=float(
            os.getenv("CRASH_HOLD_SESSION_DRAWDOWN_PCT", "0.06")
        ),
        crash_hold_recovery_drawdown_pct=float(
            os.getenv("CRASH_HOLD_RECOVERY_DRAWDOWN_PCT", "0.05")
        ),
        crash_hold_momentum_threshold=float(
            os.getenv("CRASH_HOLD_MOMENTUM_THRESHOLD", "-0.015")
        ),
        crash_hold_momentum_asset_ratio=float(
            os.getenv("CRASH_HOLD_MOMENTUM_ASSET_RATIO", "0.60")
        ),
        crash_hold_watchdog_drawdown_pct=float(
            os.getenv("CRASH_HOLD_WATCHDOG_DRAWDOWN_PCT", "0.10")
        ),
        crash_hold_min_minutes=float(os.getenv("CRASH_HOLD_MIN_MINUTES", "30")),
        live_enabled=(
            os.getenv("LIVE_TRADING_ENABLED", os.getenv("LIVE_ENABLED", "0")) == "1"
        ),
        live_trading_confirm=os.getenv("LIVE_TRADING_CONFIRM", ""),
        live_allowed_assets=_parse_core_assets(
            os.getenv("LIVE_ALLOWED_ASSETS", "ETH,ADA")
        ),
        live_allow_triangular=os.getenv("LIVE_ALLOW_TRIANGULAR", "0") == "1",
        live_max_route_legs=int(os.getenv("LIVE_MAX_ROUTE_LEGS", "1")),
        live_max_usd_per_route=float(
            os.getenv(
                "LIVE_MAX_ROUTE_USD",
                os.getenv(
                    "LIVE_MAX_TRADE_USD",
                    os.getenv("LIVE_MAX_USD_PER_TRADE", "50"),
                ),
            )
        ),
        live_state_file=ROOT / os.getenv("LIVE_STATE_FILE", ".live_state.json"),
        live_max_usd_per_trade=float(
            os.getenv(
                "LIVE_MAX_TRADE_USD",
                os.getenv("LIVE_MAX_USD_PER_TRADE", "50"),
            )
        ),
        live_drawdown_halt_pct=float(os.getenv("LIVE_DRAWDOWN_HALT_PCT", "0.10")),
        live_min_eth_reserve=float(os.getenv("LIVE_MIN_ETH_RESERVE", "0.5")),
        live_max_trades=int(os.getenv("LIVE_MAX_TRADES", "0")),
        live_strict_profit=os.getenv("LIVE_STRICT_PROFIT", "1") == "1",
        reset_live_state=os.getenv("RESET_LIVE_STATE", "0") == "1",
        live_mirror_paper=os.getenv("LIVE_MIRROR_PAPER", "0") == "1",
        live_mirror_min_confidence=_parse_live_mirror_min_confidence(
            os.getenv("LIVE_MIRROR_MIN_CONFIDENCE", "confirm")
        ),
        live_mirror_uncertain=os.getenv("LIVE_MIRROR_UNCERTAIN", "0") == "1",
        live_mirror_skip_log_file=ROOT / os.getenv(
            "LIVE_MIRROR_SKIP_LOG_FILE", "logs/live_mirror_skips.log"
        ),
        prop_enabled=os.getenv("PROP_ENABLED", "0") == "1",
        enable_equities=enable_equities,
        equity_watchlist=equity_watchlist,
        equity_assets=equity_assets,
        equity_usd_symbols=equity_usd_symbols,
        symbol_assets=symbol_assets,
        asset_usd_symbols=asset_usd_symbols,
        max_equity_allocation_pct=float(
            os.getenv("MAX_EQUITY_ALLOCATION_PCT", DEFAULT_MAX_EQUITY_ALLOCATION_PCT)
        ),
    )
    _apply_runtime_overrides(fields)
    if fields["live_enabled"] and not fields["live_mirror_paper"]:
        fields["state_file"] = fields["live_state_file"]
    return Settings(**fields)
