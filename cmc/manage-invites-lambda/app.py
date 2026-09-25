import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from cmc_shared import (
    ADMIN_ROLES,
    ApiError,
    claims,
    club_pk,
    handle,
    new_id,
    now_iso,
    parse_body,
    path_param,
    public_movie_night,
    query_items,
    require_membership,
    response,
    table,
    transact_write_items,
)


ses = boto3.client("ses")
cognito = boto3.client("cognito-idp")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def invite_log(event, action, **fields):
    """Emit safe, correlated invite-flow diagnostics without credentials or tokens."""
    request_id = (event.get("headers") or {}).get("x-movie-club-request-id") or (event.get("requestContext") or {}).get("requestId")
    logger.info(json.dumps({"event": "movie_club_invite", "action": action, "requestId": request_id, **fields}))


def normalize_email(value):
    email = str(value or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ApiError(400, "A valid email address is required.")
    return email


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_public(item):
    body = public_movie_night(item)
    body.pop("tokenHash", None)
    return body


def find_invite_by_token(token):
    result = table().query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq(f"INVITE_TOKEN#{token_hash(token)}"),
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def expiry_iso(days=14):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expiry_epoch(days=14):
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


def parse_iso(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def app_base_url(event):
    configured = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if configured and configured not in {"http://localhost:3000", "https://localhost:3000"}:
        return configured
    headers = event.get("headers") or {}
    forwarded_origin = headers.get("x-movie-club-app-origin") or headers.get("X-Movie-Club-App-Origin")
    if forwarded_origin:
        return forwarded_origin.rstrip("/")
    if configured:
        return configured.rstrip("/")
    origin = headers.get("origin") or headers.get("Origin")
    return (origin or "http://localhost:3000").rstrip("/")


def send_invite_email(email, club, token, event):
    source = os.environ.get("INVITE_EMAIL_FROM")
    if not source:
        return
    link = f"{app_base_url(event)}/invites/{token}"
    club_name = club.get("name") or "Movie Club"
    ses.send_email(
        Source=source,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": f"You're invited to {club_name}"},
            "Body": {
                "Text": {
                    "Data": f"You have been invited to join {club_name} on Movie Club.\n\nAccept your invite: {link}\n\nThis invite expires in 14 days."
                }
            },
        },
    )


def add_to_friend_group(event, user, invite):
    user_pool_id = os.environ.get("COGNITO_USER_POOL_ID")
    if not user_pool_id:
        raise ApiError(500, "Cognito user pool is not configured for invite acceptance.")
    username = user["raw"].get("cognito:username") or user.get("email") or user["userId"]
    invite_log(event, "cognito_group_start", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12])
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName="Friend",
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        invite_log(event, "cognito_group_failed", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12], errorCode=error.get("Code"))
        raise
    invite_log(event, "cognito_group_complete", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12])


def membership_for_invite(invite, user, updated_at):
    return {
        "PK": club_pk(invite["clubId"]),
        "SK": f"MEMBER#{user['userId']}",
        "GSI1PK": f"USER#{user['userId']}",
        "GSI1SK": f"CLUB#{invite['clubId']}",
        "clubId": invite["clubId"],
        "userId": user["userId"],
        "email": user.get("email") or "",
        "name": user.get("name") or "",
        "role": "friend",
        "status": "active",
        "createdAt": updated_at,
        "updatedAt": updated_at,
    }


def accept_email_invite(invite, membership, existing_membership, user, updated_at):
    invite_update = {
        "Key": {"PK": invite["PK"], "SK": invite["SK"]},
        "ConditionExpression": "#status = :pending",
        "UpdateExpression": (
            "SET #status = :status, acceptedBy = :userId, acceptedAt = :acceptedAt, "
            "updatedAt = :updatedAt, GSI1PK = :gsi1pk"
        ),
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":pending": "pending",
            ":status": "accepted",
            ":userId": user["userId"],
            ":acceptedAt": updated_at,
            ":updatedAt": updated_at,
            ":gsi1pk": f"CLUB#{invite['clubId']}#INVITES#accepted",
        },
    }
    puts = [] if existing_membership else [{
        "Item": membership,
        "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
    }]
    transact_write_items(puts=puts, updates=[invite_update])


