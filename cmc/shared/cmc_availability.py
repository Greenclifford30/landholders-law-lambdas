"""Shared validation and availability derivation for Movie Club scheduling."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cmc_shared import ApiError, parse_iso_datetime


AVAILABILITY_STATUSES = {"available", "maybe", "unavailable"}
CALENDAR_RESULTS = {"free", "conflict", "unknown"}
DEFAULT_TIME_ZONE = "America/Chicago"
DEFAULT_BUFFER_MINUTES = 30
ESTIMATED_RUNTIME_MINUTES = 180
MAX_BUFFER_MINUTES = 180
MAX_WEEKLY_WINDOWS = 14
FRESH_FOR = timedelta(hours=2)
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalize_time_zone(value):
    name = str(value or DEFAULT_TIME_ZONE).strip() or DEFAULT_TIME_ZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiError(400, "timeZone must be a valid IANA timezone.") from exc
    return name


def normalize_buffer(value, name):
    if isinstance(value, bool):
        raise ApiError(400, f"{name} must be an integer number of minutes.")
    try:
        minutes = int(DEFAULT_BUFFER_MINUTES if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f"{name} must be an integer number of minutes.") from exc
    if minutes < 0 or minutes > MAX_BUFFER_MINUTES:
        raise ApiError(400, f"{name} must be between 0 and {MAX_BUFFER_MINUTES} minutes.")
    return minutes


def _minutes(value, name):
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise ApiError(400, f"{name} must use 24-hour HH:mm format.")
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def normalize_weekly_availability(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ApiError(400, "weeklyAvailability must be a list.")
    if len(value) > MAX_WEEKLY_WINDOWS:
        raise ApiError(400, f"weeklyAvailability supports at most {MAX_WEEKLY_WINDOWS} windows.")

    normalized = []
    by_day = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError(400, "Each weekly availability window must be an object.")
        day = raw.get("dayOfWeek")
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            raise ApiError(400, "dayOfWeek must be an integer from 0 (Sunday) through 6 (Saturday).")
        start = str(raw.get("startTime") or "")
        end = str(raw.get("endTime") or "")
        start_minutes = _minutes(start, "startTime")
        end_minutes = _minutes(end, "endTime")
        if start_minutes >= end_minutes:
            raise ApiError(400, "Weekly availability windows must end after they start on the same day.")
        for existing_start, existing_end in by_day.setdefault(day, []):
            if start_minutes < existing_end and end_minutes > existing_start:
                raise ApiError(400, "Weekly availability windows cannot overlap on the same day.")
        by_day[day].append((start_minutes, end_minutes))
        normalized.append({"dayOfWeek": day, "startTime": start, "endTime": end})

    normalized.sort(key=lambda item: (item["dayOfWeek"], item["startTime"], item["endTime"]))
    return normalized


def scheduling_preferences(item=None):
    item = item or {}
    return {
        "timeZone": normalize_time_zone(item.get("timeZone")),
        "weeklyAvailability": normalize_weekly_availability(item.get("weeklyAvailability", [])),
        "bufferBeforeMinutes": normalize_buffer(item.get("bufferBeforeMinutes"), "bufferBeforeMinutes"),
        "bufferAfterMinutes": normalize_buffer(item.get("bufferAfterMinutes"), "bufferAfterMinutes"),
    }


def normalize_manual_overrides(value, valid_showtime_ids):
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ApiError(400, "overrides must be a list.")
    normalized = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError(400, "Each availability override must be an object.")
        showtime_id = str(raw.get("showtimeId") or "").strip()
        status = raw.get("status")
        if showtime_id not in valid_showtime_ids:
            raise ApiError(400, "Availability includes an unknown showtime.")
        if status not in AVAILABILITY_STATUSES:
            raise ApiError(400, "Availability status must be available, maybe, or unavailable.")
        normalized[showtime_id] = status
    return normalized


def showtime_window(showtime, movie, preferences):
    start = parse_iso_datetime(showtime.get("startsAtUtc") or showtime.get("startsAt"))
    if not start:
        return None
    raw_runtime = (movie or {}).get("runtime")
    known_runtime = isinstance(raw_runtime, (int, float, Decimal)) and not isinstance(raw_runtime, bool) and raw_runtime > 0
    runtime = float(raw_runtime) if known_runtime else ESTIMATED_RUNTIME_MINUTES
    return {
        "start": start - timedelta(minutes=preferences["bufferBeforeMinutes"]),
        "end": start + timedelta(minutes=runtime + preferences["bufferAfterMinutes"]),
        "runtimeEstimated": not known_runtime,
    }


def inside_recurring_window(window, preferences):
    if not window:
        return None
    weekly = preferences.get("weeklyAvailability") or []
    if not weekly:
        return None
    zone = ZoneInfo(preferences["timeZone"])
    local_start = window["start"].astimezone(zone)
    local_end = window["end"].astimezone(zone)
    if local_start.date() != local_end.date():
        return False
    # Python Monday=0; the public contract uses Sunday=0.
    day = (local_start.weekday() + 1) % 7
    start_minutes = local_start.hour * 60 + local_start.minute
    end_minutes = local_end.hour * 60 + local_end.minute
    return any(
        entry["dayOfWeek"] == day
        and start_minutes >= _minutes(entry["startTime"], "startTime")
        and end_minutes <= _minutes(entry["endTime"], "endTime")
        for entry in weekly
    )


def calendar_result_is_fresh(availability, at=None):
    synced = parse_iso_datetime((availability or {}).get("calendarSyncedAt"))
    if not synced:
        return False
    return (at or datetime.now(timezone.utc)) - synced <= FRESH_FOR


def resolve_status(*, showtime, movie, preferences, membership, availability, integration, revision, at=None):
    showtime_id = showtime["showtimeId"]
    record_is_current = int((availability or {}).get("availabilityRevision", 0)) == int(revision)
    manual = (availability or {}).get("manualOverrides", {}).get(showtime_id) if record_is_current else None
    if manual in AVAILABILITY_STATUSES:
        return manual
    if not membership.get("shareCalendarAvailability", False):
        return "unknown"

    window = showtime_window(showtime, movie, preferences)
    within_schedule = inside_recurring_window(window, preferences)
    if within_schedule is False:
        return "unavailable"

    integration = integration or {}
    selected = integration.get("selectedCalendarIds") or []
    if selected and integration.get("status") in {"needs_reauth", "error"}:
        return "unknown"
    calendar_connected = integration.get("status") == "connected" and bool(selected)
    if not calendar_connected:
        return "available" if within_schedule is True else "unknown"

    availability = availability or {}
    if not record_is_current:
        return "unknown"
    sync_status = availability.get("calendarSyncStatus")
    if sync_status not in {"current", "partial"} or not calendar_result_is_fresh(availability, at):
        return "unknown"
    calendar_result = (availability.get("calendarStatuses") or {}).get(showtime_id, "unknown")
    if calendar_result == "conflict":
        return "unavailable"
    if sync_status == "current" and calendar_result == "free" and within_schedule is True:
        return "available"
    return "unknown"


def enqueue_availability_sync(*, user_id=None, movie_night_id=None, reason="changed"):
    queue_url = os.environ.get("CALENDAR_SYNC_QUEUE_URL")
    if not queue_url:
        return False
    import boto3

    message = {"reason": reason}
    if user_id:
        message["userId"] = user_id
    if movie_night_id:
        message["movieNightId"] = movie_night_id
    boto3.client("sqs").send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
    return True


def emit_calendar_metrics(**metrics):
    """Emit privacy-safe CloudWatch embedded metrics without user or calendar dimensions."""
    if not metrics:
        return
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    definitions = [
        {"Name": name, "Unit": "Milliseconds" if name.endswith("LatencyMs") else "Count"}
        for name in metrics
    ]
    print(json.dumps({
        "_aws": {
            "Timestamp": timestamp,
            "CloudWatchMetrics": [{
                "Namespace": "MovieClub/CalendarAvailability",
                "Dimensions": [[]],
                "Metrics": definitions,
            }],
        },
        **metrics,
    }))
