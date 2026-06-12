import hashlib
import re
from decimal import Decimal
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    expand_date_window,
    get_item,
    handle,
    movie_night_pk,
    new_id,
    normalize_movie_snapshot,
    normalize_planning_input,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    require_movie_night_membership,
    response,
    table,
)


CLOSED_STATUSES = {"confirmed", "completed", "cancelled"}


def dynamodb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {
            key: sanitized
            for key, child in value.items()
            if (sanitized := dynamodb_value(child)) is not None
        }
    if isinstance(value, list):
        return [
            sanitized
            for child in value
            if (sanitized := dynamodb_value(child)) is not None
        ]
    return value


def sanitize_item(item):
    return {
        key: sanitized
        for key, value in item.items()
        if (sanitized := dynamodb_value(value)) is not None
    }


def normalize_title(value):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(normalized.split())


def local_parts(starts_at, local_date_time, timezone_name):
    if local_date_time:
        return local_date_time[:10], local_date_time[11:16], local_date_time
    if not starts_at:
        return "", "", ""
    raw = str(starts_at).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return "", "", ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_dt = parsed.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None, microsecond=0)
    local_iso = local_dt.isoformat()
    return local_iso[:10], local_iso[11:16], local_iso


def candidate_id(dedupe_key):
    return f"st_{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()[:16]}"


def dedupe_key_for(raw):
    provider = raw.get("provider", "manual")
    external_showtime_id = raw.get("externalShowtimeId") or raw.get("providerShowtimeId") or ""
    external_theater_id = raw.get("externalTheaterId") or raw.get("providerTheaterId") or raw.get("theatreId") or ""
    external_movie_id = raw.get("externalMovieId") or raw.get("providerMovieId") or raw.get("tmsId") or raw.get("rootId") or ""
    starts_at = raw.get("startsAt") or raw.get("startsAtUtc") or raw.get("startTime") or raw.get("localDateTime") or ""
    screen_format = raw.get("screenFormat") or "Standard"
    if external_showtime_id:
        return f"{provider}#SHOWTIME#{external_showtime_id}"
    return f"{provider}#MOVIE#{external_movie_id}#THEATER#{external_theater_id}#START#{starts_at}#FORMAT#{screen_format}"


