import boto3
import json
from boto3.dynamodb.conditions import Attr, Or

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Reunion_Attendees')

def handler(event, context):
    try:
        query = None

        # Parse `q` from queryStringParameters
        if 'queryStringParameters' in event and event['queryStringParameters']:
            query = event['queryStringParameters'].get('q')
        
        if not query or query.strip() == '':
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing search query parameter `q`"})
            }

        # Build a filter: match `q` in firstName, lastName, familyGroup, or registrationCode
        filter_expr = (
            Attr("firstName").contains(query) |
            Attr("lastName").contains(query) |
            Attr("familyGroup").contains(query) |
            Attr("registrationCode").contains(query)
        )

        response = table.scan(FilterExpression=filter_expr)

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
