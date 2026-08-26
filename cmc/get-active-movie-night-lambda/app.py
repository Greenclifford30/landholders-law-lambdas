from cmc_shared import (
    ApiError,
    active_pointer,
    claims,
    club_pk,
    get_item,
    handle,
    list_showtimes_by_status,
    path_param,
    public_movie_night,
    require_membership,
    response,
)


@handle
def handler(event, context):
    club_id = path_param(event, "clubId")
    user = claims(event)
    membership = require_membership(club_id, user["userId"])

    pointer = active_pointer(club_id)
    if not pointer:
        raise ApiError(404, "No active movie night exists for this club.")

    movie_night = get_item(club_pk(club_id), f"MOVIE_NIGHT#{pointer['movieNightId']}")
    if not movie_night:
        raise ApiError(404, "Active movie night record was not found.")

    movie_night_id = movie_night["movieNightId"]
    vote = get_item(f"MOVIE_NIGHT#{movie_night_id}", f"VOTE#{user['userId']}")
    rsvp = get_item(f"MOVIE_NIGHT#{movie_night_id}", f"RSVP#{user['userId']}")
    if membership.get("role") == "admin" and movie_night.get("status") == "planning":
        showtime_statuses = {"imported", "approved", "rejected"}
    else:
        showtime_statuses = {"approved"}
    return response(
        200,
        {
            "movieNight": public_movie_night(movie_night),
            "showtimes": [public_movie_night(item) for item in list_showtimes_by_status(movie_night_id, showtime_statuses)],
            "currentUserVote": public_movie_night(vote) if vote else None,
            "currentUserRsvp": public_movie_night(rsvp) if rsvp else None,
            "currentUserRole": membership.get("role"),
        },
    )
