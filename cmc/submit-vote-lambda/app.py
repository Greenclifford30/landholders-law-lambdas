from cmc_shared import (
    ApiError,
    claims,
    get_showtime,
    handle,
    movie_night_pk,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    put_item,
    require_movie_night_membership,
    response,
)


CLOSED_STATUSES = {"confirmed", "completed", "cancelled"}


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"])
    if movie_night.get("status") != "voting":
        raise ApiError(409, "Voting is not open for this movie night.")
    if movie_night.get("status") in CLOSED_STATUSES:
        raise ApiError(409, "Voting is closed for this movie night.")
    voting_closes_at = movie_night.get("votingClosesAt")
    if voting_closes_at and now_iso() > voting_closes_at:
        raise ApiError(409, "Voting has closed for this movie night.")

    payload = parse_body(event)
    rankings = payload.get("rankings") or payload.get("rankedShowtimeIds")
    if not isinstance(rankings, list) or not 1 <= len(rankings) <= 3:
        raise ApiError(400, "rankings must contain 1 to 3 showtime IDs.")
    ranked_ids = [str(item).strip() for item in rankings if str(item).strip()]
    if len(ranked_ids) != len(rankings) or len(set(ranked_ids)) != len(ranked_ids):
        raise ApiError(400, "rankings must not contain blank or duplicate showtime IDs.")
    for showtime_id in ranked_ids:
        showtime = get_showtime(movie_night_id, showtime_id)
        if not showtime:
            raise ApiError(400, f"Showtime {showtime_id} is not attached to this movie night.")
        if showtime.get("status", "approved") != "approved":
            raise ApiError(400, f"Showtime {showtime_id} is not approved for voting.")

    saved_at = now_iso()
    item = {
        "PK": movie_night_pk(movie_night_id),
        "SK": f"VOTE#{user['userId']}",
        "GSI1PK": f"MOVIE_NIGHT#{movie_night_id}#VOTES",
        "GSI1SK": f"USER#{user['userId']}",
        "movieNightId": movie_night_id,
        "userId": user["userId"],
        "rankings": ranked_ids,
        "updatedAt": saved_at,
    }
    put_item(item)
    return response(200, {"vote": public_movie_night(item)})
