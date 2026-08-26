import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import boto3
import requests
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

dynamodb = boto3.resource("dynamodb")
secretsmanager = boto3.client("secretsmanager")

VALID_UNITS = {"mi", "km"}
RETRYABLE_DDB_CODES = {
    "InternalServerError",
    "ProvisionedThroughputExceededException",
    "RequestLimitExceeded",
    "ThrottlingException",
}

_cached_api_key = None


class NonRetryableError(Exception):
    pass


class RetryableError(Exception):
    pass


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RetryableError(f"Missing required environment variable: {name}")
    return value


def parse_secret_value(secret_value):
    secret_string = secret_value.get("SecretString")
    if not secret_string:
        raise RetryableError("Gracenote secret has no SecretString value.")

    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string

    if isinstance(parsed, str):
        return parsed

    if isinstance(parsed, dict):
        for key in ("api_key", "apiKey", "GRACENOTE_API_KEY", "key"):
            if parsed.get(key):
                return str(parsed[key])

    raise RetryableError("Gracenote secret does not contain a supported API key field.")


def get_api_key():
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key

    try:
        secret = secretsmanager.get_secret_value(SecretId=get_required_env("GRACENOTE_SECRET_ARN"))
    except ClientError as exc:
        raise RetryableError("Unable to read Gracenote API key secret.") from exc

    _cached_api_key = parse_secret_value(secret)
    return _cached_api_key


