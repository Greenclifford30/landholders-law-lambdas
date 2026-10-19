"""Club film suggestions. Conditional writes serialize transitions per proposal."""
import hashlib
import json
from botocore.exceptions import ClientError
from cmc_shared import (ApiError, club_pk, get_item, now_iso, new_id, public_movie_night,
                        transact_write_items, require_membership, dynamodb_value)
from cmc_events import all_items, build_night, paginate, member_check
from cmc_movies import resolve_movie

ROLES = {"admin", "friend"}
UNIQUE = "attribute_not_exists(PK) AND attribute_not_exists(SK)"


def text(payload, field):
    value = payload.get(field, "")
    if not isinstance(value, str) or len(value) > 1000:
        raise ApiError(400, f"{field} must be text up to 1,000 characters.")
    return value.strip()


def proposal_key(club_id, proposal_id):
    return {"PK": club_pk(club_id), "SK": f"PROPOSAL#{proposal_id}"}


def load(club_id, proposal_id):
    item = get_item(club_pk(club_id), f"PROPOSAL#{proposal_id}")
    if not item:
        raise ApiError(404, "Proposal not found.")
    return item


def visible(item, user_id, members=None):
    members = members if members is not None else {m["SK"][7:]: m for m in all_items(club_pk(item["clubId"]), "MEMBER#") if m.get("status", "active") == "active"}
    endorsements = all_items(f"PROPOSAL#{item['proposalId']}", "ENDORSEMENT#")
    active = {e["userId"] for e in endorsements if members.get(e["userId"], {}).get("role") in ROLES}
    author = members.get(item["proposedByUserId"])
    return {**public_movie_night(item), "proposerName": (author.get("name") or "Member") if author else "Former member",
            "viewerCanWithdraw": item["status"] == "open" and item["proposedByUserId"] == user_id,
            "endorsementCount": len(active), "viewerHasEndorsed": user_id in active}


def list_proposals(club_id, user_id, event):
    status = (event.get("queryStringParameters") or {}).get("status", "open")
    if status not in {"open", "scheduled", "withdrawn", "dismissed"}:
        raise ApiError(400, "Invalid proposal status.")
    members = {m["SK"][7:]: m for m in all_items(club_pk(club_id), "MEMBER#") if m.get("status", "active") == "active"}
    items = [visible(p, user_id, members) for p in all_items(club_pk(club_id), "PROPOSAL#") if p["status"] == status]
    order = lambda p: (-p["endorsementCount"], p["createdAt"], p["proposalId"])
    items.sort(key=order)
    page, cursor = paginate(items, event, f"proposals:{club_id}:{status}", order)
    return {"proposals": page, "nextCursor": cursor}


def create(club_id, user, membership, payload):
    reason = text(payload, "reason")
    movie = resolve_movie(payload.get("provider"), payload.get("externalId"))
    at = now_iso()
    identifier = new_id("mp")
    item = {**proposal_key(club_id, identifier), "proposalId": identifier, "clubId": club_id,
            "movie": movie, "proposedByUserId": user["userId"], "reason": reason,
            "status": "open", "version": 1, "createdAt": at, "updatedAt": at}
    claim = claim_key(item)
    try:
        transact_write_items(puts=[{"Item": dynamodb_value(item), "ConditionExpression": UNIQUE},
                                  {"Item": {**claim, "proposalId": identifier}, "ConditionExpression": UNIQUE}],
                             checks=[member_check(club_id, user["userId"], membership)])
    except ClientError as exc:
        if not conflict(exc):
            raise
        existing = get_item(claim["PK"], claim["SK"])
        if existing:
            raise ApiError(409, "This film already has an open suggestion.", {"existingProposalId": existing["proposalId"]}) from exc
        raise ApiError(409, "Membership or proposal changed. Retry the request.") from exc
    return visible(item, user["userId"])


def claim_key(item):
    return {"PK": club_pk(item["clubId"]), "SK": f"OPEN_FILM#{item['movie']['provider']}#{item['movie']['externalId']}"}


def conflict(exc):
    return exc.response.get("Error", {}).get("Code") in {"TransactionCanceledException", "ConditionalCheckFailedException"}


def checked_put(previous, updated):
    return {"Item": dynamodb_value(updated), "ConditionExpression": "#version = :version AND #status = :open",
            "ExpressionAttributeNames": {"#version": "version", "#status": "status"},
            "ExpressionAttributeValues": {":version": previous["version"], ":open": "open"}}


def release_claim(item):
    return {"Key": claim_key(item), "ConditionExpression": "proposalId = :id", "ExpressionAttributeValues": {":id": item["proposalId"]}}


