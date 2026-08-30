import os

import boto3
from boto3.dynamodb.conditions import Key

from cmc_shared import list_rsvps, list_votes, now_iso, put_item, table


ses = boto3.client("ses")


def notification_copy(event):
    title = event.get("movieTitle") or "Movie night"
    kind = event["notificationType"]
    copy = {
        "voting_open": ("Voting is open", f"Vote for your preferred showtimes for {title}."),
        "showtime_confirmed": ("Your movie night is confirmed", f"{title} has a confirmed showtime. Please RSVP."),
        "showtime_changed": ("Your movie night changed", f"The confirmed showtime for {title} changed. Please review and RSVP."),
        "movie_night_cancelled": ("Movie night cancelled", f"{title} has been cancelled."),
        "vote_reminder": ("Vote reminder", f"Voting for {title} closes in about 24 hours."),
        "rsvp_reminder": ("RSVP reminder", f"{title} is about 24 hours away. Let your club know if you are going."),
    }
    return copy[kind]


def eligible_members(event):
    members = table().query(KeyConditionExpression=Key("PK").eq(f"CLUB#{event['clubId']}") & Key("SK").begins_with("MEMBER#")).get("Items", [])
    users = [member for member in members if member.get("status", "active") == "active"]
    if event["notificationType"] == "vote_reminder":
        voted = {item.get("userId") for item in list_votes(event["movieNightId"])}
        users = [member for member in users if member.get("userId") not in voted]
    if event["notificationType"] == "rsvp_reminder":
        rsvped = {item.get("userId") for item in list_rsvps(event["movieNightId"])}
        users = [member for member in users if member.get("userId") not in rsvped]
    return users


def reminder_email_enabled(user_id):
    preferences = table().get_item(Key={"PK": f"USER#{user_id}", "SK": "PREFERENCES"}).get("Item") or {}
    return preferences.get("reminderEmailsEnabled", True)


def deliver(event):
    subject, body = notification_copy(event)
    link = f"{os.environ.get('APP_BASE_URL', '').rstrip('/')}/clubs/{event['clubId']}"
    source = os.environ.get("NOTIFICATION_EMAIL_FROM")
    is_reminder = event["notificationType"] in {"vote_reminder", "rsvp_reminder"}
    created_at = now_iso()
    for member in eligible_members(event):
        user_id = member["userId"]
        notification_id = event["eventId"]
        item = {
            "PK": f"USER#{user_id}", "SK": f"NOTIFICATION#{notification_id}",
            "entityType": "notification", "notificationId": notification_id,
            "userId": user_id, "clubId": event["clubId"], "movieNightId": event["movieNightId"],
            "type": event["notificationType"], "title": subject, "body": body,
            "href": f"/clubs/{event['clubId']}", "createdAt": created_at, "emailStatus": "not_configured",
        }
        try:
            put_item(item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
        except Exception:
            continue
        if source and member.get("email") and (not is_reminder or reminder_email_enabled(user_id)):
            send_args = {"Source": source, "Destination": {"ToAddresses": [member["email"]]}, "Message": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": f"{body}\n\nOpen Movie Club: {link}"}}}}
            if os.environ.get("NOTIFICATION_EMAIL_CONFIGURATION_SET"):
                send_args["ConfigurationSetName"] = os.environ["NOTIFICATION_EMAIL_CONFIGURATION_SET"]
            ses.send_email(**send_args)
            table().update_item(Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression="SET emailStatus = :status, emailedAt = :at", ExpressionAttributeValues={":status": "sent", ":at": now_iso()})


def process_outbox():
    result = table().query(KeyConditionExpression=Key("PK").eq("NOTIFICATION_OUTBOX") & Key("SK").begins_with("EVENT#"))
    for event in result.get("Items", []):
        if event.get("status") != "pending":
            continue
        deliver(event)
        table().update_item(Key={"PK": event["PK"], "SK": event["SK"]}, UpdateExpression="SET #status = :status, deliveredAt = :at", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": "delivered", ":at": now_iso()})


def process_due():
    result = table().query(KeyConditionExpression=Key("PK").eq("NOTIFICATION_DUE") & Key("SK").lte(f"DUE#{now_iso()}~"))
    for reminder in result.get("Items", []):
        if reminder.get("status") != "pending":
            continue
        movie_night = table().get_item(Key={"PK": f"CLUB#{reminder['clubId']}", "SK": f"MOVIE_NIGHT#{reminder['movieNightId']}"}).get("Item")
        expected_status = "voting" if reminder["notificationType"] == "vote_reminder" else "confirmed"
        if movie_night and movie_night.get("status") == expected_status:
            deliver(reminder)
        table().update_item(Key={"PK": reminder["PK"], "SK": reminder["SK"]}, UpdateExpression="SET #status = :status, deliveredAt = :at", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": "delivered", ":at": now_iso()})


def handler(event, context):
    process_outbox()
    process_due()
    return {"ok": True}
