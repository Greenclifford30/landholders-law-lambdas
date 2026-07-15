import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError


ACTIVE_STATUSES = {"planning", "voting", "confirmed"}
HISTORY_STATUSES = {"confirmed", "completed", "cancelled"}
ADMIN_ROLES = {"admin"}
PARTICIPANT_ROLES = {"admin", "friend", "guest"}
PLATFORM_ADMIN_GROUPS = {"Admin", "admin", "PlatformAdmin", "platform-admin"}

dynamodb = boto3.resource("dynamodb")
dynamodb_client = boto3.client("dynamodb")
type_serializer = TypeSerializer()
logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def voting_is_closed(movie_night, at=None):
    if movie_night.get("votingClosedAt"):
        return True
    deadline = parse_iso_datetime(movie_night.get("votingClosesAt"))
    return bool(deadline and deadline <= (at or datetime.now(timezone.utc)))


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
            "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def handle(handler_func):
    def wrapped(event, context):
        try:
            return handler_func(event or {}, context)
        except ApiError as exc:
            return response(exc.status_code, {"error": exc.message})
        except ClientError as exc:
            error = exc.response.get("Error", {})
            logger.exception(
                "AWS ClientError in %s: %s - %s",
                getattr(exc, "operation_name", "unknown"),
                error.get("Code", "Unknown"),
                error.get("Message", ""),
            )
            return response(500, {"error": "AWS service request failed."})
        except Exception:
            logger.exception("Unhandled exception in CMC handler.")
            return response(500, {"error": "Internal server error."})

    return wrapped


def parse_body(event):
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raise ApiError(400, "Base64 encoded request bodies are not supported.")
    if isinstance(raw_body, dict):
        return raw_body
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "Request body must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ApiError(400, "Request body must be a JSON object.")
    return parsed


def path_param(event, name):
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ApiError(400, f"Missing path parameter: {name}.")
    return str(value)


def query_param(event, name, default=None):
    return (event.get("queryStringParameters") or {}).get(name, default)


def claims(event):
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    raw_claims = authorizer.get("claims") or authorizer.get("jwt", {}).get("claims") or {}
    if not raw_claims:
        raise ApiError(401, "Authentication claims are required.")
    user_id = raw_claims.get("sub") or raw_claims.get("cognito:username") or raw_claims.get("username")
    if not user_id:
        raise ApiError(401, "Authenticated user id is required.")
    groups = raw_claims.get("cognito:groups") or ""
    if isinstance(groups, str):
        groups = [group.strip() for group in groups.split(",") if group.strip()]
    return {
        "userId": str(user_id),
        "email": raw_claims.get("email"),
        "name": raw_claims.get("name"),
        "groups": groups,
        "raw": raw_claims,
    }


def table():
    name = os.environ.get("APP_TABLE_NAME")
    if not name:
        raise ApiError(500, "APP_TABLE_NAME is not configured.")
    return dynamodb.Table(name)


def club_pk(club_id):
    return f"CLUB#{club_id}"


def movie_night_pk(movie_night_id):
    return f"MOVIE_NIGHT#{movie_night_id}"


def get_item(pk, sk):
    return table().get_item(Key={"PK": pk, "SK": sk}).get("Item")


def put_item(item, **kwargs):
    return table().put_item(Item=item, **kwargs)


def dynamodb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: dynamodb_value(nested_value) for key, nested_value in value.items()}
    if isinstance(value, list):
        return [dynamodb_value(nested_value) for nested_value in value]
    return value


