import json
import os
import boto3
from datetime import datetime, timedelta, timezone

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["ADMIN_SELECTION_QUEUE_URL"]

def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        movie_id = body.get("movieId")
        movie_title = body.get("movieTitle")
        show_date = body.get("showDate")

        if not movie_id or not movie_title or not show_date:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Missing one or more required fields: movieId, movieTitle, showDate"
                })
            }

        base_date = datetime.strptime(show_date, "%Y-%m-%d").date()
        submitted_at = datetime.now(timezone.utc).isoformat()

        for day_offset in range(14):
            date_obj = base_date + timedelta(days=day_offset)
            message_body = {
                "movieId": movie_id,
                "movieTitle": movie_title,
                "showDate": date_obj.strftime("%Y-%m-%d"),
                "submittedAt": submitted_at
            }

            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(message_body)
            )

        return {
            "statusCode": 202,
            "body": json.dumps({
                "success": True,
                "enqueued": 14
            })
        }

    except Exception as e:
        print("Error sending to SQS:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