def normalize_showtime_candidate(movie_night, raw, import_job_id, created_at, status="imported"):
    timezone_name = raw.get("timezone") or movie_night.get("timezone") or "America/Chicago"
    starts_at = raw.get("startsAt") or raw.get("startsAtUtc") or raw.get("startTime")
    theater_name = raw.get("theaterName") or raw.get("theatreName")
    if not starts_at or not theater_name:
        raise ApiError(400, "Each showtime requires startsAtUtc and theaterName.")
    local_date, local_time, local_date_time = local_parts(starts_at, raw.get("localDateTime"), timezone_name)
    dedupe_key = raw.get("dedupeKey") or dedupe_key_for(raw)
    showtime_id = raw.get("showtimeId") or candidate_id(dedupe_key)
    external_showtime_id = raw.get("externalShowtimeId") or raw.get("providerShowtimeId") or ""
    external_theater_id = raw.get("externalTheaterId") or raw.get("providerTheaterId") or raw.get("theatreId") or ""
    external_movie_id = raw.get("externalMovieId") or raw.get("providerMovieId") or raw.get("tmsId") or raw.get("rootId") or ""
    theater_location = raw.get("theaterLocation") or raw.get("theaterAddress") or raw.get("theatreLocation") or ""
    item = {
        "PK": movie_night_pk(movie_night["movieNightId"]),
        "SK": f"SHOWTIME#{showtime_id}",
        "GSI1PK": f"MOVIE_NIGHT#{movie_night['movieNightId']}#SHOWTIMES",
        "GSI1SK": f"START#{starts_at}#SHOWTIME#{showtime_id}",
        "movieNightId": movie_night["movieNightId"],
        "showtimeId": showtime_id,
        "provider": raw.get("provider", "manual"),
        "externalShowtimeId": external_showtime_id,
        "externalTheaterId": external_theater_id,
        "externalMovieId": external_movie_id,
        "providerShowtimeId": external_showtime_id,
        "providerTheaterId": external_theater_id,
        "providerMovieId": external_movie_id,
        "theaterName": theater_name,
        "theaterLocation": theater_location,
        "theaterAddress": raw.get("theaterAddress") or theater_location,
        "startsAt": starts_at,
        "startsAtUtc": starts_at,
        "localDate": local_date,
        "localTime": local_time,
        "localDateTime": local_date_time,
        "timezone": timezone_name,
        "screenFormat": raw.get("screenFormat") or "Standard",
        "amenities": raw.get("amenities", raw.get("quals", [])),
        "quals": raw.get("quals", raw.get("amenities", [])),
        "ticketURI": raw.get("ticketURI", raw.get("ticketUrl", "")),
        "importJobId": import_job_id,
        "dedupeKey": dedupe_key,
        "status": status,
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    return sanitize_item(item)


def cached_showtime_to_raw(cached):
    return {
        "provider": cached.get("provider", "gracenote"),
        "externalShowtimeId": cached.get("providerShowtimeId") or cached.get("SK"),
        "externalMovieId": cached.get("providerMovieId") or cached.get("tmsId") or cached.get("rootId"),
        "externalTheaterId": cached.get("providerTheaterId") or cached.get("theatreId"),
        "theaterName": cached.get("theaterName") or cached.get("theatreName"),
        "theaterLocation": cached.get("theaterLocation") or cached.get("theatreLocation", ""),
        "startsAtUtc": cached.get("startsAtUtc"),
        "localDateTime": cached.get("localDateTime"),
        "screenFormat": cached.get("screenFormat", "Standard"),
        "ticketURI": cached.get("ticketURI", ""),
        "quals": cached.get("quals", []),
        "tmsId": cached.get("tmsId"),
        "rootId": cached.get("rootId"),
    }


def cache_pk(zip_code, show_date):
    return f"SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#{zip_code}#DATE#{show_date}"


def title_sk_prefix(title):
    return f"TITLE#{normalize_title(title)}#"


def query_cached_showtimes(movie_night, show_date):
    planning_zip = movie_night.get("zipCode")
    if not planning_zip:
        raise ApiError(400, "zipCode must be saved before importing showtimes.")
    movie = movie_night.get("movie") or {}
    prefix = title_sk_prefix(movie.get("title"))
    items = []
    last_key = None
    key_expression = Key("PK").eq(cache_pk(planning_zip, show_date)) & Key("SK").begins_with(prefix)
    while True:
        kwargs = {"KeyConditionExpression": key_expression, "Limit": 100}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        result = table().query(**kwargs)
        items.extend(result.get("Items", []))
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break
    provider_movie_id = str(movie.get("externalId") or "")
    if provider_movie_id:
        items = [
            item
            for item in items
            if str(item.get("providerMovieId") or item.get("tmsId") or item.get("rootId") or "") in {provider_movie_id, str(item.get("tmsId") or "")}
            or normalize_title(item.get("title")) == normalize_title(movie.get("title"))
        ]
    return items


def write_candidates(movie_night, candidates):
    imported_count = 0
    duplicate_count = 0
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for candidate in candidates:
            existing = get_item(candidate["PK"], candidate["SK"])
            if existing:
                duplicate_count += 1
                candidate["createdAt"] = existing.get("createdAt", candidate.get("createdAt"))
                candidate["status"] = existing.get("status", candidate.get("status", "imported"))
            else:
                imported_count += 1
            batch.put_item(Item=candidate)
    return imported_count, duplicate_count


def update_movie_night(movie_night, fields):
    if not fields:
        return movie_night
    names = {}
    values = {}
    assignments = []
    for key, value in fields.items():
        names[f"#{key}"] = key
        values[f":{key}"] = dynamodb_value(value)
        assignments.append(f"#{key} = :{key}")
    table().update_item(
        Key={"PK": movie_night["PK"], "SK": movie_night["SK"]},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    return {**movie_night, **{key: dynamodb_value(value) for key, value in fields.items()}}


def update_active_pointer(movie_night, fields):
    if not fields:
        return
    names = {}
    values = {}
    assignments = []
    for key, value in fields.items():
        names[f"#{key}"] = key
        values[f":{key}"] = dynamodb_value(value)
        assignments.append(f"#{key} = :{key}")
    table().update_item(
        Key={"PK": f"CLUB#{movie_night['clubId']}", "SK": "ACTIVE_MOVIE_NIGHT"},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def movie_identity(movie):
    movie = movie or {}
    provider = str(movie.get("provider") or movie.get("externalProvider") or "").strip()
    external_id = str(movie.get("externalId") or movie.get("externalMovieId") or "").strip()
    title = normalize_title(movie.get("title"))
    return provider, external_id, title


def list_movie_night_children(movie_night_id, prefixes):
    items = []
    for prefix in prefixes:
        result = table().query(
            KeyConditionExpression=Key("PK").eq(movie_night_pk(movie_night_id)) & Key("SK").begins_with(prefix)
        )
        items.extend(result.get("Items", []))
    return items


def delete_movie_night_children(movie_night_id, prefixes):
    for item in list_movie_night_children(movie_night_id, prefixes):
        table().delete_item(Key={"PK": item["PK"], "SK": item["SK"]})


def handle_update_planning(movie_night, payload):
    if movie_night.get("status") != "planning":
        raise ApiError(409, "Planning can only be changed while the movie night is in setup.")
    updated_at = now_iso()
    planning = normalize_planning_input(payload.get("planning") or payload, movie_night)
    fields = {**planning, "updatedAt": updated_at}
    if "movie" in payload or "selectedMovie" in payload:
        movie = normalize_movie_snapshot(payload)
        if movie_identity(movie) != movie_identity(movie_night.get("movie")):
            delete_movie_night_children(movie_night["movieNightId"], ("SHOWTIME#", "SHOWTIME_IMPORT#"))
            fields.update(
                {
                    "movie": movie,
                    "showtimeImportStatus": "idle",
                    "lastShowtimeImportSummary": {},
                }
            )
    updated = update_movie_night(movie_night, fields)
    update_active_pointer(movie_night, {"targetDate": planning["targetDate"], "updatedAt": updated_at})
    return response(200, {"movieNight": public_movie_night(updated)})


def create_import_job(movie_night, params, requested_dates, created_at):
    import_job_id = new_id("sij")
    item = {
        "PK": movie_night_pk(movie_night["movieNightId"]),
        "SK": f"SHOWTIME_IMPORT#{import_job_id}",
        "importJobId": import_job_id,
        "movieNightId": movie_night["movieNightId"],
        "clubId": movie_night["clubId"],
        "provider": "gracenote",
        "status": "running",
        "params": params,
        "requestedDates": requested_dates,
        "resultCount": 0,
        "importedCount": 0,
        "duplicateCount": 0,
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    table().put_item(Item=sanitize_item(item))
    return item


def complete_import_job(job, fields):
    updated = {**job, **fields}
    table().put_item(Item=sanitize_item(updated))
    return updated


def handle_import(movie_night):
    if movie_night.get("status") in CLOSED_STATUSES:
        raise ApiError(409, "Showtimes cannot be imported after confirmation.")
    planning = normalize_planning_input({}, movie_night)
    if not planning.get("zipCode") or not planning.get("radiusMiles"):
        raise ApiError(400, "zipCode and radiusMiles must be saved before importing showtimes.")
    requested_dates = expand_date_window(planning["dateWindowStart"], planning["dateWindowEnd"])
    created_at = now_iso()
    params = {
        "movieExternalId": (movie_night.get("movie") or {}).get("externalId", ""),
        "zipCode": planning["zipCode"],
        "radiusMiles": planning["radiusMiles"],
        "dateWindowStart": planning["dateWindowStart"],
        "dateWindowEnd": planning["dateWindowEnd"],
    }
    job = create_import_job(movie_night, params, requested_dates, created_at)
    try:
        cached_items = []
        for show_date in requested_dates:
            cached_items.extend(query_cached_showtimes(movie_night, show_date))
        raw_candidates = [cached_showtime_to_raw(item) for item in cached_items if item.get("startsAtUtc")]
        candidates = [
            normalize_showtime_candidate(movie_night, raw, job["importJobId"], created_at, "imported")
            for raw in raw_candidates
        ]
        seen = set()
        deduped = []
        for candidate in candidates:
            if candidate["dedupeKey"] in seen:
                continue
            seen.add(candidate["dedupeKey"])
            deduped.append(candidate)
        imported_count, duplicate_count = write_candidates(movie_night, deduped)
        summary = {
            "resultCount": len(cached_items),
            "importedCount": imported_count,
            "duplicateCount": duplicate_count + (len(candidates) - len(deduped)),
            "requestedDates": requested_dates,
        }
        completed_at = now_iso()
        completed_job = complete_import_job(
            job,
            {
                "status": "completed",
                **summary,
                "updatedAt": completed_at,
            },
        )
        updated_movie_night = update_movie_night(
            movie_night,
            {
                "showtimeImportStatus": "completed",
                "lastShowtimeImportAt": completed_at,
                "lastShowtimeImportSummary": summary,
                "updatedAt": completed_at,
            },
        )
        return response(
            200,
            {
                "importJob": public_movie_night(completed_job),
                "movieNight": public_movie_night(updated_movie_night),
                "showtimes": [public_movie_night(item) for item in deduped],
            },
        )
    except Exception as exc:
        failed_at = now_iso()
        complete_import_job(job, {"status": "failed", "errorMessage": str(exc), "updatedAt": failed_at})
        update_movie_night(
            movie_night,
            {
                "showtimeImportStatus": "failed",
                "lastShowtimeImportAt": failed_at,
                "lastShowtimeImportSummary": {"errorMessage": str(exc), "requestedDates": requested_dates},
                "updatedAt": failed_at,
            },
        )
        raise


def update_candidate_status(movie_night, showtime_id, status):
    item = get_item(movie_night_pk(movie_night["movieNightId"]), f"SHOWTIME#{showtime_id}")
    if not item:
        raise ApiError(404, "Showtime candidate was not found.")
    updated_at = now_iso()
    table().update_item(
        Key={"PK": item["PK"], "SK": item["SK"]},
        UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": status, ":updatedAt": updated_at},
    )
    return {**item, "status": status, "updatedAt": updated_at}


def handle_candidate_status(movie_night, payload, status):
    showtime_id = payload.get("showtimeId") or path_param({"pathParameters": payload}, "showtimeId")
    updated = update_candidate_status(movie_night, str(showtime_id), status)
    return response(200, {"showtime": public_movie_night(updated)})


def handle_bulk_approve(movie_night, payload):
    showtime_ids = payload.get("showtimeIds") or []
    if not isinstance(showtime_ids, list) or not showtime_ids:
        raise ApiError(400, "showtimeIds is required.")
    updated = [update_candidate_status(movie_night, str(showtime_id), "approved") for showtime_id in showtime_ids]
    return response(200, {"showtimes": [public_movie_night(item) for item in updated]})


def approved_showtimes(movie_night_id):
    return [
        item
        for item in table().query(
            KeyConditionExpression=Key("PK").eq(movie_night_pk(movie_night_id)) & Key("SK").begins_with("SHOWTIME#")
        ).get("Items", [])
        if item.get("status", "approved") == "approved"
    ]


def handle_open_voting(movie_night):
    if movie_night.get("status") != "planning":
        raise ApiError(409, "Voting can only be opened from planning.")
    approved = approved_showtimes(movie_night["movieNightId"])
    if len(approved) < 2:
        raise ApiError(400, "At least 2 approved showtimes are required before opening voting.")
    updated_at = now_iso()
    fields = {
        "status": "voting",
        "GSI1PK": f"CLUB#{movie_night['clubId']}#STATUS#voting",
        "updatedAt": updated_at,
    }
    updated = update_movie_night(movie_night, fields)
    update_active_pointer(movie_night, {"status": "voting", "updatedAt": updated_at})
    return response(200, {"movieNight": public_movie_night(updated), "showtimes": [public_movie_night(item) for item in approved]})


def legacy_add_showtimes(movie_night, payload):
    raw_showtimes = payload.get("showtimes") or []
    cached_keys = payload.get("cachedShowtimeKeys") or []
    if not raw_showtimes and not cached_keys:
        raise ApiError(400, "showtimes or cachedShowtimeKeys are required.")
    created_at = now_iso()
    raw_items = list(raw_showtimes)
    for cache_key in cached_keys:
        if not isinstance(cache_key, dict) or not cache_key.get("PK") or not cache_key.get("SK"):
            raise ApiError(400, "cachedShowtimeKeys must contain PK and SK.")
        cached = get_item(cache_key["PK"], cache_key["SK"])
        if not cached:
            raise ApiError(404, "Cached showtime was not found.")
        raw_items.append(cached_showtime_to_raw(cached))
    items = [normalize_showtime_candidate(movie_night, raw, "", created_at, payload.get("status", "approved")) for raw in raw_items]
    write_candidates(movie_night, items)
    return response(201, {"showtimes": [public_movie_night(item) for item in items], "movieNight": public_movie_night(movie_night)})


def action_from_event(event, payload):
    if payload.get("action"):
        return str(payload["action"])
    path = event.get("path") or ""
    method = event.get("httpMethod") or ""
    if path.endswith("/planning") and method in {"PUT", "POST"}:
        return "updatePlanning"
    if path.endswith("/showtimes/import"):
        return "import"
    if path.endswith("/showtimes/open-voting"):
        return "openVoting"
    if path.endswith("/showtimes/bulk-approve"):
        return "approveBulk"
    if path.endswith("/approve"):
        return "approve"
    if path.endswith("/reject"):
        return "reject"
    return "legacyAdd"


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    action = action_from_event(event, payload)

    if action == "updatePlanning":
        return handle_update_planning(movie_night, payload)
    if action == "import":
        return handle_import(movie_night)
    if action == "approve":
        return handle_candidate_status(movie_night, payload, "approved")
    if action == "reject":
        return handle_candidate_status(movie_night, payload, "rejected")
    if action == "approveBulk":
        return handle_bulk_approve(movie_night, payload)
    if action == "openVoting":
        return handle_open_voting(movie_night)

    if movie_night.get("status") in CLOSED_STATUSES:
        raise ApiError(409, "Showtimes cannot be changed after the movie night is confirmed.")
    return legacy_add_showtimes(movie_night, payload)
