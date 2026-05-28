"""Optional outbound alerts when the bot enters hibernation."""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool
    discord_webhook: str
    telegram_bot_token: str
    telegram_chat_id: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str
    twilio_sid: str
    twilio_token: str
    twilio_from: str
    sms_to: str

    @property
    def has_any_channel(self) -> bool:
        return bool(
            self.discord_webhook
            or (self.telegram_bot_token and self.telegram_chat_id)
            or (self.smtp_host and self.email_to)
            or (self.twilio_sid and self.twilio_token and self.twilio_from and self.sms_to)
        )


class AlertManager:
    def __init__(self, config: AlertConfig):
        self.config = config

    def send_hibernate_alert(
        self,
        *,
        portfolio: float,
        peak: float,
        drawdown_pct: float,
        drawdown_limit_pct: float,
        resume_at: str,
        baseline_pnl: float,
    ) -> list[str]:
        """Send hibernation alert on all configured channels. Returns delivery errors."""
        if not self.config.enabled or not self.config.has_any_channel:
            return []

        title = "Trading bot HIBERNATING"
        body = (
            f"{title}\n"
            f"Portfolio: ${portfolio:,.2f}\n"
            f"Peak: ${peak:,.2f}\n"
            f"Drawdown: {drawdown_pct:.1%} (limit {drawdown_limit_pct:.0%})\n"
            f"PnL from start: {baseline_pnl:+.2f}\n"
            f"Resumes: {resume_at}\n"
            f"All trading paused for the hibernation window."
        )

        errors: list[str] = []
        if self.config.discord_webhook:
            self._send_discord(title, body, errors)
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            self._send_telegram(body, errors)
        if self.config.smtp_host and self.config.email_to:
            self._send_email(title, body, errors)
        if self.config.twilio_sid and self.config.twilio_token and self.config.twilio_from and self.config.sms_to:
            self._send_sms(body, errors)

        for err in errors:
            logger.warning("Alert delivery failed: %s", err)
        return errors

    def _post_json(self, url: str, payload: dict, *, headers: dict | None = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)

    def _send_discord(self, title: str, body: str, errors: list[str]) -> None:
        try:
            self._post_json(
                self.config.discord_webhook,
                {"content": f"**{title}**\n```\n{body}\n```"},
            )
        except Exception as exc:
            errors.append(f"Discord: {exc}")

    def _send_telegram(self, body: str, errors: list[str]) -> None:
        token = self.config.telegram_bot_token
        chat_id = self.config.telegram_chat_id
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            self._post_json(url, {"chat_id": chat_id, "text": body})
        except Exception as exc:
            errors.append(f"Telegram: {exc}")

    def _send_email(self, subject: str, body: str, errors: list[str]) -> None:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.config.email_from or self.config.smtp_user
            msg["To"] = self.config.email_to
            msg.set_content(body)

            context = ssl.create_default_context()
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15) as smtp:
                smtp.starttls(context=context)
                if self.config.smtp_user:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(msg)
        except Exception as exc:
            errors.append(f"Email: {exc}")

    def _send_sms(self, body: str, errors: list[str]) -> None:
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.config.twilio_sid}/Messages.json"
        )
        payload = urllib.parse.urlencode(
            {
                "From": self.config.twilio_from,
                "To": self.config.sms_to,
                "Body": body[:1500],
            }
        ).encode("utf-8")
        auth = f"{self.config.twilio_sid}:{self.config.twilio_token}".encode("utf-8")
        import base64

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Basic {base64.b64encode(auth).decode('ascii')}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status >= 400:
                    raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)
        except Exception as exc:
            errors.append(f"SMS: {exc}")
