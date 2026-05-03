from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def assume_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)