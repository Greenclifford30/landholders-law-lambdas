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
    table,
)


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    showtime_id = payload.get("showtimeId") or payload.get("confirmedShowtimeId")
    if not showtime_id:
        raise ApiError(400, "showtimeId is required.")
    showtime = get_showtime(movie_night_id, str(showtime_id))
    if not showtime:
        raise ApiError(400, "Selected showtime is not attached to this movie night.")
    if showtime.get("status", "approved") != "approved":
        raise ApiError(400, "Selected showtime is not approved for voting.")
    updated_at = now_iso()
    confirmed_snapshot = public_movie_night(showtime)
    table().update_item(
        Key={"PK": movie_night["PK"], "SK": movie_night["SK"]},
        UpdateExpression=(
            "SET #status = :status, GSI1PK = :gsi1pk, confirmedShowtimeId = :showtimeId, "
            "confirmedShowtime = :showtime, confirmedAt = :confirmedAt, confirmedBy = :confirmedBy, updatedAt = :updatedAt"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "confirmed",
            ":gsi1pk": f"CLUB#{movie_night['clubId']}#STATUS#confirmed",
            ":showtimeId": str(showtime_id),
            ":showtime": confirmed_snapshot,
            ":confirmedAt": updated_at,
            ":confirmedBy": user["userId"],
            ":updatedAt": updated_at,
        },
    )
    table().update_item(
        Key={"PK": f"CLUB#{movie_night['clubId']}", "SK": "ACTIVE_MOVIE_NIGHT"},
        UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "confirmed", ":updatedAt": updated_at},
    )
    return response(200, {"movieNightId": movie_night_id, "status": "confirmed", "confirmedShowtime": confirmed_snapshot})
