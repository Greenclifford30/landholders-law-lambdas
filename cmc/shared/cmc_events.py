"""Event creation, compatibility selection and pagination for concurrent nights."""
import base64
import json
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from cmc_shared import (ApiError, club_pk, table, normalize_planning_input, new_id, now_iso,
                        get_item, public_movie_night)


def all_items(pk, prefix):
    kwargs = {"KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with(prefix), "ConsistentRead": True}
    items = []
    while True:
        page = table().query(**kwargs)
        items.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def compatibility_order(night):
    start = (night.get("confirmedShowtime") or {}).get("startsAtUtc") or (night.get("confirmedShowtime") or {}).get("startsAt")
    date = start or night.get("targetDate") or ""
    return (0 if night.get("status") == "confirmed" else 1 if date else 2, date, night["movieNightId"])


def night_order(night):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from cmc_shared import parse_iso_datetime
    showtime = night.get("confirmedShowtime") or {}
    start = parse_iso_datetime(showtime.get("startsAtUtc") or showtime.get("startsAt"))
    date = night.get("targetDate") or night.get("dateWindowStart")
    if not start and date:
        try:
            start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=ZoneInfo(night.get("timezone") or "America/Chicago"))
        except (ValueError, ZoneInfoNotFoundError):
            start = parse_iso_datetime(date)
    key = start.astimezone(timezone.utc).isoformat() if start else ""
    return (0 if start else 1, key, night["movieNightId"])


def upcoming_nights(club_id):
    return sorted([n for n in all_items(club_pk(club_id), "MOVIE_NIGHT#") if n.get("status") in {"planning", "voting", "confirmed"}], key=night_order)


def paginate(items, event, context, key):
    query = event.get("queryStringParameters") or {}
    try:
        limit = int(query.get("limit", 50))
        if not 1 <= limit <= 100:
            raise ValueError()
        cursor = query.get("cursor")
        after = None
        if cursor:
            if len(cursor) > 2048:
                raise ValueError()
            value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if value["context"] != context or not isinstance(value["key"], list):
                raise ValueError()
            after = tuple(value["key"])
            if items and (len(after) != len(key(items[0])) or any(type(a) is not type(b) for a, b in zip(after, key(items[0])))):
                raise ValueError()
        remaining = [item for item in items if after is None or key(item) > after]
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ApiError(400, "Invalid cursor or limit.") from exc
    page = remaining[:limit]
    next_cursor = None
    if len(remaining) > limit:
        next_cursor = base64.urlsafe_b64encode(json.dumps({"context": context, "key": key(page[-1])}).encode()).decode()
    return page, next_cursor


def event_detail(night, membership, user_id, include_showtimes=True):
    identifier = night["movieNightId"]
    statuses = {"imported", "approved", "rejected"} if membership.get("role") == "admin" and night.get("status") == "planning" else {"approved"}
    vote = get_item(f"MOVIE_NIGHT#{identifier}", f"VOTE#{user_id}")
    rsvp = get_item(f"MOVIE_NIGHT#{identifier}", f"RSVP#{user_id}")
    return {"movieNight": public_movie_night(night), "showtimes": [public_movie_night(s) for s in all_items(f"MOVIE_NIGHT#{identifier}", "SHOWTIME#") if s.get("status", "approved") in statuses] if include_showtimes else [],
            "currentUserVote": public_movie_night(vote) if vote else None, "currentUserRsvp": public_movie_night(rsvp) if rsvp else None,
            "currentUserRole": membership.get("role"), "currentUserAcknowledgement": public_movie_night(get_item(f"MOVIE_NIGHT#{identifier}", f"ACK#{user_id}") or {})}


def should_monitor(movie):
    release = str(movie.get("releaseDate") or "")
    return movie.get("status") == "coming_soon" or bool(release and release > datetime.now(timezone.utc).date().isoformat())


def build_night(club_id, user_id, payload, movie):
    planning = normalize_planning_input(payload)
    target_date = planning.get("targetDate")
    if not target_date:
        raise ApiError(400, "targetDate is required.")
    if payload.get("movieSelectionMode", "admin_selected") != "admin_selected":
        raise ApiError(400, "Only admin_selected movie selection is supported.")
    movie_night_id = new_id("mn")
    created_at = now_iso()
    item = {
        "PK": club_pk(club_id),
        "SK": f"MOVIE_NIGHT#{movie_night_id}",
        "GSI1PK": f"CLUB#{club_id}#STATUS#planning",
        "GSI1SK": f"START#{target_date}#MOVIE_NIGHT#{movie_night_id}",
        "GSI2PK": f"MOVIE_NIGHT#{movie_night_id}",
        "GSI2SK": "META",
        "clubId": club_id,
        "movieNightId": movie_night_id,
        "status": "planning",
        "movieSelectionMode": payload.get("movieSelectionMode", "admin_selected"),
        "movie": movie,
        **planning,
        "showtimeImportStatus": "idle",
        "lastShowtimeImportSummary": {},
        "createdAt": created_at,
        "createdBy": user_id,
        "updatedAt": created_at,
    }
    monitor_item = None
    if should_monitor(movie):
        monitoring = {"status": "active", "nextCheckAt": created_at, "resultCount": 0}
        item["showtimeMonitoring"] = monitoring
        monitor_item = {
            "PK": "SHOWTIME_MONITOR",
            "SK": f"CHECK#{created_at}#MOVIE_NIGHT#{movie_night_id}",
            "movieNightId": movie_night_id,
            "clubId": club_id,
            "status": "active",
            "nextCheckAt": created_at,
            "createdAt": created_at,
            "updatedAt": created_at,
        }
    item["version"] = 1
    return item, ([{"Item": item, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}] +
                  ([{"Item": monitor_item, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}] if monitor_item else []))


def member_check(club_id, user_id, membership):
    return {"Key": {"PK": club_pk(club_id), "SK": f"MEMBER#{user_id}"},
            "ConditionExpression": "#role = :role AND (attribute_not_exists(#status) OR #status = :active)",
            "ExpressionAttributeNames": {"#role": "role", "#status": "status"},
            "ExpressionAttributeValues": {":role": membership["role"], ":active": "active"}}


def add_conflicts(nights, personal=False):
    from datetime import timedelta
    from cmc_shared import parse_iso_datetime
    eligible = [n for n in nights if n.get("status") == "confirmed" and
                (not personal or (n.get("currentUserRsvp") or {}).get("status") in {"going", "maybe"})]
    for night in nights:
        night["conflicts"] = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1:]:
            first, second = left, right
            start = parse_iso_datetime((first.get("confirmedShowtime") or {}).get("startsAtUtc"))
            other = parse_iso_datetime((second.get("confirmedShowtime") or {}).get("startsAtUtc"))
            if not start or not other:
                continue
            if start > other:
                first, second, start, other = second, first, other, start
            runtime = (first.get("movie") or {}).get("runtime")
            known = isinstance(runtime, (int, float)) or hasattr(runtime, "as_tuple")
            known = known and runtime > 0
            if known and start + timedelta(minutes=float(runtime)) <= other:
                continue
            uncertain = not known and start != other
            left["conflicts"].append({"movieNightId": right["movieNightId"], "uncertain": uncertain})
            right["conflicts"].append({"movieNightId": left["movieNightId"], "uncertain": uncertain})
    return nights
