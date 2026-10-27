import base64
from datetime import datetime, timezone
import json
import os
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.conditions import Key

from cmc_availability import emit_calendar_metrics, scheduling_preferences, showtime_window
from cmc_events import upcoming_nights
from cmc_shared import get_item, list_showtimes_by_status, now_iso, parse_iso_datetime, query_items, table


TOKEN_URL = "https://oauth2.googleapis.com/token"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
INTEGRATION_SK = "CALENDAR#GOOGLE"

kms = boto3.client("kms")
secrets_manager = boto3.client("secretsmanager")


class ProviderFailure(Exception):
    def __init__(self, code, retryable=True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def request_json(url, *, form=None, payload=None, headers=None):
    if form is not None:
        body = urlencode(form).encode()
        content_type = "application/x-www-form-urlencoded"
    elif payload is not None:
        body = json.dumps(payload).encode()
        content_type = "application/json"
    else:
        body = None
        content_type = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if content_type:
        request_headers["Content-Type"] = content_type
    try:
        with urlopen(Request(url, data=body, headers=request_headers, method="POST" if body else "GET"), timeout=20) as result:
            raw = result.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8")).get("error")
        except (json.JSONDecodeError, UnicodeDecodeError):
            error = None
        code = error if isinstance(error, str) else (error or {}).get("status")
        if code == "invalid_grant":
            raise ProviderFailure("needs_reauth", retryable=False) from exc
        raise ProviderFailure("rate_limited" if exc.code == 429 else "provider_error") from exc
    except (URLError, TimeoutError) as exc:
        raise ProviderFailure("provider_unavailable") from exc


def credentials():
    secret = secrets_manager.get_secret_value(SecretId=os.environ["GOOGLE_CALENDAR_SECRET_ARN"])
    return json.loads(secret.get("SecretString") or "{}")


def access_token(user_id, integration):
    decrypted = kms.decrypt(
        CiphertextBlob=base64.b64decode(integration["encryptedRefreshToken"]),
        EncryptionContext={"userId": user_id, "provider": "google"},
    )["Plaintext"].decode()
    client = credentials()
    result = request_json(TOKEN_URL, form={
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": decrypted,
        "grant_type": "refresh_token",
    })
    if not result.get("access_token"):
        raise ProviderFailure("provider_error")
    return result["access_token"]


def user_memberships(user_id):
    refs = table().query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_id}"),
    ).get("Items", [])
    result = []
    for ref in refs:
        if not ref.get("clubId") or not str(ref.get("SK", "")).startswith("MEMBER#"):
            continue
        member = get_item(f"CLUB#{ref['clubId']}", f"MEMBER#{user_id}")
        if member and member.get("status", "active") == "active" and member.get("shareCalendarAvailability", False):
            result.append(member)
    return result


def targets_for_user(user_id, only_movie_night_id=None):
    targets = []
    for membership in user_memberships(user_id):
        for night in upcoming_nights(membership["clubId"]):
            if night.get("status") not in {"planning", "voting"}:
                continue
            if only_movie_night_id and night["movieNightId"] != only_movie_night_id:
                continue
            showtimes = sorted(
                list_showtimes_by_status(night["movieNightId"], {"approved"}),
                key=lambda item: item.get("startsAtUtc") or item.get("startsAt") or "",
            )
            if showtimes:
                targets.append((night, showtimes))
    return targets


def time_bounds(targets, preferences):
    windows = [
        showtime_window(showtime, night.get("movie") or {}, preferences)
        for night, showtimes in targets
        for showtime in showtimes
    ]
    windows = [window for window in windows if window]
    if not windows:
        return None
    return min(window["start"] for window in windows), max(window["end"] for window in windows)


def overlaps(start, end, busy):
    return any(start < busy_end and end > busy_start for busy_start, busy_end in busy)


def calendar_statuses(result, selected_calendar_ids, targets, preferences):
    calendars = result.get("calendars") or {}
    busy = []
    partial = False
    for calendar_id in selected_calendar_ids:
        calendar = calendars.get(calendar_id) or {}
        if calendar.get("errors"):
            partial = True
            continue
        for interval in calendar.get("busy") or []:
            start = parse_iso_datetime(interval.get("start"))
            end = parse_iso_datetime(interval.get("end"))
            if start and end:
                busy.append((start, end))
    by_night = {}
    for night, showtimes in targets:
        statuses = {}
        for showtime in showtimes:
            window = showtime_window(showtime, night.get("movie") or {}, preferences)
            if not window:
                statuses[showtime["showtimeId"]] = "unknown"
            elif overlaps(window["start"], window["end"], busy):
                statuses[showtime["showtimeId"]] = "conflict"
            else:
                statuses[showtime["showtimeId"]] = "unknown" if partial else "free"
        by_night[night["movieNightId"]] = statuses
    return by_night, "partial" if partial else "current"


