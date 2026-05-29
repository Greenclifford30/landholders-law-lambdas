import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


ACTIVE_STATUSES = {"planning", "voting", "confirmed"}
HISTORY_STATUSES = {"confirmed", "completed", "cancelled"}
ADMIN_ROLES = {"admin"}
PARTICIPANT_ROLES = {"admin", "friend", "guest"}

dynamodb = boto3.resource("dynamodb")


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
        except ClientError:
            return response(500, {"error": "AWS service request failed."})
        except Exception:
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


def list_votes(movie_night_id):
    return query_items(movie_night_pk(movie_night_id), "VOTE#")


def list_rsvps(movie_night_id):
    return query_items(movie_night_pk(movie_night_id), "RSVP#")


def require_string(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{name} is required.")
    return value.strip()


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
