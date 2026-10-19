from cmc_shared import ApiError, claims, handle, path_param, require_membership, require_movie_night_membership, response, public_movie_night
from cmc_events import upcoming_nights, paginate, night_order, event_detail


@handle
def handler(event, context):
    user = claims(event)
    if (event.get("pathParameters") or {}).get("movieNightId"):
        night, membership = require_movie_night_membership(path_param(event, "movieNightId"), user["userId"])
        return response(200, event_detail(night, membership, user["userId"]))
    club_id = path_param(event, "clubId")
    membership = require_membership(club_id, user["userId"], {"admin", "friend"})
    if (event.get("queryStringParameters") or {}).get("scope", "upcoming") != "upcoming":
        raise ApiError(400, "scope must be upcoming.")
    nights, cursor = paginate(upcoming_nights(club_id), event, f"nights:{club_id}", night_order)
    summaries = []
    for night in nights:
        detail = event_detail(night, membership, user["userId"], include_showtimes=False)
        summaries.append({**detail["movieNight"], "currentUserVote": detail["currentUserVote"], "currentUserRsvp": detail["currentUserRsvp"]})
    return response(200, {"movieNights": summaries, "nextCursor": cursor})
