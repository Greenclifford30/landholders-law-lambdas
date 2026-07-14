import re

from cmc_shared import ApiError, claims, get_item, handle, now_iso, parse_body, put_item, response


ZIP_CODE_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
PREFERENCES_SK = "PREFERENCES"


def preferences_pk(user_id):
    return f"USER#{user_id}"


def public_preferences(item):
    return {
        "defaultZipCode": item.get("defaultZipCode", ""),
        "defaultRadiusMiles": item.get("defaultRadiusMiles", 25),
        "preferredFormats": item.get("preferredFormats", []),
        "updatedAt": item.get("updatedAt"),
    }


def get_preferences(user_id):
    item = get_item(preferences_pk(user_id), PREFERENCES_SK)
    if not item:
        raise ApiError(404, "Preferences not found.")
    return response(200, {"preferences": public_preferences(item)})


def update_preferences(event, user_id):
    payload = parse_body(event)
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
    item = {
        "PK": preferences_pk(user_id),
        "SK": PREFERENCES_SK,
        "entityType": "userPreferences",
        "userId": user_id,
        "defaultZipCode": zip_code,
        "defaultRadiusMiles": radius,
        "preferredFormats": normalized_formats,
        "updatedAt": updated_at,
    }
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
