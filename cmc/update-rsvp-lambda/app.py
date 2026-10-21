from botocore.exceptions import ClientError
from cmc_events import member_check
from cmc_lifecycle import revision, version_check
from cmc_shared import (
    ApiError,
    claims,
    handle,
    movie_night_pk,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    transact_write_items,
    require_movie_night_membership,
    response,
)


VALID_RSVP_STATUSES = {"going", "maybe", "not_going"}
VALID_TICKET_STATUSES = {"not_purchased", "purchased"}


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, membership = require_movie_night_membership(movie_night_id, user["userId"])
    if movie_night.get("status") != "confirmed":
        raise ApiError(409, "RSVP is available after the movie night is confirmed.")
    payload = parse_body(event)
    current_revision = revision(movie_night)
    requested_revision = payload.get("planRevision", 1)
    if type(requested_revision) is not int or requested_revision != current_revision:
        raise ApiError(409, "The plan changed. Reload before submitting your RSVP and ticket status.")
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
        "rsvpPlanRevision": current_revision,
        "ticketPlanRevision": current_revision,
        "status": status,
        "ticketStatus": ticket_status,
        "updatedAt": updated_at,
    }
    try:
        transact_write_items(puts=[{"Item": item}], checks=[version_check(movie_night), member_check(movie_night["clubId"], user["userId"], membership)])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            raise ApiError(409, "The plan changed. Reload and try again.") from exc
        raise
    return response(200, {"rsvp": public_movie_night(item)})
