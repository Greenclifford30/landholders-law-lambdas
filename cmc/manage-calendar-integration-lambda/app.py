import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from cmc_availability import emit_calendar_metrics, enqueue_availability_sync
from cmc_events import all_items
from cmc_shared import ApiError, claims, get_item, handle, now_iso, parse_body, parse_iso_datetime, response, table


PROVIDER = "google"
INTEGRATION_SK = "CALENDAR#GOOGLE"
OAUTH_SK = "GOOGLE_CALENDAR"
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

kms = boto3.client("kms")
secrets_manager = boto3.client("secretsmanager")


def enabled():
    return os.environ.get("GOOGLE_CALENDAR_ENABLED", "false").lower() == "true"


def require_enabled():
    if not enabled():
        raise ApiError(503, "Google Calendar connection is not enabled in this environment.")


def user_pk(user_id):
    return f"USER#{user_id}"


def integration_item(user_id):
    return get_item(user_pk(user_id), INTEGRATION_SK)


def public_integration(item):
    if not item:
        return {
            "provider": PROVIDER,
            "status": "disconnected",
            "selectedCalendarCount": 0,
        }
    return {
        "provider": PROVIDER,
        "status": item.get("status", "disconnected"),
        "accountEmail": item.get("accountEmail"),
        "selectedCalendarCount": len(item.get("selectedCalendarIds") or []),
        "scopes": item.get("scopes") or [],
        "connectedAt": item.get("connectedAt"),
        "updatedAt": item.get("updatedAt"),
        "lastSyncedAt": item.get("lastSyncedAt"),
        "lastErrorCode": item.get("lastErrorCode"),
    }


def load_credentials():
    secret_arn = os.environ.get("GOOGLE_CALENDAR_SECRET_ARN")
    if not secret_arn:
        raise ApiError(500, "Google Calendar credentials are not configured.")
    raw = secrets_manager.get_secret_value(SecretId=secret_arn).get("SecretString") or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(500, "Google Calendar credentials are invalid.") from exc
    if not value.get("client_id") or not value.get("client_secret"):
        raise ApiError(500, "Google Calendar credentials are incomplete.")
    return value


def allowed_redirect_uri(value):
    allowed = {entry.strip() for entry in os.environ.get("GOOGLE_CALENDAR_REDIRECT_URIS", "").split(",") if entry.strip()}
    if value not in allowed:
        raise ApiError(400, "redirectUri is not an approved Google Calendar callback.")
    return value


def request_json(url, *, method="GET", headers=None, form=None):
    body = urlencode(form).encode() if form is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=15) as result:
            raw = result.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        code = payload.get("error")
        if isinstance(code, dict):
            code = code.get("status") or code.get("message")
        if code == "invalid_grant":
            raise ApiError(401, "Google Calendar authorization expired. Reconnect your calendar.", {"code": "needs_reauth"}) from exc
        if exc.code == 429:
            raise ApiError(503, "Google Calendar is temporarily rate limited. Try again shortly.", {"code": "rate_limited"}) from exc
        raise ApiError(502, "Google Calendar could not complete the request.", {"code": "provider_error"}) from exc
    except (URLError, TimeoutError) as exc:
        raise ApiError(502, "Google Calendar is temporarily unavailable.", {"code": "provider_unavailable"}) from exc


def encrypt_refresh_token(user_id, token):
    key_id = os.environ.get("GOOGLE_CALENDAR_KMS_KEY_ARN")
    if not key_id:
        raise ApiError(500, "Google Calendar token encryption is not configured.")
    result = kms.encrypt(
        KeyId=key_id,
        Plaintext=token.encode("utf-8"),
        EncryptionContext={"userId": user_id, "provider": PROVIDER},
    )
    return base64.b64encode(result["CiphertextBlob"]).decode("ascii")


def decrypt_refresh_token(user_id, ciphertext):
    result = kms.decrypt(
        CiphertextBlob=base64.b64decode(ciphertext),
        EncryptionContext={"userId": user_id, "provider": PROVIDER},
    )
    return result["Plaintext"].decode("utf-8")


