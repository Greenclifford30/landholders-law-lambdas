from botocore.exceptions import ClientError

from cmc_notifications import enqueue_movie_notification
from cmc_shared import ADMIN_ROLES, ApiError, claims, handle, now_iso, path_param, public_movie_night, require_movie_night_membership, response, transact_update_items


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    if movie_night.get("status") not in {"planning", "voting", "confirmed"}:
        raise ApiError(409, "Only an active movie night can be cancelled.")
    updated_at = now_iso()
    try:
        transact_update_items([
            {"Key": {"PK": movie_night["PK"], "SK": movie_night["SK"]}, "UpdateExpression": "SET #status = :status, GSI1PK = :gsi, cancelledAt = :at, cancelledBy = :by, updatedAt = :at", "ExpressionAttributeNames": {"#status": "status"}, "ExpressionAttributeValues": {":status": "cancelled", ":gsi": f"CLUB#{movie_night['clubId']}#STATUS#cancelled", ":at": updated_at, ":by": user["userId"], ":expected": movie_night["status"]}, "ConditionExpression": "#status = :expected"},
            {"Key": {"PK": f"CLUB#{movie_night['clubId']}", "SK": "ACTIVE_MOVIE_NIGHT"}, "UpdateExpression": "SET #status = :status, updatedAt = :at", "ExpressionAttributeNames": {"#status": "status"}, "ExpressionAttributeValues": {":status": "cancelled", ":at": updated_at, ":id": movie_night_id}, "ConditionExpression": "movieNightId = :id"},
        ])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            raise ApiError(409, "Movie night changed. Reload and try again.") from exc
        raise
    updated = {**movie_night, "status": "cancelled", "cancelledAt": updated_at, "cancelledBy": user["userId"], "updatedAt": updated_at}
    enqueue_movie_notification(updated, "movie_night_cancelled")
    return response(200, {"movieNight": public_movie_night(updated)})
