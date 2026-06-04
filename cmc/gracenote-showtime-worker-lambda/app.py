import hashlib
import json
import logging
import os
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

            item = sanitize_item(
                {
                    "PK": (
                        "SHOWTIME_CACHE#PROVIDER#gracenote"
                        f"#ZIP#{message['zip']}#DATE#{message['startDate']}"
                    ),
                    "SK": (
                        f"MOVIE#{tms_id}#THEATER#{theater_id}"
                        f"#START#{local_date_time}#FORMAT#{q_hash}"
                    ),
                    "GSI1PK": f"MOVIE#GRACENOTE#{tms_id}",
                    "GSI1SK": f"START#{starts_at_utc}#THEATER#{theater_id}",
                    "provider": "gracenote",
                    "tmsId": tms_id,
                    "rootId": movie.get("rootId") or "",
                    "title": movie.get("title") or "",
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
                    "startDate": message["startDate"],
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


def process_record(record):
    message = parse_message(record)
    response_data = call_gracenote(message)
    items = normalize_items(response_data, message)
    write_items(items)
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
            logger.warning("Dropping non-retryable Gracenote record %s: %s", message_id, exc)
        except RetryableError as exc:
            logger.warning("Retryable Gracenote record failure %s: %s", message_id, exc)
            failures.append({"itemIdentifier": message_id})
        except Exception:
            logger.exception("Unexpected Gracenote record failure %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}
