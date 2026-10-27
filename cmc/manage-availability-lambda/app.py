from botocore.exceptions import ClientError

from cmc_availability import calendar_result_is_fresh, emit_calendar_metrics, normalize_manual_overrides, resolve_status, scheduling_preferences, showtime_window
from cmc_shared import (
    ApiError,
    PARTICIPANT_ROLES,
    claims,
    club_pk,
    get_item,
    handle,
    list_showtimes_by_status,
    movie_night_pk,
    now_iso,
    parse_body,
    path_param,
    query_items,
    require_movie_night_membership,
    response,
    table,
    transact_write_items,
    voting_is_closed,
)


def availability_revision(movie_night):
    return int(movie_night.get("availabilityRevision", 1))


def active_members(club_id):
    return [
        member
        for member in query_items(club_pk(club_id), "MEMBER#")
        if member.get("status", "active") == "active" and member.get("role") in PARTICIPANT_ROLES
    ]


def display_name(member):
    name = str(member.get("name") or "").strip()
    if name:
        return name
    email = str(member.get("email") or "").strip()
    if email:
        return email.split("@", 1)[0]
    return "Club member"


def public_overrides(record, revision):
    if int((record or {}).get("availabilityRevision", 0)) != revision:
        return []
    return [
        {"showtimeId": showtime_id, "status": status}
        for showtime_id, status in sorted((record.get("manualOverrides") or {}).items())
    ]


def get_availability(movie_night, viewer_id, viewer_membership):
    revision = availability_revision(movie_night)
    showtimes = sorted(
        list_showtimes_by_status(movie_night["movieNightId"], {"approved"}),
        key=lambda item: item.get("startsAtUtc") or item.get("startsAt") or "",
    )
    members = active_members(movie_night["clubId"])
    records = {
        member["userId"]: get_item(movie_night_pk(movie_night["movieNightId"]), f"AVAILABILITY#{member['userId']}") or {}
        for member in members
    }
    preferences = {
        member["userId"]: scheduling_preferences(get_item(f"USER#{member['userId']}", "PREFERENCES") or {})
        for member in members
    }
    integrations = {
        member["userId"]: get_item(f"USER#{member['userId']}", "CALENDAR#GOOGLE") or {}
        for member in members
    }

    showtime_rows = []
    stale_assessments = 0
    for showtime in showtimes:
        statuses = []
        counts = {"available": 0, "maybe": 0, "unavailable": 0, "unknown": 0}
        for member in members:
            member_id = member["userId"]
            status = resolve_status(
                showtime=showtime,
                movie=movie_night.get("movie") or {},
                preferences=preferences[member_id],
                membership=member,
                availability=records[member_id],
                integration=integrations[member_id],
                revision=revision,
            )
            if (
                integrations[member_id].get("status") == "connected"
                and integrations[member_id].get("selectedCalendarIds")
                and records[member_id].get("calendarSyncStatus") in {"current", "partial"}
                and not calendar_result_is_fresh(records[member_id])
            ):
                stale_assessments += 1
            counts[status] += 1
            statuses.append({"displayName": display_name(member), "status": status})
        viewer_preferences = preferences.get(viewer_id, scheduling_preferences({}))
        interval = showtime_window(showtime, movie_night.get("movie") or {}, viewer_preferences)
        showtime_rows.append({
            "showtimeId": showtime["showtimeId"],
            "startsAtUtc": showtime.get("startsAtUtc") or showtime.get("startsAt"),
            "runtimeEstimated": bool(interval and interval["runtimeEstimated"]),
            "counts": counts,
            "members": statuses,
        })

    best = None
    if showtime_rows:
        best_row = max(
            showtime_rows,
            key=lambda row: (row["counts"]["available"], row["counts"]["maybe"]),
        )
        if best_row["counts"]["available"] or best_row["counts"]["maybe"]:
            best = best_row["showtimeId"]
    viewer_record = records.get(viewer_id, {})
    viewer_integration = integrations.get(viewer_id, {})
    viewer_member = next((member for member in members if member["userId"] == viewer_id), {})
    viewer_member_index = next((index for index, member in enumerate(members) if member["userId"] == viewer_id), -1)
    if stale_assessments:
        emit_calendar_metrics(StaleAssessmentCount=stale_assessments)
    return response(200, {
        "availabilityRevision": revision,
        "bestFitShowtimeId": best if viewer_membership.get("role") == "admin" else None,
        "showtimes": showtime_rows,
        "viewer": {
            "memberIndex": viewer_member_index,
            "manualOverrides": public_overrides(viewer_record, revision),
            "shareCalendarAvailability": viewer_member.get("shareCalendarAvailability", False),
            "calendarStatus": viewer_integration.get("status", "disconnected"),
            "calendarSyncedAt": viewer_record.get("calendarSyncedAt"),
            "calendarSyncStatus": viewer_record.get("calendarSyncStatus", "not_synced"),
        },
    })


