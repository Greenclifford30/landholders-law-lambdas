"""Versioned event mutations, with atomic audit, retry and notification records."""
import hashlib
import json
from botocore.exceptions import ClientError
from cmc_shared import ApiError, get_item, now_iso, normalize_planning_input, public_movie_night, transact_write_items
from cmc_events import member_check
from cmc_notifications import notification_record, reminder_record, trigger_notification_delivery


def revision(night):
    return int(night.get("planRevision", 1 if night.get("confirmedShowtimeId") or night.get("status") in {"confirmed", "completed"} else 0))


def version_check(night):
    value = int(night.get("version", 0))
    names = {"#v": "version", "#s": "status"}
    values = {":s": night["status"]}
    condition = "attribute_not_exists(#v)" if "version" not in night else "#v = :v"
    if "version" in night:
        values[":v"] = value
    return {"Key": {"PK": night["PK"], "SK": night["SK"]},
            "ConditionExpression": condition + " AND #s = :s",
            "ExpressionAttributeNames": names, "ExpressionAttributeValues": values}


def check_expected(night, payload, field="expectedVersion", required=False):
    expected = payload.get(field)
    if expected is None and not required:
        return
    if type(expected) is not int or expected != int(night.get("version", 0)):
        raise ApiError(409, "Movie night changed. Reload and try again.")


def retry_record(night, user_id, action, payload):
    key = payload.get("idempotencyKey")
    if key is None:
        return None, None
    if not isinstance(key, str) or not key.strip() or len(key) > 200:
        raise ApiError(400, "Invalid idempotencyKey.")
    digest = hashlib.sha256(key.encode()).hexdigest()
    record = {"PK": f"MOVIE_NIGHT#{night['movieNightId']}", "SK": f"RETRY#{user_id}#{action}#{digest}"}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    existing = get_item(record["PK"], record["SK"])
    if existing and existing.get("fingerprint") != fingerprint:
        raise ApiError(409, "Idempotency key was used with different input.")
    return {**record, "fingerprint": fingerprint}, existing


def commit(night, updated, user_id, membership, action, retry=None, notification=None):
    updated = {**updated, "version": int(night.get("version", 0)) + 1, "updatedAt": now_iso()}
    condition = version_check(night)
    put = {"Item": updated, **{k: v for k, v in condition.items() if k != "Key"}}
    puts = [put, {"Item": {"PK": f"MOVIE_NIGHT#{night['movieNightId']}", "SK": f"AUDIT#{updated['version']}",
                           "actorUserId": user_id, "action": action, "createdAt": updated["updatedAt"],
                           "planRevision": revision(updated), "previousPlan": night.get("confirmedShowtime"),
                           "changeReason": updated.get("changeReason")}, "ConditionExpression": "attribute_not_exists(PK)"}]
    if retry:
        puts.append({"Item": {**retry, "result": public_movie_night(updated)}, "ConditionExpression": "attribute_not_exists(PK)"})
    if notification:
        puts.append({"Item": notification_record(updated, notification), "ConditionExpression": "attribute_not_exists(PK)"})
        reminder = reminder_record(updated, notification)
        if reminder:
            puts.append({"Item": reminder, "ConditionExpression": "attribute_not_exists(PK)"})
    try:
        transact_write_items(puts=puts, checks=[member_check(night["clubId"], user_id, membership)])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            if retry:
                existing = get_item(retry["PK"], retry["SK"])
                if existing and existing.get("fingerprint") == retry["fingerprint"]:
                    return existing["result"]
            raise ApiError(409, "Movie night changed. Reload and try again.") from exc
        raise
    if notification:
        trigger_notification_delivery()
    return public_movie_night(updated)


def edit_planning(night, payload, user_id, membership):
    check_expected(night, payload, "version", required=True)
    if night["status"] != "planning":
        raise ApiError(409, "Planning can only be edited before voting opens.")
    fields = normalize_planning_input(payload, night)
    if any(k in payload for k in ("movie", "status", "confirmedShowtime", "confirmedShowtimeId")):
        raise ApiError(400, "Use the event setup or confirmation workflow for this change.")
    return commit(night, {**night, **fields}, user_id, membership, "planning_updated")


def save_noop(night, user_id, membership, retry):
    if not retry:
        return
    try:
        transact_write_items(puts=[{"Item": {**retry, "result": public_movie_night(night)}, "ConditionExpression": "attribute_not_exists(PK)"}],
                             checks=[version_check(night), member_check(night["clubId"], user_id, membership)])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            existing = get_item(retry["PK"], retry["SK"])
            if existing and existing.get("fingerprint") == retry["fingerprint"]:
                return
            raise ApiError(409, "Movie night changed. Reload and try again.") from exc
        raise
