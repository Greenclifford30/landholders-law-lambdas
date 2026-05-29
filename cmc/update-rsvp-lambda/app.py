from cmc_shared import (
    ApiError,
    claims,
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


VALID_RSVP_STATUSES = {"going", "maybe", "not_going"}
VALID_TICKET_STATUSES = {"not_purchased", "purchased"}


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"])
    if movie_night.get("status") != "confirmed":
        raise ApiError(409, "RSVP is available after the movie night is confirmed.")
    payload = parse_body(event)
    status = payload.get("status")
    ticket_status = payload.get("ticketStatus", "not_purchased")
    if status not in VALID_RSVP_STATUSES:
        raise ApiError(400, "status must be going, maybe, or not_going.")
    if ticket_status not in VALID_TICKET_STATUSES:
        raise ApiError(400, "ticketStatus must be not_purchased or purchased.")
    updated_at = now_iso()
    item = {
        "PK": movie_night_pk(movie_night_id),
        "SK": f"RSVP#{user['userId']}",
        "GSI1PK": f"MOVIE_NIGHT#{movie_night_id}#RSVPS",
        "GSI1SK": f"USER#{user['userId']}",
        "movieNightId": movie_night_id,
        "userId": user["userId"],
        "status": status,
        "ticketStatus": ticket_status,
        "updatedAt": updated_at,
    }
    put_item(item)
    return response(200, {"rsvp": public_movie_night(item)})
