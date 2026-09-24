import os
import json
import logging

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from cmc_shared import list_rsvps, list_votes, now_iso, put_item, table
from pywebpush import WebPushException, webpush


ses = boto3.client("ses")
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


def log(event_name, **details):
    """Emit structured diagnostics without recipient addresses or push endpoints."""
    logger.info("%s %s", event_name, json.dumps(details, sort_keys=True, default=str))


def error_details(exc):
    error = getattr(exc, "response", {}).get("Error", {})
    return {
        "errorCode": error.get("Code", type(exc).__name__),
        "errorType": type(exc).__name__,
    }


def delivery_details(item, channel):
    return {
        "channel": channel,
        "clubId": item["clubId"],
        "movieNightId": item["movieNightId"],
        "notificationId": item["notificationId"],
        "notificationType": item["type"],
        "userId": item["userId"],
    }


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
        "test_notification": ("Movie Club notification test", "This is a test of your in-app, email, and browser push notification channels."),
    }
    return copy[kind]


def eligible_members(event):
    members = table().query(KeyConditionExpression=Key("PK").eq(f"CLUB#{event['clubId']}") & Key("SK").begins_with("MEMBER#")).get("Items", [])
    users = [member for member in members if member.get("status", "active") == "active"]
    if event["notificationType"] == "test_notification":
        users = [member for member in users if member.get("userId") == event.get("targetUserId")]
    if event["notificationType"] == "vote_reminder":
        voted = {item.get("userId") for item in list_votes(event["movieNightId"])}
        users = [member for member in users if member.get("userId") not in voted]
    if event["notificationType"] == "rsvp_reminder":
        rsvped = {item.get("userId") for item in list_rsvps(event["movieNightId"])}
        users = [member for member in users if member.get("userId") not in rsvped]
    return users


def user_preferences(user_id):
    return table().get_item(Key={"PK": f"USER#{user_id}", "SK": "PREFERENCES"}).get("Item") or {}


def update_delivery_status(item, channel, status, error=None):
    values = {":status": status, ":at": now_iso()}
    expression = f"SET {channel}Status = :status, {channel}At = :at"
    if error:
        values[":error"] = error_details(error)["errorCode"]
        expression += f", {channel}Error = :error"
    table().update_item(Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression=expression, ExpressionAttributeValues=values)
    details = delivery_details(item, channel)
    details["status"] = status
    if error:
        details.update(error_details(error))
        log("notification_delivery_failed", **details)
    else:
        log("notification_delivery_status", **details)


