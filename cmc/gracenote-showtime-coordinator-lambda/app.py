import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

sqs = boto3.client("sqs")

VALID_UNITS = {"mi", "km"}
ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")


class ValidationError(Exception):
    pass


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


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


def get_int(payload, name, default, min_value, max_value):
    value = payload.get(name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer.") from exc

    if parsed < min_value or parsed > max_value:
        raise ValidationError(f"{name} must be between {min_value} and {max_value}.")
    return parsed


def resolve_refresh_request(event):
    payload = parse_payload(event)
    timezone_name = os.environ.get("MOVIE_CLUB_TIMEZONE", "America/Chicago")
    now_utc = datetime.utcnow().replace(microsecond=0)
    today_local = datetime.now(ZoneInfo(timezone_name)).date().isoformat()

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

    start_date = str(payload.get("startDate") or today_local).strip()
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError("startDate must use yyyy-mm-dd format.") from exc

    requested_by = payload.get("requestedBy") or payload.get("source") or event.get("source")
    if not requested_by:
        requested_by = "api-gateway" if is_api_gateway_event(event) else "manual"

    message = {
        "provider": "gracenote",
        "zip": zip_code,
        "radius": radius,
        "numDays": num_days,
        "units": units,
        "startDate": start_date,
        "requestedBy": requested_by,
        "requestedAt": f"{now_utc.isoformat()}Z",
    }

    if payload.get("tmsId"):
        message["tmsId"] = str(payload["tmsId"]).strip()
    if payload.get("rootId"):
        message["rootId"] = str(payload["rootId"]).strip()

    return message


def handler(event, context):
    api_event = is_api_gateway_event(event)

    try:
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
