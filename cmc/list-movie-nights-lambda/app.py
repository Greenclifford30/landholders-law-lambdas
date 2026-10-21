from datetime import datetime, timedelta, timezone
from boto3.dynamodb.conditions import Key
from cmc_shared import (ApiError, claims, get_item, handle, parse_body, path_param, require_membership,
                        require_movie_night_membership, response, public_movie_night, table, transact_write_items, now_iso)
from cmc_events import upcoming_nights, all_items, paginate, night_order, event_detail, member_check, add_conflicts
from cmc_lifecycle import edit_planning, revision, version_check
from botocore.exceptions import ClientError


def user_memberships(user_id):
    kwargs = {"IndexName": "GSI1", "KeyConditionExpression": Key("GSI1PK").eq(f"USER#{user_id}")}
    result = []
    while True:
        page = table().query(**kwargs)
        for entry in page.get("Items", []):
            if not entry.get("clubId") or not str(entry.get("SK", "")).startswith("MEMBER#"):
                continue
            membership = get_item(f"CLUB#{entry['clubId']}", f"MEMBER#{user_id}")
            if membership and membership.get("status", "active") == "active" and membership.get("role") in {"admin", "friend"}:
                result.append(membership)
        if not page.get("LastEvaluatedKey"):
            return result
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def summary(night, membership, user_id):
    detail = event_detail(night, membership, user_id, include_showtimes=False)
    result = {**detail["movieNight"], "currentUserVote": detail["currentUserVote"], "currentUserRsvp": detail["currentUserRsvp"],
              "currentUserAcknowledgement": detail["currentUserAcknowledgement"]}
    actions = []
    if night["status"] == "voting" and not night.get("votingClosedAt"):
        from cmc_shared import voting_is_closed
        if not voting_is_closed(night):
            actions.append("edit_vote" if detail["currentUserVote"] else "vote")
    if night["status"] == "confirmed":
        rsvp = detail["currentUserRsvp"] or {}
        if not rsvp or int(rsvp.get("rsvpPlanRevision", 1)) < revision(night):
            actions.append("rsvp")
        if rsvp and int(rsvp.get("ticketPlanRevision", 1)) < revision(night):
            actions.append("review_tickets")
    if night["status"] in {"confirmed", "cancelled"} and revision(night) > 1:
        ack = detail["currentUserAcknowledgement"] or {}
        if int(ack.get("acknowledgedPlanRevision", 0)) < revision(night):
            actions.append("acknowledge_plan")
    result["nextActions"] = actions
    return result


def agenda(event, user_id):
    scope = (event.get("queryStringParameters") or {}).get("scope", "upcoming")
    if scope not in {"upcoming", "recent"}:
        raise ApiError(400, "scope must be upcoming or recent.")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    items = []
    for member in user_memberships(user_id):
        club_id = member["clubId"]
        club = get_item(f"CLUB#{club_id}", "META") or {}
        nights = upcoming_nights(club_id) if scope == "upcoming" else [n for n in all_items(f"CLUB#{club_id}", "MOVIE_NIGHT#") if n.get("status") == "completed" and n.get("completedAt", "") >= cutoff]
        items.extend({**summary(n, member, user_id), "clubName": club.get("name", "Movie club")} for n in nights)
    add_conflicts(items, personal=True)
    items.sort(key=night_order)
    page, cursor = paginate(items, event, f"agenda:{user_id}:{scope}", night_order)
    return response(200, {"movieNights": page, "nextCursor": cursor})


def acknowledge(night, membership, user_id, payload):
    if night["status"] not in {"confirmed", "cancelled"} or type(payload.get("planRevision")) is not int or payload["planRevision"] != revision(night):
        raise ApiError(409, "The plan changed. Reload before acknowledging it.")
    item = {"PK": f"MOVIE_NIGHT#{night['movieNightId']}", "SK": f"ACK#{user_id}", "movieNightId": night["movieNightId"],
            "userId": user_id, "acknowledgedPlanRevision": revision(night), "updatedAt": now_iso()}
    try:
        transact_write_items(puts=[{"Item": item}], checks=[version_check(night), member_check(night["clubId"], user_id, membership)])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            raise ApiError(409, "The plan changed. Reload and try again.") from exc
        raise
    return response(200, {"acknowledgedPlanRevision": revision(night)})


@handle
def handler(event, context):
    user = claims(event)
    path = event.get("path") or event.get("rawPath") or ""
    if path.rstrip("/").endswith("/me/movie-nights"):
        return agenda(event, user["userId"])
    if (event.get("pathParameters") or {}).get("movieNightId"):
        night, membership = require_movie_night_membership(path_param(event, "movieNightId"), user["userId"])
        if path.endswith("/plan-acknowledgement/me"):
            return acknowledge(night, membership, user["userId"], parse_body(event))
        if event.get("httpMethod") == "PATCH":
            if membership.get("role") != "admin":
                raise ApiError(403, "Only club admins can edit planning.")
            return response(200, {"movieNight": edit_planning(night, parse_body(event), user["userId"], membership)})
        return response(200, event_detail(night, membership, user["userId"]))
    club_id = path_param(event, "clubId")
    membership = require_membership(club_id, user["userId"], {"admin", "friend"})
    if (event.get("queryStringParameters") or {}).get("scope", "upcoming") != "upcoming":
        raise ApiError(400, "scope must be upcoming.")
    items = add_conflicts([summary(n, membership, user["userId"]) for n in upcoming_nights(club_id)])
    nights, cursor = paginate(items, event, f"nights:{club_id}", night_order)
    return response(200, {"movieNights": nights, "nextCursor": cursor})
