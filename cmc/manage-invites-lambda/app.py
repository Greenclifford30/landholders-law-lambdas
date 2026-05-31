import hashlib
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
    require_membership,
    response,
    table,
)


ses = boto3.client("ses")


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
    configured = os.environ.get("APP_BASE_URL")
    if configured:
        return configured.rstrip("/")
    headers = event.get("headers") or {}
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


def create_invites(event):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"], ADMIN_ROLES)
    club = table().get_item(Key={"PK": club_pk(club_id), "SK": "META"}).get("Item")
    if not club:
        raise ApiError(404, "Club not found.")
    payload = parse_body(event)
    raw_emails = payload.get("emails") or []
    if isinstance(raw_emails, str):
        raw_emails = [raw_emails]
    emails = []
    for email in raw_emails:
        normalized = normalize_email(email)
        if normalized not in emails:
            emails.append(normalized)
    if not emails:
        raise ApiError(400, "emails are required.")

    created_at = now_iso()
    invites = []
    for email in emails:
        invite_id = new_id("inv")
        raw_token = secrets.token_urlsafe(32)
        item = {
            "PK": club_pk(club_id),
            "SK": f"INVITE#{invite_id}",
            "GSI1PK": f"CLUB#{club_id}#INVITES#pending",
            "GSI1SK": f"EMAIL#{email}#INVITE#{invite_id}",
            "GSI2PK": f"INVITE_TOKEN#{token_hash(raw_token)}",
            "GSI2SK": f"CLUB#{club_id}#INVITE#{invite_id}",
            "clubId": club_id,
            "clubName": club.get("name", ""),
            "inviteId": invite_id,
            "email": email,
            "role": "friend",
            "status": "pending",
            "tokenHash": token_hash(raw_token),
            "expiresAt": expiry_iso(),
            "expiresAtEpoch": expiry_epoch(),
            "createdBy": user["userId"],
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        table().put_item(Item=item)
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


def get_invite(event):
    token = path_param(event, "token")
    invite = find_invite_by_token(token)
    if not invite:
        raise ApiError(404, "Invite not found.")
    if invite.get("status") == "pending" and parse_iso(invite["expiresAt"]) < datetime.now(timezone.utc):
        invite["status"] = "expired"
    return response(200, {"invite": invite_public(invite)})


def accept_invite(event):
    token = path_param(event, "token")
    user = claims(event)
    invite = find_invite_by_token(token)
    if not invite:
        raise ApiError(404, "Invite not found.")
    if invite.get("status") != "pending":
        raise ApiError(409, "Invite is no longer pending.")
    if parse_iso(invite["expiresAt"]) < datetime.now(timezone.utc):
        table().update_item(
            Key={"PK": invite["PK"], "SK": invite["SK"]},
            UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "expired", ":updatedAt": now_iso()},
        )
        raise ApiError(410, "Invite has expired.")
    if normalize_email(user.get("email")) != invite.get("email"):
        raise ApiError(403, "This invite belongs to a different email address.")

    updated_at = now_iso()
    membership_key = {"PK": club_pk(invite["clubId"]), "SK": f"MEMBER#{user['userId']}"}
    existing_membership = table().get_item(Key=membership_key).get("Item")
    membership = {
        **membership_key,
        "GSI1PK": f"USER#{user['userId']}",
        "GSI1SK": f"CLUB#{invite['clubId']}",
        "clubId": invite["clubId"],
        "userId": user["userId"],
        "email": invite["email"],
        "name": user.get("name") or "",
        "role": "friend",
        "status": "active",
        "createdAt": updated_at,
        "updatedAt": updated_at,
    }
    if existing_membership:
        membership = existing_membership
    else:
        try:
            table().put_item(
                Item=membership,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    table().update_item(
        Key={"PK": invite["PK"], "SK": invite["SK"]},
        UpdateExpression=(
            "SET #status = :status, acceptedBy = :userId, acceptedAt = :acceptedAt, "
            "updatedAt = :updatedAt, GSI1PK = :gsi1pk"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "accepted",
            ":userId": user["userId"],
            ":acceptedAt": updated_at,
            ":updatedAt": updated_at,
            ":gsi1pk": f"CLUB#{invite['clubId']}#INVITES#accepted",
        },
    )
    return response(200, {"membership": public_movie_night(membership), "clubId": invite["clubId"]})


@handle
def handler(event, context):
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    if method == "POST" and (event.get("pathParameters") or {}).get("clubId"):
        return create_invites(event)
    if method == "GET" and (event.get("pathParameters") or {}).get("clubId"):
        return list_invites(event)
    if method == "POST":
        return accept_invite(event)
    return get_invite(event)
