from cmc_shared import ADMIN_ROLES, ApiError, claims, handle, now_iso, parse_body, path_param, require_movie_night_membership, response
from cmc_lifecycle import check_expected, commit, revision, retry_record


@handle
def handler(event, context):
    user = claims(event)
    night, membership = require_movie_night_membership(path_param(event, "movieNightId"), user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    retry, previous = retry_record(night, user["userId"], "complete", payload)
    if previous:
        return response(200, {"movieNight": previous["result"]})
    check_expected(night, payload)
    if night["status"] not in {"confirmed"}:
        raise ApiError(409, "Movie night cannot be completed from its current state.")
    updated = {**night, "status": "completed", "GSI1PK": f"CLUB#{night['clubId']}#STATUS#completed",
               "completedAt": now_iso(), "completedBy": user["userId"]}

    result = commit(night, updated, user["userId"], membership, "complete", retry, None)
    return response(200, {"movieNight": result})
