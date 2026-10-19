import hashlib
import json
from botocore.exceptions import ClientError
from cmc_shared import (ADMIN_ROLES, ApiError, claims, handle, normalize_movie_snapshot, parse_body,
                        path_param, require_membership, response, transact_write_items, public_movie_night, get_item, club_pk)
from cmc_events import build_night, member_check


@handle
def handler(event, context):
    club_id = path_param(event, "clubId")
    user = claims(event)
    membership = require_membership(club_id, user["userId"], ADMIN_ROLES)
    payload = parse_body(event)
    raw_key = payload.get("idempotencyKey")
    key = None
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if raw_key is not None:
        if not isinstance(raw_key, str) or not raw_key.strip() or len(raw_key) > 200:
            raise ApiError(400, "idempotencyKey must be text up to 200 characters.")
        key = {"PK": club_pk(club_id), "SK": "CREATE_NIGHT#" + hashlib.sha256(raw_key.encode()).hexdigest()}
        retry = replay(key, fingerprint)
        if retry:
            return response(200, {"movieNight": public_movie_night(retry)})
    item, puts = build_night(club_id, user["userId"], payload, normalize_movie_snapshot(payload))
    if key:
        puts.append({"Item": {**key, "fingerprint": fingerprint, "movieNightId": item["movieNightId"]},
                     "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"})
    try:
        transact_write_items(puts=puts, checks=[member_check(club_id, user["userId"], membership)])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            require_membership(club_id, user["userId"], ADMIN_ROLES)
            retry = replay(key, fingerprint) if key else None
            if retry:
                return response(200, {"movieNight": public_movie_night(retry)})
            raise ApiError(409, "Movie night already exists or membership changed.") from exc
        raise
    return response(201, {"movieNight": public_movie_night(item)})


def replay(key, fingerprint):
    record = get_item(key["PK"], key["SK"])
    if not record:
        return None
    if record["fingerprint"] != fingerprint:
        raise ApiError(409, "Idempotency key was used with different input.")
    return get_item(key["PK"], f"MOVIE_NIGHT#{record['movieNightId']}")