def transact_put_items(puts):
    table_name = os.environ.get("APP_TABLE_NAME")
    if not table_name:
        raise ApiError(500, "APP_TABLE_NAME is not configured.")
    transact_items = []
    for put in puts:
        transact_put = {
            "TableName": table_name,
            "Item": {key: type_serializer.serialize(dynamodb_value(value)) for key, value in put["Item"].items()},
        }
        for option in ("ConditionExpression", "ExpressionAttributeNames", "ExpressionAttributeValues"):
            if option in put:
                transact_put[option] = put[option]
        if "ExpressionAttributeValues" in transact_put:
            transact_put["ExpressionAttributeValues"] = {
                key: type_serializer.serialize(dynamodb_value(value))
                for key, value in transact_put["ExpressionAttributeValues"].items()
            }
        transact_items.append({"Put": transact_put})
    return dynamodb_client.transact_write_items(TransactItems=transact_items)


def update_item(**kwargs):
    return table().update_item(**kwargs)


def query_items(pk, sk_prefix=None, index_name=None, limit=None, scan_forward=True):
    key_expr = Key("PK").eq(pk)
    if sk_prefix:
        key_expr = key_expr & Key("SK").begins_with(sk_prefix)
    kwargs = {
        "KeyConditionExpression": key_expr,
        "ScanIndexForward": scan_forward,
    }
    if index_name:
        kwargs["IndexName"] = index_name
    if limit:
        kwargs["Limit"] = limit
    return table().query(**kwargs).get("Items", [])


def query_gsi2_movie_night(movie_night_id):
    result = table().query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq(movie_night_pk(movie_night_id)),
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def require_membership(club_id, user_id, allowed_roles=None):
    item = get_item(club_pk(club_id), f"MEMBER#{user_id}")
    if not item:
        raise ApiError(403, "User is not a member of this club.")
    role = item.get("role")
    if allowed_roles and role not in allowed_roles:
        raise ApiError(403, "User is not allowed to perform this action.")
    return item


def is_platform_admin(user):
    return any(group in PLATFORM_ADMIN_GROUPS for group in user.get("groups", []))


def require_platform_admin(user):
    if not is_platform_admin(user):
        raise ApiError(403, "Platform admin access is required.")


def public_club(item, membership=None):
    body = public_movie_night(item)
    if membership:
        body["role"] = membership.get("role")
        body["membershipStatus"] = membership.get("status", "active")
    return body


def require_movie_night_membership(movie_night_id, user_id, allowed_roles=None):
    movie_night = query_gsi2_movie_night(movie_night_id)
    if not movie_night:
        raise ApiError(404, "Movie night not found.")
    membership = require_membership(movie_night["clubId"], user_id, allowed_roles)
    return movie_night, membership


def active_pointer(club_id):
    return get_item(club_pk(club_id), "ACTIVE_MOVIE_NIGHT")


def get_showtime(movie_night_id, showtime_id):
    return get_item(movie_night_pk(movie_night_id), f"SHOWTIME#{showtime_id}")


def list_showtimes(movie_night_id):
    return query_items(movie_night_pk(movie_night_id), "SHOWTIME#")


def list_showtimes_by_status(movie_night_id, allowed_statuses=None):
    showtimes = list_showtimes(movie_night_id)
    if allowed_statuses is None:
        return showtimes
    return [
        item
        for item in showtimes
        if item.get("status", "approved") in allowed_statuses
    ]


def list_votes(movie_night_id):
    return query_items(movie_night_pk(movie_night_id), "VOTE#")


def list_rsvps(movie_night_id):
    return query_items(movie_night_pk(movie_night_id), "RSVP#")


