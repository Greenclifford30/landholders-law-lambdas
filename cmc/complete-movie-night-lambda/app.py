from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    club_pk,
    handle,
    now_iso,
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

    if movie_night.get("status") != "confirmed":
        raise ApiError(409, "Only confirmed movie nights can be completed.")

    updated_at = now_iso()
    table().update_item(
        Key={"PK": movie_night["PK"], "SK": movie_night["SK"]},
        UpdateExpression=(
            "SET #status = :status, GSI1PK = :gsi1pk, completedAt = :completedAt, "
            "completedBy = :completedBy, updatedAt = :updatedAt"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "completed",
            ":gsi1pk": f"CLUB#{movie_night['clubId']}#STATUS#completed",
            ":completedAt": updated_at,
            ":completedBy": user["userId"],
            ":updatedAt": updated_at,
        },
    )
    table().update_item(
        Key={"PK": club_pk(movie_night["clubId"]), "SK": "ACTIVE_MOVIE_NIGHT"},
        UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "completed", ":updatedAt": updated_at},
    )

    completed_movie_night = {
        **movie_night,
        "status": "completed",
        "GSI1PK": f"CLUB#{movie_night['clubId']}#STATUS#completed",
        "completedAt": updated_at,
        "completedBy": user["userId"],
        "updatedAt": updated_at,
    }
    return response(200, {"movieNight": public_movie_night(completed_movie_night)})
