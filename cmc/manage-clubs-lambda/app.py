import re

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

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
        club = table().get_item(Key={"PK": club_pk(club_id), "SK": "META"}).get("Item")
        if club:
            clubs.append(public_club(club, membership))
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


@handle
def handler(event, context):
    user = claims(event)
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    if method == "POST":
        return create_club(event, user)
    return response(200, {"clubs": list_user_clubs(user["userId"]), "isPlatformAdmin": is_platform_admin(user)})