def fresh_access_token(user_id, integration):
    credentials = load_credentials()
    refresh_token = decrypt_refresh_token(user_id, integration["encryptedRefreshToken"])
    result = request_json(
        TOKEN_URL,
        method="POST",
        form={
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if not result.get("access_token"):
        raise ApiError(502, "Google Calendar did not return an access token.", {"code": "provider_error"})
    return result["access_token"], refresh_token


def begin_authorization(user, payload):
    redirect_uri = allowed_redirect_uri(str(payload.get("redirectUri") or ""))
    credentials = load_credentials()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
    table().put_item(Item={
        "PK": f"OAUTH_STATE#{state}",
        "SK": OAUTH_SK,
        "entityType": "oauthState",
        "userId": user["userId"],
        "redirectUri": redirect_uri,
        "codeVerifier": verifier,
        "expiresAt": expires_at,
        "createdAt": now_iso(),
    })
    params = {
        "client_id": credentials["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if user.get("email"):
        params["login_hint"] = user["email"]
    return response(200, {"authorizationUrl": f"{AUTH_URL}?{urlencode(params)}"})


def complete_authorization(event):
    require_enabled()
    query = event.get("queryStringParameters") or {}
    if query.get("error"):
        raise ApiError(400, "Google Calendar access was not granted.", {"code": "consent_denied"})
    state = str(query.get("state") or "")
    code = str(query.get("code") or "")
    if not state or not code:
        raise ApiError(400, "Google Calendar authorization could not be verified.", {"code": "invalid_state"})
    try:
        deleted = table().delete_item(
            Key={"PK": f"OAUTH_STATE#{state}", "SK": OAUTH_SK},
            ConditionExpression="attribute_exists(PK)",
            ReturnValues="ALL_OLD",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise ApiError(400, "Google Calendar authorization could not be verified.", {"code": "invalid_state"}) from exc
        raise
    state_item = deleted.get("Attributes")
    if not state_item:
        raise ApiError(400, "Google Calendar authorization could not be verified.", {"code": "invalid_state"})
    if int(state_item.get("expiresAt", 0)) <= int(datetime.now(timezone.utc).timestamp()):
        raise ApiError(400, "Google Calendar authorization expired. Start the connection again.", {"code": "expired_state"})

    credentials = load_credentials()
    tokens = request_json(
        TOKEN_URL,
        method="POST",
        form={
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "code": code,
            "code_verifier": state_item["codeVerifier"],
            "grant_type": "authorization_code",
            "redirect_uri": state_item["redirectUri"],
        },
    )
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token or not access_token:
        raise ApiError(502, "Google Calendar did not return durable authorization. Reconnect and grant access.")
    profile = request_json(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if not profile.get("sub"):
        raise ApiError(502, "Google Calendar account identity could not be verified.")

    user_id = state_item["userId"]
    previous = integration_item(user_id) or {}
    now = now_iso()
    same_account = previous.get("providerSubject") == profile["sub"]
    item = {
        "PK": user_pk(user_id),
        "SK": INTEGRATION_SK,
        "GSI1PK": "CALENDAR_PROVIDER#google#connected",
        "GSI1SK": f"USER#{user_id}",
        "entityType": "calendarIntegration",
        "provider": PROVIDER,
        "userId": user_id,
        "providerSubject": profile["sub"],
        "accountEmail": profile.get("email"),
        "encryptedRefreshToken": encrypt_refresh_token(user_id, refresh_token),
        "selectedCalendarIds": previous.get("selectedCalendarIds", []) if same_account else [],
        "scopes": str(tokens.get("scope") or " ".join(SCOPES)).split(),
        "status": "connected",
        "connectedAt": previous.get("connectedAt", now) if same_account else now,
        "updatedAt": now,
    }
    table().put_item(Item=item)
    enqueue_availability_sync(user_id=user_id, reason="calendar_connected")
    emit_calendar_metrics(ConnectSuccess=1)
    return response(200, {"integration": public_integration(item), "redirectPath": "/settings?calendar=connected"})


def list_calendars(user_id):
    integration = integration_item(user_id)
    if not integration or integration.get("status") != "connected":
        raise ApiError(409, "Connect Google Calendar before choosing calendars.")
    access_token, _refresh = fresh_access_token(user_id, integration)
    selected = set(integration.get("selectedCalendarIds") or [])
    calendars = []
    page_token = None
    while True:
        params = {"maxResults": 250, "minAccessRole": "freeBusyReader"}
        if page_token:
            params["pageToken"] = page_token
        result = request_json(
            f"{CALENDAR_LIST_URL}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        for item in result.get("items") or []:
            calendar_id = item.get("id")
            if calendar_id:
                calendars.append({
                    "id": calendar_id,
                    "summary": item.get("summary") or "Calendar",
                    "primary": bool(item.get("primary")),
                    "selected": calendar_id in selected,
                })
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return response(200, {"calendars": calendars})


def select_calendars(user_id, payload):
    requested = payload.get("selectedCalendarIds")
    if not isinstance(requested, list) or any(not isinstance(value, str) or not value for value in requested):
        raise ApiError(400, "selectedCalendarIds must be a list of calendar ids.")
    requested = list(dict.fromkeys(requested))
    if len(requested) > 50:
        raise ApiError(400, "Select no more than 50 calendars.")
    available_response = list_calendars(user_id)
    available = {item["id"] for item in json.loads(available_response["body"])["calendars"]}
    if any(value not in available for value in requested):
        raise ApiError(400, "One or more selected calendars are no longer accessible.")
    integration = integration_item(user_id)
    integration = {**integration, "selectedCalendarIds": requested, "updatedAt": now_iso(), "lastErrorCode": None}
    table().put_item(Item={key: value for key, value in integration.items() if value is not None})
    enqueue_availability_sync(user_id=user_id, reason="calendar_selection_changed")
    return response(200, {"integration": public_integration(integration)})


def request_sync(user_id):
    integration = integration_item(user_id)
    if not integration or integration.get("status") != "connected":
        raise ApiError(409, "Connect Google Calendar before syncing.")
    requested_at = parse_iso_datetime(integration.get("lastSyncRequestedAt"))
    if requested_at and datetime.now(timezone.utc) - requested_at < timedelta(minutes=5):
        raise ApiError(429, "Calendar refresh was already requested. Try again in a few minutes.")
    integration = {**integration, "lastSyncRequestedAt": now_iso(), "updatedAt": now_iso()}
    table().put_item(Item=integration)
    enqueue_availability_sync(user_id=user_id, reason="manual_refresh")
    return response(202, {"status": "queued"})


def clear_automatic_availability(user_id):
    memberships = table().query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(user_pk(user_id)),
    ).get("Items", [])
    for membership_ref in memberships:
        if not str(membership_ref.get("SK", "")).startswith("MEMBER#"):
            continue
        club_id = membership_ref.get("clubId")
        membership = get_item(f"CLUB#{club_id}", f"MEMBER#{user_id}")
        if not membership:
            continue
        membership = {**membership, "shareCalendarAvailability": False, "updatedAt": now_iso()}
        table().put_item(Item=membership)
        for night in all_items(f"CLUB#{club_id}", "MOVIE_NIGHT#"):
            record = get_item(f"MOVIE_NIGHT#{night['movieNightId']}", f"AVAILABILITY#{user_id}")
            if record:
                record = {
                    **record,
                    "calendarStatuses": {},
                    "calendarSyncStatus": "disconnected",
                    "updatedAt": now_iso(),
                }
                record.pop("calendarSyncedAt", None)
                table().put_item(Item=record)


def disconnect(user_id):
    integration = integration_item(user_id)
    if integration:
        try:
            _access_token, refresh_token = fresh_access_token(user_id, integration)
            request_json(REVOKE_URL, method="POST", form={"token": refresh_token})
        except ApiError:
            pass
        table().delete_item(Key={"PK": integration["PK"], "SK": integration["SK"]})
    clear_automatic_availability(user_id)
    return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"}, "body": ""}


@handle
def handler(event, context):
    path = (event.get("path") or event.get("rawPath") or "").rstrip("/")
    method = (event.get("httpMethod") or "GET").upper()
    if path.endswith("/integrations/google-calendar/callback"):
        return complete_authorization(event)

    require_enabled()
    user = claims(event)
    if path.endswith("/authorize") and method == "POST":
        return begin_authorization(user, parse_body(event))
    if path.endswith("/calendars") and method == "GET":
        return list_calendars(user["userId"])
    if path.endswith("/sync") and method == "POST":
        return request_sync(user["userId"])
    if method == "GET":
        return response(200, {"integration": public_integration(integration_item(user["userId"]))})
    if method == "PUT":
        return select_calendars(user["userId"], parse_body(event))
    if method == "DELETE":
        return disconnect(user["userId"])
    raise ApiError(405, "Method not allowed.")
