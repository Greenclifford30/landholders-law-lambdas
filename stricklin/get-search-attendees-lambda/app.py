import boto3
import json
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Reunion_Attendees')

def handler(event, context):
    try:
        # Read search parameters from queryStringParameters (GET) or body (POST)
        if 'queryStringParameters' in event and event['queryStringParameters']:
            params = event['queryStringParameters']
        else:
            params = json.loads(event.get('body', '{}'))

        # Build filter expression
        filter_expr = None
        for key, value in params.items():
            if value.strip() == '':
                continue
            condition = Attr(key).contains(value)
            filter_expr = condition if filter_expr is None else filter_expr & condition

        if filter_expr:
            response = table.scan(FilterExpression=filter_expr)
        else:
            response = table.scan()  # no filters provided, return all

        attendees = response.get('Items', [])

        return {
            "statusCode": 200,
            "body": json.dumps(attendees)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
