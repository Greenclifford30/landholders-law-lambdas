import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

VALID_UNITS = {"mi", "km"}
ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
SEARCH_LIMIT = 100


class ValidationError(Exception):
    pass


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def table():
    table_name = os.environ.get("APP_TABLE_NAME")
    if not table_name:
        raise RuntimeError("APP_TABLE_NAME is not configured.")
    return dynamodb.Table(table_name)


def is_api_gateway_event(event):
    return isinstance(event, dict) and (
        "requestContext" in event or "httpMethod" in event or "body" in event
    )


def parse_payload(event):
    if not isinstance(event, dict):
        raise ValidationError("Event must be a JSON object.")

    if is_api_gateway_event(event):
        raw_body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raise ValidationError("Base64 encoded request bodies are not supported.")
        try:
            payload = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
        except json.JSONDecodeError as exc:
            raise ValidationError("Request body must be valid JSON.") from exc
        return payload or {}

    return event


def query_params(event):
    return event.get("queryStringParameters") or {}


def normalize_title(value):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(normalized.split())


def get_int(payload, name, default, min_value, max_value):
    value = payload.get(name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer.") from exc

    if parsed < min_value or parsed > max_value:
        raise ValidationError(f"{name} must be between {min_value} and {max_value}.")
    return parsed


def current_local_date():
    timezone_name = os.environ.get("MOVIE_CLUB_TIMEZONE", "America/Chicago")
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def validate_common_window(payload):
    zip_code = str(payload.get("zip") or os.environ.get("GRACENOTE_DEFAULT_ZIP", "")).strip()
    if not ZIP_RE.match(zip_code):
        raise ValidationError("zip must be a 5 digit ZIP code or ZIP+4.")

    radius = get_int(
        payload,
        "radius",
        os.environ.get("GRACENOTE_DEFAULT_RADIUS", "30"),
        1,
        100,
    )
    num_days = get_int(
        payload,
        "numDays",
        os.environ.get("GRACENOTE_DEFAULT_NUM_DAYS", "14"),
        1,
        90,
    )

    units = str(payload.get("units") or os.environ.get("GRACENOTE_UNITS", "mi")).strip()
    if units not in VALID_UNITS:
        raise ValidationError("units must be either 'mi' or 'km'.")

    start_date = str(payload.get("startDate") or current_local_date()).strip()
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError("startDate must use yyyy-mm-dd format.") from exc

    return {
        "zip": zip_code,
        "radius": radius,
        "numDays": num_days,
        "units": units,
        "startDate": start_date,
    }


def resolve_refresh_request(event):
    payload = parse_payload(event)
    now_utc = datetime.utcnow().replace(microsecond=0)
    window = validate_common_window(payload)

    requested_by = payload.get("requestedBy") or payload.get("source") or event.get("source")
    if not requested_by:
        requested_by = "api-gateway" if is_api_gateway_event(event) else "manual"

    message = {
        "provider": "gracenote",
        **window,
        "requestedBy": requested_by,
        "requestedAt": f"{now_utc.isoformat()}Z",
    }

    if payload.get("tmsId"):
        message["tmsId"] = str(payload["tmsId"]).strip()
    if payload.get("rootId"):
        message["rootId"] = str(payload["rootId"]).strip()

    return message


def is_search_request(event):
    if not is_api_gateway_event(event):
        return False
    method = event.get("httpMethod") or (event.get("requestContext") or {}).get("httpMethod")
    resource_path = (event.get("requestContext") or {}).get("resourcePath") or event.get("resource") or event.get("path") or ""
    return method == "GET" and resource_path.endswith("/admin/showtimes/gracenote/search")


def resolve_search_request(event):
    payload = query_params(event)
    window = validate_common_window(payload)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required.")
    provider = str(payload.get("provider") or "gracenote").strip()
    if provider and provider != "gracenote" and provider != "tmdb":
        raise ValidationError("provider must be gracenote or tmdb.")
    return {
        **window,
        "title": title,
        "normalizedTitle": normalize_title(title),
        "provider": provider,
        "providerMovieId": str(payload.get("providerMovieId") or "").strip(),
    }


def cache_pk(search):
    return (
        "SHOWTIME_CACHE#PROVIDER#gracenote"
        f"#ZIP#{search['zip']}#DATE#{search['startDate']}"
    )


def values_equal(left, right):
    return str(left) == str(right)


def matches_search(item, search):
    item_title = normalize_title(item.get("title"))
    requested_title = search["normalizedTitle"]
    if not item_title or not requested_title:
        return False
    title_matches = item_title == requested_title or requested_title in item_title or item_title in requested_title
    if not title_matches:
        return False
    if item.get("radius") is not None and not values_equal(item.get("radius"), search["radius"]):
        return False
    if item.get("units") is not None and item.get("units") != search["units"]:
        return False
    return True


def public_cached_showtime(item):
    return {
        "PK": item.get("PK", ""),
        "SK": item.get("SK", ""),
        "provider": item.get("provider", "gracenote"),
        "providerShowtimeId": item.get("providerShowtimeId") or item.get("SK", ""),
        "providerMovieId": item.get("providerMovieId") or item.get("tmsId") or item.get("rootId") or "",
        "providerTheaterId": item.get("providerTheaterId") or item.get("theatreId") or "",
        "theaterName": item.get("theaterName") or item.get("theatreName") or "",
        "theaterLocation": item.get("theaterLocation") or item.get("theatreLocation") or "",
        "startsAtUtc": item.get("startsAtUtc") or "",
        "localDateTime": item.get("localDateTime") or "",
        "screenFormat": item.get("screenFormat") or "Standard",
        "ticketURI": item.get("ticketURI") or "",
        "quals": item.get("quals") or [],
    }


def search_cached_showtimes(event):
    search = resolve_search_request(event)
    result = table().query(KeyConditionExpression=Key("PK").eq(cache_pk(search)))
    showtimes = [
        public_cached_showtime(item)
        for item in result.get("Items", [])
        if matches_search(item, search) and item.get("startsAtUtc")
    ]
    showtimes.sort(key=lambda item: (item.get("startsAtUtc") or "", item.get("theaterName") or ""))
    return {"showtimes": showtimes[:SEARCH_LIMIT]}


def handler(event, context):
    api_event = is_api_gateway_event(event)

    try:
        if is_search_request(event):
            return response(200, search_cached_showtimes(event))

        queue_url = os.environ["SHOWTIME_REFRESH_QUEUE_URL"]
        message = resolve_refresh_request(event)
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))

        logger.info(
            "Enqueued Gracenote refresh zip=%s startDate=%s numDays=%s requestedBy=%s",
            message["zip"],
            message["startDate"],
            message["numDays"],
            message["requestedBy"],
        )

        body = {"success": True, "enqueued": 1, "job": message}
        return response(202, body) if api_event else body

    except ValidationError as exc:
        logger.warning("Invalid Gracenote refresh request: %s", exc)
        body = {"success": False, "error": str(exc)}
        return response(400, body) if api_event else body

    except Exception as exc:
        logger.exception("Failed to enqueue Gracenote refresh")
        body = {"success": False, "error": "Failed to enqueue refresh request."}
        return response(500, body) if api_event else body