def save_results(user_id, targets, statuses_by_night, sync_status, synced_at):
    for night, _showtimes in targets:
        key = {"PK": f"MOVIE_NIGHT#{night['movieNightId']}", "SK": f"AVAILABILITY#{user_id}"}
        existing = get_item(key["PK"], key["SK"]) or {}
        revision = int(night.get("availabilityRevision", 1))
        manual_overrides = existing.get("manualOverrides", {}) if int(existing.get("availabilityRevision", 0)) == revision else {}
        item = {
            **existing,
            **key,
            "entityType": "movieNightAvailability",
            "movieNightId": night["movieNightId"],
            "clubId": night["clubId"],
            "userId": user_id,
            "availabilityRevision": revision,
            "manualOverrides": manual_overrides,
            "calendarStatuses": statuses_by_night.get(night["movieNightId"], {}),
            "calendarSyncStatus": sync_status,
            "calendarSyncedAt": synced_at,
            "updatedAt": synced_at,
        }
        table().put_item(Item=item)


def mark_reauth(user_id, integration):
    item = {
        **integration,
        "GSI1PK": "CALENDAR_PROVIDER#google#needs_reauth",
        "status": "needs_reauth",
        "lastErrorCode": "needs_reauth",
        "updatedAt": now_iso(),
    }
    table().put_item(Item=item)


def mark_sync_failed(user_id, integration, targets, code):
    failed_at = now_iso()
    save_results(user_id, targets, {}, "failed", failed_at)
    table().put_item(Item={
        **integration,
        "lastErrorCode": code,
        "updatedAt": failed_at,
    })


def sync_user(user_id, only_movie_night_id=None):
    integration = get_item(f"USER#{user_id}", INTEGRATION_SK)
    if not integration or integration.get("status") != "connected":
        return "skipped"
    targets = targets_for_user(user_id, only_movie_night_id)
    if not targets:
        return "skipped"
    selected = integration.get("selectedCalendarIds") or []
    preferences = scheduling_preferences(get_item(f"USER#{user_id}", "PREFERENCES") or {})
    synced_at = now_iso()
    if not selected:
        save_results(user_id, targets, {}, "no_calendars", synced_at)
        return "success"
    bounds = time_bounds(targets, preferences)
    if not bounds:
        return "skipped"
    try:
        token = access_token(user_id, integration)
        result = request_json(FREEBUSY_URL, payload={
            "timeMin": bounds[0].isoformat().replace("+00:00", "Z"),
            "timeMax": bounds[1].isoformat().replace("+00:00", "Z"),
            "timeZone": "UTC",
            "calendarExpansionMax": 50,
            "items": [{"id": calendar_id} for calendar_id in selected],
        }, headers={"Authorization": f"Bearer {token}"})
        statuses, sync_status = calendar_statuses(result, selected, targets, preferences)
        save_results(user_id, targets, statuses, sync_status, synced_at)
        updated = {**integration, "lastSyncedAt": synced_at, "updatedAt": synced_at}
        updated.pop("lastErrorCode", None)
        table().put_item(Item=updated)
        return "success"
    except ProviderFailure as exc:
        if exc.code == "needs_reauth":
            save_results(user_id, targets, {}, "failed", now_iso())
            mark_reauth(user_id, integration)
            emit_calendar_metrics(ReauthorizationRequired=1, SyncFailure=1)
            return "reauth"
        mark_sync_failed(user_id, integration, targets, exc.code)
        raise


def users_for_movie_night(movie_night_id):
    from cmc_shared import query_gsi2_movie_night

    night = query_gsi2_movie_night(movie_night_id)
    if not night:
        return []
    return [
        member["userId"]
        for member in query_items(f"CLUB#{night['clubId']}", "MEMBER#")
        if member.get("status", "active") == "active" and member.get("shareCalendarAvailability", False)
    ]


def process_message(message):
    if message.get("userId"):
        return sync_user(str(message["userId"]), message.get("movieNightId"))
    if message.get("movieNightId"):
        outcomes = []
        for user_id in users_for_movie_night(str(message["movieNightId"])):
            outcomes.append(sync_user(user_id, str(message["movieNightId"])))
        if "reauth" in outcomes:
            return "reauth"
        return "success" if "success" in outcomes else "skipped"
    return "skipped"


def handler(event, context):
    failures = []
    for record in event.get("Records") or []:
        started = perf_counter()
        try:
            outcome = process_message(json.loads(record.get("body") or "{}"))
            if outcome == "success":
                emit_calendar_metrics(SyncSuccess=1, SyncLatencyMs=round((perf_counter() - started) * 1000, 2))
        except ProviderFailure as exc:
            metrics = {"SyncFailure": 1, "SyncLatencyMs": round((perf_counter() - started) * 1000, 2)}
            if exc.code == "rate_limited":
                metrics["ProviderRateLimit"] = 1
            emit_calendar_metrics(**metrics)
            failures.append({"itemIdentifier": record.get("messageId")})
        except Exception:
            emit_calendar_metrics(SyncFailure=1, SyncLatencyMs=round((perf_counter() - started) * 1000, 2))
            failures.append({"itemIdentifier": record.get("messageId")})
    if event.get("Records") is None:
        started = perf_counter()
        try:
            outcome = process_message(event or {})
            if outcome == "success":
                emit_calendar_metrics(SyncSuccess=1, SyncLatencyMs=round((perf_counter() - started) * 1000, 2))
        except ProviderFailure as exc:
            metrics = {"SyncFailure": 1, "SyncLatencyMs": round((perf_counter() - started) * 1000, 2)}
            if exc.code == "rate_limited":
                metrics["ProviderRateLimit"] = 1
            emit_calendar_metrics(**metrics)
            raise
    return {"batchItemFailures": failures}
