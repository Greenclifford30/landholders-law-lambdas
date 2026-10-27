import json
import os

import boto3
from boto3.dynamodb.conditions import Key

from cmc_shared import table


sqs = boto3.client("sqs")


def handler(event, context):
    queue_url = os.environ["CALENDAR_SYNC_QUEUE_URL"]
    kwargs = {
        "IndexName": "GSI1",
        "KeyConditionExpression": Key("GSI1PK").eq("CALENDAR_PROVIDER#google#connected"),
    }
    queued = 0
    while True:
        page = table().query(**kwargs)
        for item in page.get("Items", []):
            if not item.get("userId"):
                continue
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({"userId": item["userId"], "reason": "hourly_refresh"}),
            )
            queued += 1
        if not page.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return {"queued": queued}
