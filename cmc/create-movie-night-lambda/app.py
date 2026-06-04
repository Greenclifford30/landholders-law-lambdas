from botocore.exceptions import ClientError
from datetime import datetime

from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    club_pk,
    handle,
    new_id,
    normalize_movie_snapshot,
    now_iso,
    parse_body,
    path_param,
    require_membership,
    require_string,
    response,
    transact_put_items,
)


@handle
def handler(event, context):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    movie = normalize_movie_snapshot(payload)
    target_date = require_string(payload, "targetDate")
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ApiError(400, "targetDate must use yyyy-mm-dd format.") from exc

    movie_night_id = payload.get("movieNightId") or new_id("mn")
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
        "targetDate": target_date,
        "createdAt": created_at,
        "createdBy": user["userId"],
        "updatedAt": created_at,
    }
    pointer_item = {
        "PK": club_pk(club_id),
        "SK": "ACTIVE_MOVIE_NIGHT",
        "clubId": club_id,
        "movieNightId": movie_night_id,
        "status": "planning",
        "targetDate": target_date,
        "updatedAt": created_at,
    }

    try:
        transact_put_items(
            [
                {
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                },
                {
                    "Item": pointer_item,
                    "ConditionExpression": (
                        "attribute_not_exists(PK) OR NOT (#status IN (:planning, :voting, :confirmed))"
                    ),
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        ":planning": "planning",
                        ":voting": "voting",
                        ":confirmed": "confirmed",
                    },
                },
            ]
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {
            "ConditionalCheckFailedException",
            "TransactionCanceledException",
        }:
            raise ApiError(409, "Movie night already exists or club already has an active movie night.") from exc
        raise

    return response(201, {"movieNight": {k: v for k, v in item.items() if not k.startswith("GSI") and k not in {"PK", "SK"}}})
