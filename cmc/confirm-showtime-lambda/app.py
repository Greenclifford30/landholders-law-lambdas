from cmc_shared import (ADMIN_ROLES, ApiError, claims, get_showtime, handle, now_iso, parse_body,
                        path_param, public_movie_night, require_movie_night_membership, response, voting_is_closed)
from cmc_lifecycle import check_expected, commit, revision, retry_record, save_noop


def material_plan(showtime):
    from cmc_shared import parse_iso_datetime
    start = parse_iso_datetime(showtime.get("startsAtUtc") or showtime.get("startsAt"))
    theater = showtime.get("providerTheaterId") or showtime.get("externalTheaterId") or (
        str(showtime.get("theaterName") or "").strip().casefold(),
        str(showtime.get("theaterAddress") or showtime.get("theaterLocation") or "").strip().casefold())
    return theater, start, str(showtime.get("screenFormat") or "Standard").strip().casefold()


@handle
def handler(event, context):
    identifier = path_param(event, "movieNightId")
    user = claims(event)
    night, membership = require_movie_night_membership(identifier, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    retry, previous = retry_record(night, user["userId"], "confirm", payload)
    if previous:
        return confirmation_response(previous["result"])
    check_expected(night, payload)
    if night["status"] == "voting" and not voting_is_closed(night):
        raise ApiError(409, "Voting must be closed before confirming a showtime.")
    if night["status"] not in {"voting", "confirmed"}:
        raise ApiError(409, "Movie night cannot be confirmed from its current state.")
    showtime = get_showtime(identifier, str(payload.get("showtimeId") or payload.get("confirmedShowtimeId") or ""))
    if not showtime or showtime.get("status", "approved") != "approved":
        raise ApiError(400, "Select an approved showtime attached to this movie night.")
    snapshot = public_movie_night(showtime)
    if night["status"] == "confirmed" and material_plan(night.get("confirmedShowtime") or {}) == material_plan(snapshot):
        save_noop(night, user["userId"], membership, retry)
        return confirmation_response(night)
    initial = night["status"] == "voting"
    reason = payload.get("changeReason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 1000):
        raise ApiError(400, "changeReason must be at most 1000 characters.")
    updated = {**night, "status": "confirmed", "GSI1PK": f"CLUB#{night['clubId']}#STATUS#confirmed",
               "confirmedShowtimeId": showtime["showtimeId"], "confirmedShowtime": snapshot,
               "confirmedAt": night.get("confirmedAt") or now_iso(), "confirmedBy": user["userId"],
               "planRevision": revision(night) + 1, "calendarSequence": 0 if initial else int(night.get("calendarSequence", 0)) + 1,
               "previousPlan": None if initial else night.get("confirmedShowtime"), "changeReason": reason}
    result = commit(night, updated, user["userId"], membership, "confirm", retry,
                    "showtime_confirmed" if initial else "showtime_changed")
    return confirmation_response(result)


def confirmation_response(night):
    public = public_movie_night(night)
    return response(200, {"movieNight": public, "movieNightId": public["movieNightId"],
                          "status": public["status"], "confirmedShowtime": public.get("confirmedShowtime")})
