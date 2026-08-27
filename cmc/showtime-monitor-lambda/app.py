import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key


dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def handler(event, context):
    app_table = dynamodb.Table(os.environ["APP_TABLE_NAME"])
    queue_url = os.environ["SHOWTIME_REFRESH_QUEUE_URL"]
    now = now_iso()
    result = app_table.query(
        KeyConditionExpression=Key("PK").eq("SHOWTIME_MONITOR") & Key("SK").lte(f"CHECK#{now}~")
    )
    queued = 0
    for monitor in result.get("Items", []):
        if monitor.get("status") != "active":
            continue
        night = app_table.get_item(Key={"PK": f"CLUB#{monitor['clubId']}", "SK": f"MOVIE_NIGHT#{monitor['movieNightId']}"}).get("Item")
        if not night or night.get("status") != "planning" or (night.get("showtimeMonitoring") or {}).get("status") != "active":
            app_table.delete_item(Key={"PK": monitor["PK"], "SK": monitor["SK"]})
            continue
        planning = night
        message = {
            "provider": "gracenote", "requestedBy": "upcoming-showtime-monitor", "monitoring": True,
            "monitorPK": monitor["PK"], "monitorSK": monitor["SK"], "movieNightId": night["movieNightId"],
            "clubId": night["clubId"], "importJobId": f"monitor-{now}-{night['movieNightId']}",
            "movieTitle": (night.get("movie") or {}).get("title", ""), "zip": planning.get("zipCode"),
            "radius": planning.get("radiusMiles"), "units": "mi", "startDate": planning.get("dateWindowStart"),
            "numDays": (datetime.strptime(planning["dateWindowEnd"], "%Y-%m-%d").date() - datetime.strptime(planning["dateWindowStart"], "%Y-%m-%d").date()).days + 1,
            "timezone": planning.get("timezone") or "America/Chicago",
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
        app_table.update_item(Key={"PK": monitor["PK"], "SK": monitor["SK"]}, UpdateExpression="SET lastCheckedAt = :now, updatedAt = :now", ExpressionAttributeValues={":now": now})
        queued += 1
    return {"queued": queued}