def create_invites(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    club = table().get_item(Key={"PK": club_pk(club_id), "SK": "META"}).get("Item")
    if not club:
        raise ApiError(404, "Club not found.")
    payload = parse_body(event)
    is_share_link = payload.get("shareLink") is True
    raw_emails = payload.get("emails") or []
    if isinstance(raw_emails, str):
        raw_emails = [raw_emails]
    emails = []
    for email in raw_emails:
        normalized = normalize_email(email)
        if normalized not in emails:
            emails.append(normalized)
    if not emails and not is_share_link:
        raise ApiError(400, "emails are required.")

    if is_share_link:
        emails = [None]

    created_at = now_iso()
    invites = []
    for email in emails:
        invite_id = new_id("inv")
        raw_token = secrets.token_urlsafe(32)
        item = {
            "PK": club_pk(club_id),
            "SK": f"INVITE#{invite_id}",
            "GSI1PK": f"CLUB#{club_id}#INVITES#pending",
            "GSI1SK": f"{'SHARE' if email is None else f'EMAIL#{email}'}#INVITE#{invite_id}",
            "GSI2PK": f"INVITE_TOKEN#{token_hash(raw_token)}",
            "GSI2SK": f"CLUB#{club_id}#INVITE#{invite_id}",
            "clubId": club_id,
            "clubName": club.get("name", ""),
            "inviteId": invite_id,
            "inviteType": "share_link" if email is None else "email",
            "role": "friend",
            "status": "pending",
            "tokenHash": token_hash(raw_token),
            "expiresAt": expiry_iso(),
            # "expiresAtEpoch": expiry_epoch(),
            "createdBy": user["userId"],
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        if email is not None:
            item["email"] = email
        table().put_item(Item=item)
        if email is not None:
            send_invite_email(email, club, raw_token, event)
        public_item = invite_public(item)
        public_item["inviteUrl"] = f"{app_base_url(event)}/invites/{raw_token}"
        invites.append(public_item)
    return response(201, {"invites": invites})


def list_invites(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    result = table().query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"CLUB#{club_id}#INVITES#pending"),
    )
    invites = []
    for invite in result.get("Items", []):
        if parse_iso(invite["expiresAt"]) < datetime.now(timezone.utc):
            invite["status"] = "expired"
        invites.append(invite_public(invite))
    return response(200, {"invites": sorted(invites, key=lambda invite: invite.get("createdAt", ""), reverse=True)})


def list_members(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    memberships = []
    for membership in query_items(club_pk(club_id), "MEMBER#"):
        if membership.get("status", "active") != "active":
            continue
        public_membership = public_movie_night(membership)
        preferences = get_item(f"USER#{membership['userId']}", "PREFERENCES") or {}
        public_membership["reminderEmailsEnabled"] = preferences.get("reminderEmailsEnabled", True)
        public_membership["pushNotificationsEnabled"] = preferences.get("pushNotificationsEnabled", False)
        memberships.append(public_membership)
    memberships.sort(key=lambda membership: ((membership.get("name") or membership.get("email") or "").lower(), membership["userId"]))
    return response(200, {"members": memberships})


def revoke_invite(club_id, invite_id, updated_at):
    invite = table().get_item(Key={"PK": club_pk(club_id), "SK": f"INVITE#{invite_id}"}).get("Item")
    if not invite:
        raise ApiError(404, "Invite not found.")
    if invite.get("status") != "pending":
        raise ApiError(409, "Invite is no longer pending.")
    try:
        table().update_item(
            Key={"PK": invite["PK"], "SK": invite["SK"]},
            ConditionExpression="#status = :pending",
            UpdateExpression="SET #status = :revoked, updatedAt = :updatedAt, GSI1PK = :gsi1pk",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "pending",
                ":revoked": "revoked",
                ":updatedAt": updated_at,
                ":gsi1pk": f"CLUB#{club_id}#INVITES#revoked",
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise ApiError(409, "Invite is no longer pending.") from exc
        raise


def revoke_invite_by_id(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    invite_id = path_param(event, "inviteId")
    revoke_invite(club_id, invite_id, now_iso())
    return response(200, {"inviteId": invite_id, "status": "revoked"})


def revoke_all_invites(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    pending = []
    query_args = {
        "IndexName": "GSI1",
        "KeyConditionExpression": Key("GSI1PK").eq(f"CLUB#{club_id}#INVITES#pending"),
    }
    while True:
        result = table().query(**query_args)
        pending.extend(result.get("Items", []))
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break
        query_args["ExclusiveStartKey"] = last_key
    revoked_count = 0
    updated_at = now_iso()
    for invite in pending:
        try:
            revoke_invite(club_id, invite["inviteId"], updated_at)
            revoked_count += 1
        except ApiError as exc:
            if exc.status != 409:
                raise
    return response(200, {"revokedCount": revoked_count})


def get_invite(event):
    token = path_param(event, "token")
    invite = find_invite_by_token(token)
    if not invite:
        raise ApiError(404, "Invite not found.")
    invite_log(event, "lookup", tokenHashPrefix=invite["tokenHash"][:12], status=invite.get("status"))
    if invite.get("status") == "pending" and parse_iso(invite["expiresAt"]) < datetime.now(timezone.utc):
        invite["status"] = "expired"
    return response(200, {"invite": invite_public(invite)})


def accept_invite(event):
    token = path_param(event, "token")
    user = claims(event)
    invite = find_invite_by_token(token)
    if not invite:
        raise ApiError(404, "Invite not found.")
    invite_log(event, "accept_start", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12], status=invite.get("status"))
    if invite.get("status") != "pending":
        if invite.get("status") == "accepted" and invite.get("acceptedBy") == user["userId"]:
            membership = table().get_item(
                Key={"PK": club_pk(invite["clubId"]), "SK": f"MEMBER#{user['userId']}"}
            ).get("Item")
            if membership:
                add_to_friend_group(event, user, invite)
                invite_log(event, "accept_idempotent_complete", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12])
                return response(200, {"membership": public_movie_night(membership), "clubId": invite["clubId"]})
        raise ApiError(409, "Invite is no longer pending.")
    if parse_iso(invite["expiresAt"]) < datetime.now(timezone.utc):
        table().update_item(
            Key={"PK": invite["PK"], "SK": invite["SK"]},
            UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "expired", ":updatedAt": now_iso()},
        )
        raise ApiError(410, "Invite has expired.")
    if invite.get("email") and normalize_email(user.get("email")) != invite.get("email"):
        raise ApiError(403, "This invite belongs to a different email address.")

    is_share_link = invite.get("inviteType") == "share_link" or not invite.get("email")
    updated_at = now_iso()
    # Cognito is idempotent and must succeed before any active club membership is written.
    add_to_friend_group(event, user, invite)
    membership_key = {"PK": club_pk(invite["clubId"]), "SK": f"MEMBER#{user['userId']}"}
    existing_membership = table().get_item(Key=membership_key).get("Item")
    membership = existing_membership or membership_for_invite(invite, user, updated_at)
    invite_log(event, "membership_persist_start", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12], shareLink=is_share_link)
    if not is_share_link:
        try:
            accept_email_invite(invite, membership, existing_membership, user, updated_at)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ApiError(409, "Invite is no longer pending.")
            raise
    elif not existing_membership:
        try:
            table().put_item(
                Item=membership,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            membership = table().get_item(Key=membership_key).get("Item")
            if not membership:
                raise
    invite_log(event, "accept_complete", subject=user["userId"], tokenHashPrefix=invite["tokenHash"][:12], clubId=invite["clubId"])
    return response(200, {"membership": public_movie_night(membership), "clubId": invite["clubId"]})


@handle
def handler(event, context):
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    path_params = event.get("pathParameters") or {}
    path = event.get("path") or ""
    if method == "GET" and path_params.get("clubId") and path.endswith("/members"):
        return list_members(event)
    if method == "DELETE" and path_params.get("inviteId"):
        return revoke_invite_by_id(event)
    if method == "DELETE" and path_params.get("clubId"):
        return revoke_all_invites(event)
    if method == "POST" and path_params.get("clubId"):
        return create_invites(event)
    if method == "GET" and path_params.get("clubId"):
        return list_invites(event)
    if method == "POST":
        return accept_invite(event)
    return get_invite(event)