def parse_message(record):
    try:
        payload = json.loads(record.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise NonRetryableError("SQS body must be valid JSON.") from exc

    if payload.get("provider") != "gracenote":
        raise NonRetryableError("Unsupported provider.")

    zip_code = str(payload.get("zip") or os.environ.get("GRACENOTE_DEFAULT_ZIP", "")).strip()
    start_date = str(payload.get("startDate") or "").strip()
    units = str(payload.get("units") or os.environ.get("GRACENOTE_UNITS", "mi")).strip()

    if not zip_code:
        raise NonRetryableError("Missing zip.")
    if not start_date:
        raise NonRetryableError("Missing startDate.")
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise NonRetryableError("startDate must use yyyy-mm-dd format.") from exc
    if units not in VALID_UNITS:
        raise NonRetryableError("Unsupported units.")

    try:
        radius = int(payload.get("radius", os.environ.get("GRACENOTE_DEFAULT_RADIUS", "30")))
        num_days = int(payload.get("numDays", os.environ.get("GRACENOTE_DEFAULT_NUM_DAYS", "14")))
    except (TypeError, ValueError) as exc:
        raise NonRetryableError("radius and numDays must be integers.") from exc

    if radius < 1 or radius > 100:
        raise NonRetryableError("radius must be between 1 and 100.")
    if num_days < 1 or num_days > 90:
        raise NonRetryableError("numDays must be between 1 and 90.")

    payload["zip"] = zip_code
    payload["startDate"] = start_date
    payload["units"] = units
    payload["radius"] = radius
    payload["numDays"] = num_days
    return payload


def build_gracenote_params(message, api_key):
    params = {
        "api_key": api_key,
        "startDate": message["startDate"],
        "zip": message["zip"],
        "numDays": str(message["numDays"]),
        "radius": str(message["radius"]),
        "units": message["units"],
        "imageSize": os.environ.get("GRACENOTE_IMAGE_SIZE", "Md"),
        "imageText": os.environ.get("GRACENOTE_IMAGE_TEXT", "true"),
    }
    return params


def call_gracenote(message):
    base_url = os.environ.get("GRACENOTE_BASE_URL", "http://data.tmsapi.com/v1.1").rstrip("/")
    endpoint = "/movies/showings"
    if message.get("tmsId") or message.get("rootId"):
        movie_id = message.get("tmsId") or message.get("rootId")
        endpoint = f"/movies/{movie_id}/showings"

    params = build_gracenote_params(message, get_api_key())
    safe_params = {key: value for key, value in params.items() if key != "api_key"}
    logger.info("Calling Gracenote endpoint=%s params=%s", endpoint, safe_params)

    try:
        result = requests.get(f"{base_url}{endpoint}", params=params, timeout=20)
    except requests.Timeout as exc:
        raise RetryableError("Gracenote request timed out.") from exc
    except requests.RequestException as exc:
        raise RetryableError("Gracenote request failed.") from exc

    if result.status_code == 429 or result.status_code >= 500:
        raise RetryableError(f"Gracenote returned retryable status {result.status_code}.")
    if result.status_code >= 400:
        raise NonRetryableError(f"Gracenote returned non-retryable status {result.status_code}.")

    try:
        return result.json()
    except ValueError as exc:
        raise RetryableError("Gracenote response was not valid JSON.") from exc


def canonical_json(value):
    return json.dumps(value or "", sort_keys=True, separators=(",", ":"))


def qualifier_hash(quals):
    return hashlib.sha256(canonical_json(quals).encode("utf-8")).hexdigest()[:12]


def normalize_title(value):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(normalized.split())


def parse_screen_format(quals):
    text = " ".join(quals) if isinstance(quals, list) else str(quals or "")
    lower = text.lower()
    if "imax" in lower:
        return "IMAX"
    if "dolby" in lower:
        return "Dolby"
    if "70mm" in lower or "70 mm" in lower:
        return "70mm"
    if "3d" in lower or "3-d" in lower:
        return "3D"
    if "closed caption" in lower or "open caption" in lower or "caption" in lower:
        return "Captioned"
    if "d-box" in lower or "dbox" in lower:
        return "D-BOX"
    return "Standard"


def normalize_datetime(date_time, timezone_name):
    if not date_time:
        raise NonRetryableError("Showtime is missing dateTime.")

    raw = str(date_time).strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise NonRetryableError(f"Invalid showtime dateTime: {raw}") from exc

    local_zone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        local_dt = parsed.replace(tzinfo=local_zone)
    else:
        local_dt = parsed.astimezone(local_zone)

    utc_dt = local_dt.astimezone(timezone.utc).replace(microsecond=0)
    local_without_offset = local_dt.replace(tzinfo=None, microsecond=0)
    return local_without_offset.isoformat(), utc_dt.isoformat().replace("+00:00", "Z")


def sanitize_value(value):
    if isinstance(value, dict):
        return {
            key: sanitized
            for key, child in value.items()
            if (sanitized := sanitize_value(child)) is not None
        }
    if isinstance(value, list):
        return [
            sanitized
            for child in value
            if (sanitized := sanitize_value(child)) is not None
        ]
    return value


def sanitize_item(item):
    return {
        key: sanitized
        for key, value in item.items()
        if (sanitized := sanitize_value(value)) is not None
    }


def normalize_items(response_data, message):
    if not isinstance(response_data, list):
        raise RetryableError("Gracenote response root was not a list.")

    timezone_name = os.environ.get("MOVIE_CLUB_TIMEZONE", "America/Chicago")
    fetched_at_dt = datetime.now(timezone.utc).replace(microsecond=0)
    fetched_at = fetched_at_dt.isoformat().replace("+00:00", "Z")
    expires_at = int((fetched_at_dt + timedelta(hours=48)).timestamp())
    items = []

    for movie in response_data:
        if not isinstance(movie, dict):
            continue

        tms_id = movie.get("tmsId")
        if not tms_id:
            logger.warning("Skipping Gracenote movie without tmsId")
            continue

        for showtime in movie.get("showtimes") or []:
            theatre = showtime.get("theatre") or {}
            theater_id = theatre.get("id")
            theater_name = theatre.get("name")
            if not theater_id or not theater_name:
                raise NonRetryableError("Showtime is missing theater id or name.")

            local_date_time, starts_at_utc = normalize_datetime(
                showtime.get("dateTime"), timezone_name
            )
            quals = showtime.get("quals") or []
            q_hash = qualifier_hash(quals)
            show_date = local_date_time[:10]
            normalized_title = normalize_title(movie.get("title"))

            item = sanitize_item(
                {
                    "PK": (
                        "SHOWTIME_CACHE#PROVIDER#gracenote"
                        f"#ZIP#{message['zip']}#DATE#{show_date}"
                    ),
                    "SK": (
                        f"TITLE#{normalized_title}#MOVIE#{tms_id}#THEATER#{theater_id}"
                        f"#START#{local_date_time}#FORMAT#{q_hash}"
                    ),
                    "GSI1PK": f"MOVIE#GRACENOTE#{tms_id}",
                    "GSI1SK": f"START#{starts_at_utc}#THEATER#{theater_id}",
                    "provider": "gracenote",
                    "tmsId": tms_id,
                    "rootId": movie.get("rootId") or "",
                    "title": movie.get("title") or "",
                    "normalizedTitle": normalized_title,
                    "releaseYear": movie.get("releaseYear") or "",
                    "providerTheaterId": theater_id,
                    "theaterName": theater_name,
                    "theaterLocation": theatre.get("location") or theatre.get("address") or "",
                    "theatreId": theater_id,
                    "theatreName": theater_name,
                    "localDateTime": local_date_time,
                    "startsAtUtc": starts_at_utc,
                    "quals": quals,
                    "screenFormat": parse_screen_format(quals),
                    "ticketURI": showtime.get("ticketURI"),
                    "fetchedAt": fetched_at,
                    "expiresAt": expires_at,
                    "releaseDate": movie.get("releaseDate"),
                    "runTime": movie.get("runTime"),
                    "preferredImage": movie.get("preferredImage"),
                    "zip": message["zip"],
                    "showDate": show_date,
                    "startDate": show_date,
                    "requestStartDate": message["startDate"],
                    "radius": message["radius"],
                    "units": message["units"],
                    "qualifierHash": q_hash,
                    "sourceEndpoint": "movies/showings",
                }
            )
            items.append(item)

    return items


def write_items(items):
    table = dynamodb.Table(get_required_env("APP_TABLE_NAME"))
    try:
        with table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for item in items:
                batch.put_item(Item=item)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in RETRYABLE_DDB_CODES:
            raise RetryableError("DynamoDB write was throttled or temporarily unavailable.") from exc
        raise NonRetryableError("DynamoDB rejected the normalized showtime record.") from exc


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def candidate_from_cache(item, message, imported_at):
    dedupe_key = item["SK"]
    showtime_id = f"st_{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()[:16]}"
    return {
        "PK": f"MOVIE_NIGHT#{message['movieNightId']}",
        "SK": f"SHOWTIME#{showtime_id}",
        "GSI1PK": f"MOVIE_NIGHT#{message['movieNightId']}#SHOWTIMES",
        "GSI1SK": f"START#{item['startsAtUtc']}#SHOWTIME#{showtime_id}",
        "movieNightId": message["movieNightId"],
        "showtimeId": showtime_id,
        "provider": "gracenote",
        "externalMovieId": item.get("tmsId") or item.get("rootId") or "",
        "providerMovieId": item.get("tmsId") or item.get("rootId") or "",
        "externalTheaterId": item.get("providerTheaterId") or "",
        "providerTheaterId": item.get("providerTheaterId") or "",
        "theaterName": item.get("theaterName") or "",
        "theaterLocation": item.get("theaterLocation") or "",
        "theaterAddress": item.get("theaterLocation") or "",
        "startsAt": item["startsAtUtc"],
        "startsAtUtc": item["startsAtUtc"],
        "localDate": item.get("localDateTime", "")[:10],
        "localTime": item.get("localDateTime", "")[11:16],
        "localDateTime": item.get("localDateTime") or "",
        "timezone": message.get("timezone") or "America/Chicago",
        "screenFormat": item.get("screenFormat") or "Standard",
        "amenities": item.get("quals") or [],
        "quals": item.get("quals") or [],
        "ticketURI": item.get("ticketURI") or "",
        "importJobId": message["importJobId"],
        "dedupeKey": dedupe_key,
        "status": "imported",
        "createdAt": imported_at,
        "updatedAt": imported_at,
    }


def update_import_state(message, status, summary=None, error_message=None):
    if not message.get("movieNightId") or not message.get("importJobId"):
        return
    updated_at = now_iso()
    app_table = dynamodb.Table(get_required_env("APP_TABLE_NAME"))
    job_key = {"PK": f"MOVIE_NIGHT#{message['movieNightId']}", "SK": f"SHOWTIME_IMPORT#{message['importJobId']}"}
    job = app_table.get_item(Key=job_key).get("Item") or job_key
    job.update({"status": status, "updatedAt": updated_at})
    if summary:
        job.update(summary)
    if error_message:
        job["errorMessage"] = error_message
    app_table.put_item(Item=job)
    movie_night = app_table.query(
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": f"MOVIE_NIGHT#{message['movieNightId']}"},
        Limit=1,
    ).get("Items", [])
    if movie_night:
        values = {":status": status, ":updatedAt": updated_at, ":summary": summary or {"errorMessage": error_message or ""}}
        app_table.update_item(
            Key={"PK": movie_night[0]["PK"], "SK": movie_night[0]["SK"]},
            UpdateExpression="SET showtimeImportStatus = :status, lastShowtimeImportAt = :updatedAt, lastShowtimeImportSummary = :summary, updatedAt = :updatedAt",
            ExpressionAttributeValues=values,
        )


def import_movie_night_candidates(items, message):
    if not message.get("movieNightId") or not message.get("importJobId"):
        return None
    wanted_title = normalize_title(message.get("movieTitle"))
    matched = [item for item in items if normalize_title(item.get("title")) == wanted_title]
    imported_at = now_iso()
    app_table = dynamodb.Table(get_required_env("APP_TABLE_NAME"))
    imported_count = 0
    duplicate_count = 0
    with app_table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for item in matched:
            candidate = candidate_from_cache(item, message, imported_at)
            existing = app_table.get_item(Key={"PK": candidate["PK"], "SK": candidate["SK"]}).get("Item")
            if existing:
                duplicate_count += 1
                candidate["status"] = existing.get("status", "imported")
                candidate["createdAt"] = existing.get("createdAt", imported_at)
            else:
                imported_count += 1
            batch.put_item(Item=candidate)
    summary = {
        "resultCount": len(matched),
        "importedCount": imported_count,
        "duplicateCount": duplicate_count,
        "requestedDates": [
            (datetime.strptime(message["startDate"], "%Y-%m-%d").date() + timedelta(days=offset)).isoformat()
            for offset in range(message["numDays"])
        ],
    }
    update_import_state(message, "completed", summary=summary)
    return summary


def process_record(record):
    message = parse_message(record)
    update_import_state(message, "running")
    response_data = call_gracenote(message)
    items = normalize_items(response_data, message)
    write_items(items)
    import_movie_night_candidates(items, message)
    logger.info(
        "Stored Gracenote showtime cache records count=%s zip=%s startDate=%s",
        len(items),
        message["zip"],
        message["startDate"],
    )


def handler(event, context):
    failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            process_record(record)
        except NonRetryableError as exc:
            try:
                update_import_state(parse_message(record), "failed", error_message=str(exc))
            except Exception:
                logger.exception("Unable to mark import failed for record %s", message_id)
            logger.warning("Dropping non-retryable Gracenote record %s: %s", message_id, exc)
        except RetryableError as exc:
            try:
                update_import_state(parse_message(record), "failed", error_message=str(exc))
            except Exception:
                logger.exception("Unable to mark retryable import failed for record %s", message_id)
            logger.warning("Retryable Gracenote record failure %s: %s", message_id, exc)
            failures.append({"itemIdentifier": message_id})
        except Exception:
            try:
                update_import_state(parse_message(record), "failed", error_message="Unexpected provider import failure.")
            except Exception:
                logger.exception("Unable to mark import failed for record %s", message_id)
            logger.exception("Unexpected Gracenote record failure %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}