def expected_version(payload, item):
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ApiError(400, "version must be a positive integer.")
    if version != item["version"] or item["status"] != "open":
        raise ApiError(409, "Proposal changed. Reload and try again.")


def update(item, user, membership, payload):
    expected_version(payload, item)
    status = payload.get("status", "open")
    author = item["proposedByUserId"] == user["userId"]
    if status not in {"open", "withdrawn", "dismissed"}:
        raise ApiError(400, "Unsupported proposal transition.")
    if "reason" in payload and not author:
        raise ApiError(403, "Only the author can edit the reason.")
    if status == "dismissed":
        if membership["role"] != "admin":
            raise ApiError(403, "Only admins may dismiss proposals.")
        moderation = text(payload, "moderationReason")
        if not moderation:
            raise ApiError(400, "moderationReason is required.")
    elif not author:
        raise ApiError(403, "Only the author can edit or withdraw this proposal.")
    updated = {**item, "status": status, "version": item["version"] + 1, "updatedAt": now_iso()}
    if "reason" in payload:
        updated["reason"] = text(payload, "reason")
    if status == "dismissed":
        updated.update(moderationReason=moderation, moderatedByUserId=user["userId"], moderatedAt=updated["updatedAt"])
    commit(item, updated, user, membership, deletes=[release_claim(item)] if status != "open" else [])
    return visible(updated, user["userId"])


def commit(item, updated, user, membership, puts=None, deletes=None):
    try:
        transact_write_items(puts=[checked_put(item, updated), *(puts or [])], deletes=deletes,
                             checks=[member_check(item["clubId"], user["userId"], membership)])
    except ClientError as exc:
        if conflict(exc):
            raise ApiError(409, "Proposal or membership changed. Reload and try again.") from exc
        raise


def endorse(club_id, proposal_id, user, membership, enabled):
    # A concurrent unrelated edit may win; retry using the latest version.
    for attempt in range(4):
        item = load(club_id, proposal_id)
        if item["status"] != "open":
            raise ApiError(409, "Only open proposals accept endorsement changes.")
        key = {"PK": f"PROPOSAL#{proposal_id}", "SK": f"ENDORSEMENT#{user['userId']}"}
        existing = get_item(key["PK"], key["SK"])
        if bool(existing) == enabled:
            return visible(item, user["userId"])
        updated = {**item, "version": item["version"] + 1, "updatedAt": now_iso()}
        try:
            commit(item, updated, user, membership,
                   puts=[{"Item": {**key, "userId": user["userId"], "createdAt": now_iso()}, "ConditionExpression": UNIQUE}] if enabled else [],
                   deletes=[] if enabled else [{"Key": key}])
            return visible(updated, user["userId"])
        except ApiError as exc:
            if exc.status_code != 409 or attempt == 3:
                raise
            membership = require_membership(club_id, user["userId"], ROLES)


def schedule(item, user, membership, payload):
    raw_key = payload.get("idempotencyKey")
    if not isinstance(raw_key, str) or not raw_key.strip() or len(raw_key) > 200:
        raise ApiError(400, "idempotencyKey is required (up to 200 characters).")
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    key = {"PK": f"PROPOSAL#{item['proposalId']}", "SK": f"SCHEDULE#{digest}"}
    fingerprint = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "idempotencyKey"}, sort_keys=True).encode()).hexdigest()
    retry = get_item(key["PK"], key["SK"])
    if retry:
        if retry["fingerprint"] != fingerprint:
            raise ApiError(409, "Idempotency key was used with different input.")
        night = get_item(club_pk(item["clubId"]), f"MOVIE_NIGHT#{retry['movieNightId']}")
        return {"proposal": visible(load(item["clubId"], item["proposalId"]), user["userId"]), "movieNight": public_movie_night(night)}
    expected_version(payload, item)
    night, puts = build_night(item["clubId"], user["userId"], {k: v for k, v in payload.items() if k != "movieNightId"}, item["movie"])
    night["proposalId"] = item["proposalId"]
    night["proposedByUserId"] = item["proposedByUserId"]
    updated = {**item, "status": "scheduled", "movieNightId": night["movieNightId"], "version": item["version"] + 1, "updatedAt": now_iso()}
    puts.append({"Item": {**key, "fingerprint": fingerprint, "movieNightId": night["movieNightId"]}, "ConditionExpression": UNIQUE})
    try:
        commit(item, updated, user, membership, puts=puts, deletes=[release_claim(item)])
    except ApiError as exc:
        if exc.status_code == 409 and get_item(key["PK"], key["SK"]):
            require_membership(item["clubId"], user["userId"], {"admin"})
            return schedule(load(item["clubId"], item["proposalId"]), user, membership, payload)
        raise
    return {"proposal": visible(updated, user["userId"]), "movieNight": public_movie_night(night)}
