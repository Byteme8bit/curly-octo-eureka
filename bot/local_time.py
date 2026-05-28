from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_LOG_ROTATE_HOURS = 4


def pacific_now() -> datetime:
    return datetime.now(PACIFIC)


def to_pacific(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PACIFIC)


def format_pacific(dt: datetime | None = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Human-readable Pacific time with PST/PDT suffix."""
    local = to_pacific(dt) if dt is not None else pacific_now()
    return f"{local.strftime(fmt)} {local.tzname()}"


def pacific_stamp(dt: datetime | None = None) -> str:
    """Compact stamp for filenames (Pacific clock)."""
    local = to_pacific(dt) if dt is not None else pacific_now()
    return local.strftime("%Y%m%d-%H%M%S")


def log_window_bounds(
    dt: datetime | None = None,
    hours: int = DEFAULT_LOG_ROTATE_HOURS,
) -> tuple[datetime, datetime]:
    """Aligned Pacific window, e.g. 8:00 PM - 12:00 AM for a 4-hour block."""
    local = to_pacific(dt) if dt is not None else pacific_now()
    block = local.hour // hours
    start = local.replace(hour=block * hours, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=hours)
    return start, end


def log_window_filename(
    start: datetime,
    end: datetime,
) -> str:
    tz = start.tzname() or "PT"
    return (
        f"{start.strftime('%Y-%m-%d_%H-%M')}_to_"
        f"{end.strftime('%Y-%m-%d_%H-%M')}_{tz}.log"
    )


def format_log_window_range(start: datetime, end: datetime) -> str:
    return f"{format_pacific(start)} to {format_pacific(end)}"
