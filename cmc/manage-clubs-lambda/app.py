import re

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from cmc_availability import enqueue_availability_sync
from cmc_events import upcoming_nights, compatibility_order
from cmc_shared import (
    ApiError,
    claims,
    club_pk,
    handle,
    is_platform_admin,
    new_id,
    now_iso,
    parse_body,
    public_club,
    require_membership,
    require_platform_admin,
    response,
    table,
)


SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value):
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:48] or new_id("club")


def list_user_clubs(user_id):
    result = table().query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_id}"),
    )
    clubs = []
    for membership in result.get("Items", []):
        club_id = membership.get("clubId")
        if not club_id or not str(membership.get("SK", "")).startswith("MEMBER#"):
            continue
        membership = table().get_item(Key={"PK": club_pk(club_id), "SK": membership["SK"]}, ConsistentRead=True).get("Item")
        if not membership or membership.get("status", "active") != "active":
            continue
        club = table().get_item(Key={"PK": club_pk(club_id), "SK": "META"}).get("Item")
        if club:
            nights = sorted(upcoming_nights(club_id), key=compatibility_order)
            clubs.append({**public_club(club, membership), "activeStatus": nights[0]["status"] if nights else None,
                          "upcomingNightCount": len(nights), "nextMovieNight": public_club(nights[0]) if nights else None})
    return sorted(clubs, key=lambda club: club.get("name", "").lower())


def create_club(event, user):
    require_platform_admin(user)
    payload = parse_body(event)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "name is required.")
    club_id = str(payload.get("clubId") or slugify(name)).strip()
    created_at = now_iso()
    club_item = {
        "PK": club_pk(club_id),
        "SK": "META",
        "clubId": club_id,
        "name": name,
        "createdBy": user["userId"],
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    membership_item = {
        "PK": club_pk(club_id),
        "SK": f"MEMBER#{user['userId']}",
        "GSI1PK": f"USER#{user['userId']}",
        "GSI1SK": f"CLUB#{club_id}",
        "clubId": club_id,
        "userId": user["userId"],
        "email": user.get("email") or "",
        "name": user.get("name") or "",
        "role": "admin",
        "status": "active",
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    try:
        table().put_item(
            Item=club_item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        table().put_item(
            Item=membership_item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise ApiError(409, "A club with this id already exists.") from exc
        raise
    return response(201, {"club": public_club(club_item, membership_item)})


def update_my_membership(event, user):
    club_id = str((event.get("pathParameters") or {}).get("clubId") or "").strip()
    if not club_id:
        raise ApiError(400, "clubId is required.")
    membership = require_membership(club_id, user["userId"])
    payload = parse_body(event)
    share = payload.get("shareCalendarAvailability")
    if not isinstance(share, bool):
        raise ApiError(400, "shareCalendarAvailability must be a boolean.")
    membership = {**membership, "shareCalendarAvailability": share, "updatedAt": now_iso()}
    table().put_item(Item=membership)
    enqueue_availability_sync(user_id=user["userId"], reason="club_sharing_changed")
    return response(200, {"membership": {
        "clubId": club_id,
        "userId": user["userId"],
        "role": membership.get("role"),
        "status": membership.get("status", "active"),
        "shareCalendarAvailability": share,
        "updatedAt": membership["updatedAt"],
    }})


@handle
def handler(event, context):
    user = claims(event)
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    path = event.get("path") or event.get("rawPath") or ""
    if method == "PATCH" and path.rstrip("/").endswith("/members/me"):
        return update_my_membership(event, user)
    if method == "POST":
        return create_club(event, user)
    return response(200, {"clubs": list_user_clubs(user["userId"]), "isPlatformAdmin": is_platform_admin(user)})
