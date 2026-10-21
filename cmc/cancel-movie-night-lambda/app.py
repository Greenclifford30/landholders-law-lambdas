from cmc_shared import ADMIN_ROLES, ApiError, claims, handle, now_iso, parse_body, path_param, require_movie_night_membership, response
from cmc_lifecycle import check_expected, commit, revision, retry_record


@handle
def handler(event, context):
    user = claims(event)
    night, membership = require_movie_night_membership(path_param(event, "movieNightId"), user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    retry, previous = retry_record(night, user["userId"], "cancel", payload)
    if previous:
        return response(200, {"movieNight": previous["result"]})
    check_expected(night, payload)
    if night["status"] not in {"planning", "voting", "confirmed"}:
        raise ApiError(409, "Movie night cannot be cancelled from its current state.")
    updated = {**night, "status": "cancelled", "GSI1PK": f"CLUB#{night['clubId']}#STATUS#cancelled",
               "cancelledAt": now_iso(), "cancelledBy": user["userId"]}
    updated.update(planRevision=revision(night) + 1, calendarSequence=int(night.get("calendarSequence", 0)) + 1,
                       previousPlan=night.get("confirmedShowtime"))
    result = commit(night, updated, user["userId"], membership, "cancel", retry, 'movie_night_cancelled')
    return response(200, {"movieNight": result})
