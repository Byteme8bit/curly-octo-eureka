"""Format errors for Discord with context-specific troubleshooting hints."""

from __future__ import annotations

import traceback


def _exc_chain_text(exc: BaseException) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    cause = exc.__cause__ or exc.__context__
    if cause and cause is not exc:
        parts.append(f"{type(cause).__name__}: {cause}")
    return " | ".join(parts)[:600]


def troubleshooting_tips(exc: BaseException) -> list[str]:
    name = type(exc).__name__
    text = _exc_chain_text(exc).lower()
    tips: list[str] = []

    if "403" in text or "forbidden" in text:
        tips.extend([
            "Discord 403: re-invite the bot with Send Messages + Read Message History.",
            "Reset DISCORD_BOT_TOKEN in Developer Portal if the token was revoked.",
            "Regenerate the webhook URL if webhook posts fail.",
        ])
    elif "401" in text or "unauthorized" in text:
        tips.extend([
            "Discord 401: bot token is invalid — reset token and update .env.",
        ])
    elif "429" in text or "rate limit" in text or "ratelimit" in text:
        tips.extend([
            "Rate limited — wait a few minutes; consider raising POLL_INTERVAL in .env.",
            "Kraken or Discord may throttle rapid requests.",
        ])
    elif any(k in text for k in ("timeout", "timed out", "connection", "network", "resolve")):
        tips.extend([
            "Network issue — check your internet connection.",
            "Kraken may be slow or down: https://status.kraken.com",
            "The bot will retry on the next poll automatically.",
        ])
    elif "kraken" in text or name in ("ExchangeError", "ExchangeNotAvailable", "RequestTimeout"):
        tips.extend([
            "Kraken API error — check https://status.kraken.com",
            "If this persists, verify KRAKEN_API_KEY / KRAKEN_API_SECRET in .env (optional for public data).",
            "The bot will retry on the next poll.",
        ])
    elif "json" in text or "decode" in text:
        tips.extend([
            "Unexpected API response — often temporary; wait for the next poll.",
            "Check Kraken status if it keeps happening.",
        ])
    elif "discord" in text:
        tips.extend([
            "Run: python check_discord.py to diagnose Discord connectivity.",
            "Confirm DISCORD_CHANNEL_ID and bot permissions in the server.",
        ])
    else:
        tips.extend([
            "Check the terminal/logs for the full traceback.",
            "If this repeats, restart the bot after fixing the underlying issue.",
            "Send `portfolio` once the error clears to confirm the bot is healthy.",
        ])

    return tips[:4]


def error_dedup_key(context: str, exc: BaseException) -> str:
    return f"{context}:{type(exc).__name__}:{str(exc)[:120]}"


def format_error_alert(context: str, exc: BaseException, *, include_trace: bool = False) -> str:
    summary = _exc_chain_text(exc)
    lines = [
        f"**ERROR — {context}**",
        f"`{summary}`",
        "",
        "**Try:**",
    ]
    for tip in troubleshooting_tips(exc):
        lines.append(f"• {tip}")

    if include_trace:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=3))
        lines.extend(["", "**Trace (last 3 frames):**", f"```\n{tb[-900:]}\n```"])

    return "\n".join(lines)
