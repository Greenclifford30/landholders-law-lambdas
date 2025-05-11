import json
import boto3
import os
from boto3.dynamodb.conditions import Key
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE', 'ServiceRequests'))

def handler(event, context):
    try:
        # Extract path parameters and body
        service_id = event['pathParameters']['serviceId']
        body = json.loads(event['body'])

        # Fetch the most recent SK for the given service ID
        pk = f"SERVICE#{service_id}"
        response = table.query(
            KeyConditionExpression=Key('PK').eq(pk),
            ScanIndexForward=False,
            Limit=1
        )

        if not response['Items']:
            return {
                "statusCode": 404,
                "body": json.dumps({"success": False, "message": "Service request not found"})
            }

        item = response['Items'][0]
        sk = item['SK']

        # Update expression and attribute values
        update_fields = []
        expression_values = {}

        for key, value in body.items():
            update_fields.append(f"{key} = :{key}")
            expression_values[f":{key}"] = value

        if not update_fields:
            return {
                "statusCode": 400,
                "body": json.dumps({"success": False, "message": "No fields to update"})
            }

        update_expr = "SET " + ", ".join(update_fields)

        table.update_item(
            Key={'PK': pk, 'SK': sk},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expression_values
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"success": True, "message": "Service request updated"})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"success": False, "message": str(e)})
        }
