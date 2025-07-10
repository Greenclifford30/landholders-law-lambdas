import boto3
import json
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Reunion_Attendees')

def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        attendee_id = body.get("id")
        checkin = body.get("checkin", False)
        pickup = body.get("shirtPickup", False)

        if not attendee_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing attendee id"})
            }

        update_expr = []
        expr_attrs = {}

        if checkin:
            update_expr.append("checkedIn = :checkedIn, checkedInAt = :checkedInAt")
            expr_attrs[":checkedIn"] = True
            expr_attrs[":checkedInAt"] = datetime.now().isoformat()

        if pickup:
            update_expr.append("shirtsPickedUp = :shirtsPickedUp, shirtsPickedUpAt = :shirtsPickedUpAt")
            expr_attrs[":shirtsPickedUp"] = True
            expr_attrs[":shirtsPickedUpAt"] = datetime.now().isoformat()

        if not update_expr:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No action specified"})
            }

        update_expression = "SET " + ", ".join(update_expr)

        response = table.update_item(
            Key={"id": attendee_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expr_attrs,
            ReturnValues="ALL_NEW"
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Attendee updated",
                "attendee": response.get("Attributes", {})
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
