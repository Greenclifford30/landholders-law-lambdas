import json
import os
import boto3
from datetime import datetime, timezone

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["ADMIN_SELECTION_QUEUE_URL"]

def handler(event, context):
    try:
        # Parse input from API Gateway event body
        body = json.loads(event.get("body", "{}"))
        movie_id = body.get("movieId")
        movie_title = body.get("movieTitle")
        show_date = body.get("proposedStartDate")

        if not movie_id or not movie_title or not show_date:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Missing one or more required fields: movieId, movieTitle, showDate"
                })
            }

        # Append submission timestamp
        body["submittedAt"] = datetime.now(timezone.utc).isoformat()

        # Send to SQS
        response = sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(body)
        )

        return {
            "statusCode": 202,
            "body": json.dumps({
                "success": True,
                "messageId": response["MessageId"]
            })
        }

    except Exception as e:
        print("Error sending to SQS:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