def require_editable(movie_night):
    if movie_night.get("status") not in {"planning", "voting"}:
        raise ApiError(409, "Availability can only be changed while planning or voting is open.")
    if movie_night.get("status") == "voting" and voting_is_closed(movie_night):
        raise ApiError(409, "Availability is closed because voting has ended.")


def replace_my_availability(movie_night, user_id, payload):
    require_editable(movie_night)
    revision = availability_revision(movie_night)
    if type(payload.get("availabilityRevision")) is not int or payload["availabilityRevision"] != revision:
        raise ApiError(409, "Showtime availability changed. Reload before saving.")
    valid_ids = {item["showtimeId"] for item in list_showtimes_by_status(movie_night["movieNightId"], {"approved"})}
    overrides = normalize_manual_overrides(payload.get("overrides", []), valid_ids)
    key = {"PK": movie_night_pk(movie_night["movieNightId"]), "SK": f"AVAILABILITY#{user_id}"}
    existing = get_item(key["PK"], key["SK"]) or {}
    if int(existing.get("availabilityRevision", 0)) != revision:
        existing = {field: value for field, value in existing.items() if field not in {"calendarStatuses", "calendarSyncedAt", "calendarSyncStatus"}}
        existing["calendarSyncStatus"] = "not_synced"
    item = {
        **existing,
        **key,
        "entityType": "movieNightAvailability",
        "movieNightId": movie_night["movieNightId"],
        "clubId": movie_night["clubId"],
        "userId": user_id,
        "availabilityRevision": revision,
        "manualOverrides": overrides,
        "updatedAt": now_iso(),
    }
    try:
        transact_write_items(
            puts=[{"Item": item}],
            checks=[{
                "Key": {"PK": movie_night["PK"], "SK": movie_night["SK"]},
                "ConditionExpression": "availabilityRevision = :revision",
                "ExpressionAttributeValues": {":revision": revision},
            }],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            raise ApiError(409, "Showtime availability changed. Reload before saving.") from exc
        raise
    return response(200, {"availability": {
        "movieNightId": movie_night["movieNightId"],
        "availabilityRevision": revision,
        "overrides": public_overrides(item, revision),
        "updatedAt": item["updatedAt"],
    }})


def clear_my_availability(movie_night, user_id):
    require_editable(movie_night)
    key = {"PK": movie_night_pk(movie_night["movieNightId"]), "SK": f"AVAILABILITY#{user_id}"}
    existing = get_item(key["PK"], key["SK"])
    if existing:
        existing = {**existing, "manualOverrides": {}, "updatedAt": now_iso()}
        table().put_item(Item=existing)
    return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"}, "body": ""}


@handle
def handler(event, context):
    user = claims(event)
    movie_night, membership = require_movie_night_membership(path_param(event, "movieNightId"), user["userId"])
    method = (event.get("httpMethod") or "GET").upper()
    if method == "GET":
        return get_availability(movie_night, user["userId"], membership)
    if method == "PUT":
        return replace_my_availability(movie_night, user["userId"], parse_body(event))
    if method == "DELETE":
        return clear_my_availability(movie_night, user["userId"])
    raise ApiError(405, "Method not allowed.")
