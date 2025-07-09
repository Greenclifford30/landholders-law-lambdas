import boto3
import json
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Reunion_Attendees')

def handler(event, context):
    try:
        total_attendees = 0
        checked_in = 0
        shirts_picked_up = 0

        response = table.scan()
        items = response.get('Items', [])

        for item in items:
            total_attendees += 1

            if item.get('checkedIn') is True:
                checked_in += 1

            if item.get('shirtsPickedUp') is True:
                shirts_picked_up += 1

        dashboard_data = {
            "totalAttendees": total_attendees,
            "checkedIn": checked_in,
            "shirtsPickedUp": shirts_picked_up,
            "attendees": items
        }

        return {
            "statusCode": 200,
            "body": json.dumps(dashboard_data, default=str)  # in case there are Decimals or Dates
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
