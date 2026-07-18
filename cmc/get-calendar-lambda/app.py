from cmc_shared import (
    ApiError,
    claims,
    get_item,
    get_showtime,
    handle,
    path_param,
    public_movie_night,
    query_gsi2_movie_night,
    response,
)


PARTICIPANT_ROLES = {"admin", "friend", "guest"}


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night = query_gsi2_movie_night(movie_night_id)
    if not movie_night:
        raise ApiError(404, "Movie night not found.")

    membership = get_item(f"CLUB#{movie_night['clubId']}", f"MEMBER#{user['userId']}")
    if not membership or membership.get("status", "active") != "active" or membership.get("role") not in PARTICIPANT_ROLES:
        raise ApiError(404, "Movie night not found.")
    if movie_night.get("status") != "confirmed":
        raise ApiError(409, "Calendar download is available after the movie night is confirmed.")

    showtime_id = movie_night.get("confirmedShowtimeId")
    if not showtime_id:
        raise ApiError(422, "Confirmed showtime is missing.")
    showtime = get_showtime(movie_night_id, str(showtime_id))
    if not showtime or not showtime.get("startsAtUtc"):
        raise ApiError(422, "Confirmed showtime record is missing.")
    if not (movie_night.get("movie") or {}).get("title"):
        raise ApiError(422, "Movie metadata is missing.")
    return response(200, {"movieNight": public_movie_night(movie_night), "showtime": public_movie_night(showtime)})