def send_email(item, member, subject, body, link, is_reminder, preferences):
    source = os.environ.get("NOTIFICATION_EMAIL_FROM")
    if not source:
        update_delivery_status(item, "email", "not_configured")
        return
    if not member.get("email") or (is_reminder and not preferences.get("reminderEmailsEnabled", True)):
        update_delivery_status(item, "email", "disabled")
        return
    try:
        send_args = {"Source": source, "Destination": {"ToAddresses": [member["email"]]}, "Message": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": f"{body}\n\nOpen Movie Club: {link}"}}}}
        if os.environ.get("NOTIFICATION_EMAIL_CONFIGURATION_SET"):
            send_args["ConfigurationSetName"] = os.environ["NOTIFICATION_EMAIL_CONFIGURATION_SET"]
        response = ses.send_email(**send_args)
        update_delivery_status(item, "email", "sent")
        log("notification_email_accepted", **delivery_details(item, "email"), sesMessageId=response.get("MessageId"), configurationSet=bool(send_args.get("ConfigurationSetName")))
    except Exception as exc:
        # Keep the record eligible for the next worker invocation rather than losing a failed email.
        update_delivery_status(item, "email", "failed", exc)


def send_push(item, subject, body, href, preferences):
    subscription = preferences.get("pushSubscription")
    private_key = os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY")
    claims_email = os.environ.get("WEB_PUSH_VAPID_CLAIMS_EMAIL")
    if not private_key or not claims_email:
        update_delivery_status(item, "push", "not_configured")
        return
    if not preferences.get("pushNotificationsEnabled") or not subscription:
        update_delivery_status(item, "push", "disabled")
        return
    try:
        webpush(subscription_info=subscription, data=json.dumps({"title": subject, "body": body, "href": href}), vapid_private_key=private_key, vapid_claims={"sub": claims_email})
        update_delivery_status(item, "push", "sent")
    except WebPushException as exc:
        # A future subscription refresh or worker retry may recover this delivery.
        update_delivery_status(item, "push", "failed", exc)
    except Exception as exc:
        update_delivery_status(item, "push", "failed", exc)


def deliver(event):
    subject, body = notification_copy(event)
    link = f"{os.environ.get('APP_BASE_URL', '').rstrip('/')}/clubs/{event['clubId']}"
    is_reminder = event["notificationType"] in {"vote_reminder", "rsvp_reminder"}
    created_at = now_iso()
    all_channels_delivered = True
    members = eligible_members(event)
    log("notification_delivery_started", eventId=event["eventId"], notificationType=event["notificationType"], clubId=event["clubId"], movieNightId=event["movieNightId"], recipientCount=len(members), emailConfigured=bool(os.environ.get("NOTIFICATION_EMAIL_FROM")), pushConfigured=bool(os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY") and os.environ.get("WEB_PUSH_VAPID_CLAIMS_EMAIL")))
    for member in members:
        user_id = member["userId"]
        notification_id = event["eventId"]
        item = {
            "PK": f"USER#{user_id}", "SK": f"NOTIFICATION#{notification_id}",
            "entityType": "notification", "notificationId": notification_id,
            "userId": user_id, "clubId": event["clubId"], "movieNightId": event["movieNightId"],
            "type": event["notificationType"], "title": subject, "body": body,
            "href": f"/clubs/{event['clubId']}", "createdAt": created_at,
            "emailStatus": "pending", "pushStatus": "pending",
        }
        try:
            put_item(item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                log("notification_record_create_failed", eventId=event["eventId"], userId=user_id, **error_details(exc))
                raise
            item = table().get_item(Key={"PK": item["PK"], "SK": item["SK"]}).get("Item")
            if not item:
                log("notification_record_missing_after_duplicate", eventId=event["eventId"], userId=user_id)
                continue
        preferences = user_preferences(user_id)
        if item.get("emailStatus") != "sent":
            send_email(item, member, subject, body, link, is_reminder, preferences)
        if item.get("pushStatus") != "sent":
            send_push(item, subject, body, item["href"], preferences)
        refreshed = table().get_item(Key={"PK": item["PK"], "SK": item["SK"]}).get("Item") or item
        if "failed" in {refreshed.get("emailStatus"), refreshed.get("pushStatus")}:
            all_channels_delivered = False
    log("notification_delivery_finished", eventId=event["eventId"], retryRequired=not all_channels_delivered)
    return all_channels_delivered


def process_outbox():
    result = table().query(KeyConditionExpression=Key("PK").eq("NOTIFICATION_OUTBOX") & Key("SK").begins_with("EVENT#"))
    pending_count = 0
    for event in result.get("Items", []):
        if event.get("status") != "pending":
            continue
        pending_count += 1
        if deliver(event):
            table().update_item(Key={"PK": event["PK"], "SK": event["SK"]}, UpdateExpression="SET #status = :status, deliveredAt = :at", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": "delivered", ":at": now_iso()})
            log("notification_outbox_delivered", eventId=event["eventId"])
        else:
            log("notification_outbox_retry_scheduled", eventId=event["eventId"])
    log("notification_outbox_processed", scannedCount=len(result.get("Items", [])), pendingCount=pending_count)


def process_due():
    result = table().query(KeyConditionExpression=Key("PK").eq("NOTIFICATION_DUE") & Key("SK").lte(f"DUE#{now_iso()}~"))
    pending_count = 0
    for reminder in result.get("Items", []):
        if reminder.get("status") != "pending":
            continue
        pending_count += 1
        movie_night = table().get_item(Key={"PK": f"CLUB#{reminder['clubId']}", "SK": f"MOVIE_NIGHT#{reminder['movieNightId']}"}).get("Item")
        expected_status = "voting" if reminder["notificationType"] == "vote_reminder" else "confirmed"
        if movie_night and movie_night.get("status") == expected_status:
            if deliver(reminder):
                table().update_item(Key={"PK": reminder["PK"], "SK": reminder["SK"]}, UpdateExpression="SET #status = :status, deliveredAt = :at", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": "delivered", ":at": now_iso()})
                log("notification_reminder_delivered", eventId=reminder["eventId"])
            else:
                log("notification_reminder_retry_scheduled", eventId=reminder["eventId"])
            continue
        table().update_item(Key={"PK": reminder["PK"], "SK": reminder["SK"]}, UpdateExpression="SET #status = :status, deliveredAt = :at", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": "delivered", ":at": now_iso()})
        log("notification_reminder_skipped", eventId=reminder["eventId"], expectedMovieNightStatus=expected_status, actualMovieNightStatus=movie_night.get("status") if movie_night else None)
    log("notification_due_processed", scannedCount=len(result.get("Items", [])), pendingCount=pending_count)


def handler(event, context):
    log("notification_worker_started", requestId=getattr(context, "aws_request_id", None))
    process_outbox()
    process_due()
    log("notification_worker_finished", requestId=getattr(context, "aws_request_id", None))
    return {"ok": True}
