"""Trigger configuration rules and next-run computation (wall-clock in the automation's timezone)."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Sao_Paulo"
FREQUENCIES = ("daily", "weekly", "monthly")


class InvalidTriggerConfig(ValueError):
    pass


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def normalize_trigger_config(kind: str, config: dict[str, object] | None) -> dict[str, object]:
    """Validate and canonicalize ``trigger_config``; raises InvalidTriggerConfig."""
    config = dict(config or {})
    if kind == "folder_changed":
        if config:
            raise InvalidTriggerConfig("folder_changed takes no configuration")
        return {}
    if kind != "schedule":
        raise InvalidTriggerConfig("unknown trigger kind")
    frequency = config.get("frequency")
    if frequency not in FREQUENCIES:
        raise InvalidTriggerConfig("frequency must be daily, weekly or monthly")
    hour = config.get("hour")
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        raise InvalidTriggerConfig("hour must be between 0 and 23")
    zone = config.get("timezone") or DEFAULT_TIMEZONE
    try:
        ZoneInfo(str(zone))
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise InvalidTriggerConfig("unknown timezone") from error
    normalized: dict[str, object] = {"frequency": frequency, "hour": hour, "timezone": str(zone)}
    if frequency == "weekly":
        weekday = config.get("weekday")
        if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
            raise InvalidTriggerConfig("weekday must be between 0 and 6")
        normalized["weekday"] = weekday
    if frequency == "monthly":
        day = config.get("day")
        if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 28:
            raise InvalidTriggerConfig("day must be between 1 and 28")
        normalized["day"] = day
    return normalized


def compute_next_run(config: dict[str, object], after: datetime) -> datetime:
    """First scheduled instant strictly after ``after`` (UTC)."""
    zone = ZoneInfo(str(config.get("timezone") or DEFAULT_TIMEZONE))
    moment = aware(after).astimezone(UTC)
    local_date = moment.astimezone(zone).date()
    frequency = config["frequency"]
    for offset in range(400):
        day = local_date + timedelta(days=offset)
        if frequency == "weekly" and day.weekday() != config["weekday"]:
            continue
        if frequency == "monthly" and day.day != config["day"]:
            continue
        candidate = datetime.combine(day, time(int(config["hour"])), tzinfo=zone).astimezone(UTC)
        if candidate > moment:
            return candidate
    raise InvalidTriggerConfig("no upcoming run")
