"""Auditor bot — performance auditor with news context and tier-2 proposals.

Public surface intentionally narrow so the service layer can pull everything
from one import. See `feature_logs/019_auditor-bot.md` for the design.
"""

from bot.auditor.config import AuditorConfig
from bot.auditor.report import AuditReport

__all__ = ["AuditorConfig", "AuditReport", "AuditorService"]


def __getattr__(name: str):
    """Lazy import to avoid a circular dep when bot.engine imports auditor_service."""
    if name == "AuditorService":
        from bot.auditor_service import AuditorService

        return AuditorService
    raise AttributeError(f"module 'bot.auditor' has no attribute {name!r}")
