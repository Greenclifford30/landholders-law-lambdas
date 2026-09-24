import re

from cmc_shared import ApiError, claims, get_item, handle, now_iso, parse_body, put_item, response


ZIP_CODE_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
PREFERENCES_SK = "PREFERENCES"
PUSH_SUBSCRIPTION_KEYS = {"endpoint", "keys"}


def preferences_pk(user_id):
    return f"USER#{user_id}"


def public_preferences(item):
    return {
        "defaultZipCode": item.get("defaultZipCode", ""),
        "defaultRadiusMiles": item.get("defaultRadiusMiles", 25),
        "preferredFormats": item.get("preferredFormats", []),
        "reminderEmailsEnabled": item.get("reminderEmailsEnabled", True),
        "pushNotificationsEnabled": item.get("pushNotificationsEnabled", False),
        "updatedAt": item.get("updatedAt"),
    }


def get_preferences(user_id):
    item = get_item(preferences_pk(user_id), PREFERENCES_SK)
    if not item:
        raise ApiError(404, "Preferences not found.")
    return response(200, {"preferences": public_preferences(item)})


def normalize_push_subscription(value):
    if not isinstance(value, dict) or set(value) != PUSH_SUBSCRIPTION_KEYS:
        raise ApiError(400, "pushSubscription must contain endpoint and keys.")
    endpoint = value.get("endpoint")
    keys = value.get("keys")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise ApiError(400, "pushSubscription.endpoint must be an HTTPS URL.")
    if not isinstance(keys, dict):
        raise ApiError(400, "pushSubscription.keys must be an object.")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not all(isinstance(key, str) and key for key in (p256dh, auth)):
        raise ApiError(400, "pushSubscription keys are incomplete.")
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def update_preferences(event, user_id):
    payload = parse_body(event)
    existing = get_item(preferences_pk(user_id), PREFERENCES_SK) or {}
    zip_code = str(payload.get("defaultZipCode") or "").strip()
    if not ZIP_CODE_RE.fullmatch(zip_code):
        raise ApiError(400, "defaultZipCode must be a valid US ZIP code.")

    radius = payload.get("defaultRadiusMiles")
    if isinstance(radius, bool):
        raise ApiError(400, "defaultRadiusMiles must be an integer.")
    try:
        radius = int(radius)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "defaultRadiusMiles must be an integer.") from exc
    if radius < 1 or radius > 100:
        raise ApiError(400, "defaultRadiusMiles must be between 1 and 100.")

    formats = payload.get("preferredFormats", [])
    if not isinstance(formats, list):
        raise ApiError(400, "preferredFormats must be a list.")
    normalized_formats = []
    for value in formats:
        if not isinstance(value, str):
            raise ApiError(400, "preferredFormats entries must be strings.")
        value = value.strip()
        if value and value not in normalized_formats:
            normalized_formats.append(value)

    updated_at = now_iso()
    reminder_emails_enabled = payload.get("reminderEmailsEnabled", True)
    if not isinstance(reminder_emails_enabled, bool):
        raise ApiError(400, "reminderEmailsEnabled must be a boolean.")
    push_notifications_enabled = payload.get("pushNotificationsEnabled", existing.get("pushNotificationsEnabled", False))
    if not isinstance(push_notifications_enabled, bool):
        raise ApiError(400, "pushNotificationsEnabled must be a boolean.")
    push_subscription = existing.get("pushSubscription")
    if "pushSubscription" in payload:
        push_subscription = normalize_push_subscription(payload["pushSubscription"])
    if push_notifications_enabled and not push_subscription:
        raise ApiError(400, "A pushSubscription is required to enable push notifications.")
    item = {
        "PK": preferences_pk(user_id),
        "SK": PREFERENCES_SK,
        "entityType": "userPreferences",
        "userId": user_id,
        "defaultZipCode": zip_code,
        "defaultRadiusMiles": radius,
        "preferredFormats": normalized_formats,
        "reminderEmailsEnabled": reminder_emails_enabled,
        "pushNotificationsEnabled": push_notifications_enabled,
        "updatedAt": updated_at,
    }
    if push_subscription:
        item["pushSubscription"] = push_subscription
    put_item(item)
    return response(200, {"preferences": public_preferences(item)})


@handle
def handler(event, context):
    user_id = claims(event)["userId"]
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    if method == "GET":
        return get_preferences(user_id)
    if method == "PUT":
        return update_preferences(event, user_id)
    raise ApiError(405, "Method not allowed.")
