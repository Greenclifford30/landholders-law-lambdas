from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    get_item,
    handle,
    movie_night_pk,
    new_id,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    put_item,
    require_movie_night_membership,
    response,
    table,
)


def normalize_manual_showtime(movie_night_id, raw, created_at):
    showtime_id = raw.get("showtimeId") or new_id("st")
    starts_at = raw.get("startsAtUtc") or raw.get("startsAt") or raw.get("startTime")
    theater_name = raw.get("theaterName") or raw.get("theatreName")
    if not starts_at or not theater_name:
        raise ApiError(400, "Each showtime requires startsAtUtc and theaterName.")
    return {
        "PK": movie_night_pk(movie_night_id),
        "SK": f"SHOWTIME#{showtime_id}",
        "GSI1PK": f"MOVIE_NIGHT#{movie_night_id}#SHOWTIMES",
        "GSI1SK": f"START#{starts_at}#SHOWTIME#{showtime_id}",
        "movieNightId": movie_night_id,
        "showtimeId": showtime_id,
        "provider": raw.get("provider", "manual"),
        "providerShowtimeId": raw.get("providerShowtimeId", ""),
        "providerMovieId": raw.get("providerMovieId", ""),
        "providerTheaterId": raw.get("providerTheaterId", raw.get("theatreId", "")),
        "theaterName": theater_name,
        "theaterLocation": raw.get("theaterLocation", raw.get("theatreLocation", "")),
        "startsAtUtc": starts_at,
        "localDateTime": raw.get("localDateTime", ""),
        "screenFormat": raw.get("screenFormat", "Standard"),
        "ticketURI": raw.get("ticketURI", raw.get("ticketUrl", "")),
        "quals": raw.get("quals", []),
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def from_cache(movie_night_id, cache_key, created_at):
    if not isinstance(cache_key, dict) or not cache_key.get("PK") or not cache_key.get("SK"):
        raise ApiError(400, "cachedShowtimeKeys must contain PK and SK.")
    cached = get_item(cache_key["PK"], cache_key["SK"])
    if not cached:
        raise ApiError(404, "Cached showtime was not found.")
    return normalize_manual_showtime(
        movie_night_id,
        {
            "provider": cached.get("provider", "gracenote"),
            "providerShowtimeId": cached.get("SK"),
            "providerMovieId": cached.get("tmsId") or cached.get("rootId"),
            "providerTheaterId": cached.get("theatreId"),
            "theaterName": cached.get("theatreName"),
            "startsAtUtc": cached.get("startsAtUtc"),
            "localDateTime": cached.get("localDateTime"),
            "screenFormat": cached.get("screenFormat", "Standard"),
            "ticketURI": cached.get("ticketURI", ""),
            "quals": cached.get("quals", []),
        },
        created_at,
    )


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    raw_showtimes = payload.get("showtimes") or []
    cached_keys = payload.get("cachedShowtimeKeys") or []
    if not raw_showtimes and not cached_keys:
        raise ApiError(400, "showtimes or cachedShowtimeKeys are required.")
    created_at = now_iso()
    items = [normalize_manual_showtime(movie_night_id, raw, created_at) for raw in raw_showtimes]
    items.extend(from_cache(movie_night_id, key, created_at) for key in cached_keys)
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for item in items:
            batch.put_item(Item=item)
    if movie_night.get("status") == "planning":
        table().update_item(
            Key={"PK": movie_night["PK"], "SK": movie_night["SK"]},
            UpdateExpression="SET #status = :status, GSI1PK = :gsi1pk, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "voting",
                ":gsi1pk": f"CLUB#{movie_night['clubId']}#STATUS#voting",
                ":updatedAt": created_at,
            },
        )
        table().update_item(
            Key={"PK": f"CLUB#{movie_night['clubId']}", "SK": "ACTIVE_MOVIE_NIGHT"},
            UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "voting", ":updatedAt": created_at},
        )
    return response(201, {"showtimes": [public_movie_night(item) for item in items]})
