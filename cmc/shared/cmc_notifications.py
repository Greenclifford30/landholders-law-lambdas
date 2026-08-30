"""Durable Movie Club notification records and outbox helpers."""
from datetime import timedelta

from botocore.exceptions import ClientError

from cmc_shared import now_iso, parse_iso_datetime, put_item


MILESTONE_TYPES = {"voting_open", "showtime_confirmed", "showtime_changed", "movie_night_cancelled"}
REMINDER_TYPES = {"vote_reminder", "rsvp_reminder"}


def event_id(movie_night, notification_type):
    sequence = movie_night.get("calendarSequence", 0)
    return f"{movie_night['movieNightId']}#{notification_type}#{sequence}"


def enqueue_movie_notification(movie_night, notification_type):
    """Store a deduplicated event for asynchronous recipient fan-out and delivery."""
    created_at = now_iso()
    identifier = event_id(movie_night, notification_type)
    item = {
        "PK": "NOTIFICATION_OUTBOX",
        "SK": f"EVENT#{identifier}",
        "entityType": "notificationOutbox",
        "eventId": identifier,
        "notificationType": notification_type,
        "clubId": movie_night["clubId"],
        "movieNightId": movie_night["movieNightId"],
        "movieTitle": (movie_night.get("movie") or {}).get("title", "Movie night"),
        "movieNightStatus": movie_night.get("status"),
        "confirmedShowtime": movie_night.get("confirmedShowtime"),
        "votingClosesAt": movie_night.get("votingClosesAt"),
        "createdAt": created_at,
        "status": "pending",
    }
    try:
        put_item(item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    schedule_reminder(movie_night, notification_type, created_at)


def schedule_reminder(movie_night, notification_type, created_at=None):
    deadline = None
    reminder_type = None
    if notification_type == "voting_open":
        deadline = parse_iso_datetime(movie_night.get("votingClosesAt"))
        reminder_type = "vote_reminder"
    elif notification_type in {"showtime_confirmed", "showtime_changed"}:
        deadline = parse_iso_datetime((movie_night.get("confirmedShowtime") or {}).get("startsAtUtc"))
        reminder_type = "rsvp_reminder"
    if not deadline:
        return
    due_at = deadline - timedelta(hours=24)
    if due_at.isoformat().replace("+00:00", "Z") <= now_iso():
        return
    identifier = event_id(movie_night, reminder_type)
    item = {
        "PK": "NOTIFICATION_DUE",
        "SK": f"DUE#{due_at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}#{identifier}",
        "entityType": "notificationReminder",
        "eventId": identifier,
        "notificationType": reminder_type,
        "clubId": movie_night["clubId"],
        "movieNightId": movie_night["movieNightId"],
        "movieTitle": (movie_night.get("movie") or {}).get("title", "Movie night"),
        "movieNightStatus": movie_night.get("status"),
        "confirmedShowtime": movie_night.get("confirmedShowtime"),
        "createdAt": created_at or now_iso(),
        "status": "pending",
    }
    try:
        put_item(item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