def require_string(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{name} is required.")
    return value.strip()


def validate_date(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{name} is required.")
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise ApiError(400, f"{name} must use yyyy-mm-dd format.") from exc
    return value.strip()


def expand_date_window(start_date, end_date):
    start = datetime.strptime(validate_date(start_date, "dateWindowStart"), "%Y-%m-%d").date()
    end = datetime.strptime(validate_date(end_date, "dateWindowEnd"), "%Y-%m-%d").date()
    if end < start:
        raise ApiError(400, "dateWindowEnd must be on or after dateWindowStart.")
    if (end - start).days > 30:
        raise ApiError(400, "Date windows cannot exceed 31 days.")
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def normalize_planning_input(payload, existing=None):
    existing = existing or {}
    target_date = payload.get("targetDate", existing.get("targetDate"))
    if target_date:
        target_date = validate_date(target_date, "targetDate")

    date_window_start = payload.get("dateWindowStart", existing.get("dateWindowStart") or target_date)
    date_window_end = payload.get("dateWindowEnd", existing.get("dateWindowEnd") or target_date)
    if date_window_start:
        date_window_start = validate_date(date_window_start, "dateWindowStart")
    if date_window_end:
        date_window_end = validate_date(date_window_end, "dateWindowEnd")
    if date_window_start and date_window_end:
        expand_date_window(date_window_start, date_window_end)

    zip_code = str(payload.get("zipCode", payload.get("zip", existing.get("zipCode", "")))).strip()
    radius_value = payload.get("radiusMiles", payload.get("radius", existing.get("radiusMiles")))
    radius_miles = None
    if radius_value not in (None, ""):
        try:
            radius_miles = int(radius_value)
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "radiusMiles must be an integer.") from exc
        if radius_miles < 1 or radius_miles > 100:
            raise ApiError(400, "radiusMiles must be between 1 and 100.")

    preferred_formats = payload.get("preferredFormats", existing.get("preferredFormats", []))
    if preferred_formats is None:
        preferred_formats = []
    if not isinstance(preferred_formats, list):
        raise ApiError(400, "preferredFormats must be a list.")

    preferred_theater_ids = payload.get("preferredTheaterIds", existing.get("preferredTheaterIds", []))
    if preferred_theater_ids is None:
        preferred_theater_ids = []
    if not isinstance(preferred_theater_ids, list):
        raise ApiError(400, "preferredTheaterIds must be a list.")

    return {
        "targetDate": target_date,
        "dateWindowStart": date_window_start,
        "dateWindowEnd": date_window_end,
        "zipCode": zip_code,
        "radiusMiles": radius_miles,
        "timezone": str(payload.get("timezone", existing.get("timezone", "America/Chicago"))).strip() or "America/Chicago",
        "preferredFormats": [str(item).strip() for item in preferred_formats if str(item).strip()],
        "preferredTheaterIds": [str(item).strip() for item in preferred_theater_ids if str(item).strip()],
    }


def optional_string(payload, name, default=""):
    value = payload.get(name, default)
    if value is None:
        return default
    return str(value).strip()


def normalize_movie_snapshot(payload):
    movie = payload.get("movie") or payload.get("selectedMovie")
    if not isinstance(movie, dict):
        raise ApiError(400, "movie is required.")
    provider = optional_string(movie, "provider", optional_string(movie, "externalProvider", "tmdb"))
    external_id = movie.get("externalId") or movie.get("movieId") or movie.get("id")
    title = optional_string(movie, "title")
    if not external_id or not title:
        raise ApiError(400, "movie.externalId and movie.title are required.")
    release_date = optional_string(movie, "releaseDate", optional_string(movie, "release_date"))
    return {
        "provider": provider,
        "externalId": str(external_id),
        "title": title,
        "overview": optional_string(movie, "overview"),
        "posterPath": optional_string(movie, "posterPath", optional_string(movie, "poster_path")),
        "posterUrl": optional_string(movie, "posterUrl"),
        "releaseDate": release_date,
        "releaseYear": optional_string(movie, "releaseYear", release_date[:4] if release_date else ""),
        "runtime": movie.get("runtime"),
        "genres": movie.get("genres") or [],
        "rating": movie.get("rating") or movie.get("voteAverage") or movie.get("vote_average"),
        "popularity": movie.get("popularity"),
    }


def public_movie_night(item):
    return {
        key: value
        for key, value in item.items()
        if key not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}
    }


def sort_by_date(items):
    return sorted(
        items,
        key=lambda item: item.get("targetDate") or item.get("createdAt") or "",
        reverse=True,
    )
