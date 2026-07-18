from botocore.exceptions import ClientError

from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    get_showtime,
    handle,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    require_movie_night_membership,
    response,
    transact_update_items,
    voting_is_closed,
)


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    current_status = movie_night.get("status")
    if current_status == "voting" and not voting_is_closed(movie_night):
        raise ApiError(409, "Voting must be closed before confirming a showtime.")
    if current_status not in {"voting", "confirmed"}:
        raise ApiError(409, "Movie night cannot be confirmed from its current state.")

    payload = parse_body(event)
    showtime_id = payload.get("showtimeId") or payload.get("confirmedShowtimeId")
    if not showtime_id:
        raise ApiError(400, "showtimeId is required.")
    showtime = get_showtime(movie_night_id, str(showtime_id))
    if not showtime:
        raise ApiError(400, "Selected showtime is not attached to this movie night.")
    if showtime.get("status", "approved") != "approved":
        raise ApiError(400, "Selected showtime is not approved for voting.")

    if current_status == "confirmed" and str(movie_night.get("confirmedShowtimeId")) == str(showtime_id):
        return confirmation_response(movie_night)

    updated_at = now_iso()
    confirmed_snapshot = public_movie_night(showtime)
    is_initial_confirmation = current_status == "voting"
    sequence = 0 if is_initial_confirmation else int(movie_night.get("calendarSequence", 0)) + 1
    confirmed_at = updated_at if is_initial_confirmation else movie_night.get("confirmedAt") or updated_at
    movie_update = {
        "Key": {"PK": movie_night["PK"], "SK": movie_night["SK"]},
        "UpdateExpression": (
            "SET #status = :status, GSI1PK = :gsi1pk, confirmedShowtimeId = :showtimeId, "
            "confirmedShowtime = :showtime, confirmedAt = :confirmedAt, confirmedBy = :confirmedBy, "
            "calendarSequence = :sequence, updatedAt = :updatedAt"
        ),
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":status": "confirmed",
            ":expectedStatus": current_status,
            ":gsi1pk": f"CLUB#{movie_night['clubId']}#STATUS#confirmed",
            ":showtimeId": str(showtime_id),
            ":showtime": confirmed_snapshot,
            ":confirmedAt": confirmed_at,
            ":confirmedBy": user["userId"],
            ":sequence": sequence,
            ":updatedAt": updated_at,
        },
        "ConditionExpression": "#status = :expectedStatus",
    }
    if not is_initial_confirmation:
        movie_update["ExpressionAttributeValues"][":expectedShowtimeId"] = str(movie_night.get("confirmedShowtimeId"))
        movie_update["ConditionExpression"] += " AND confirmedShowtimeId = :expectedShowtimeId"

    updates = [movie_update]
    if is_initial_confirmation:
        updates.append(
            {
                "Key": {"PK": f"CLUB#{movie_night['clubId']}", "SK": "ACTIVE_MOVIE_NIGHT"},
                "UpdateExpression": "SET #status = :status, updatedAt = :updatedAt",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":status": "confirmed",
                    ":expectedStatus": "voting",
                    ":movieNightId": movie_night_id,
                    ":updatedAt": updated_at,
                },
                "ConditionExpression": "movieNightId = :movieNightId AND #status = :expectedStatus",
            }
        )

    try:
        transact_update_items(updates)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "TransactionCanceledException":
            latest, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
            if latest.get("status") == "confirmed" and str(latest.get("confirmedShowtimeId")) == str(showtime_id):
                return confirmation_response(latest)
            raise ApiError(409, "Movie night confirmation changed. Reload and try again.") from exc
        raise

    updated_movie_night = {
        **movie_night,
        "status": "confirmed",
        "GSI1PK": f"CLUB#{movie_night['clubId']}#STATUS#confirmed",
        "confirmedShowtimeId": str(showtime_id),
        "confirmedShowtime": confirmed_snapshot,
        "confirmedAt": confirmed_at,
        "confirmedBy": user["userId"],
        "calendarSequence": sequence,
        "updatedAt": updated_at,
    }
    return confirmation_response(updated_movie_night)


def confirmation_response(movie_night):
    public = public_movie_night(movie_night)
    return response(
        200,
        {
            "movieNight": public,
            "movieNightId": public["movieNightId"],
            "status": "confirmed",
            "confirmedShowtime": public.get("confirmedShowtime"),
        },
    )
