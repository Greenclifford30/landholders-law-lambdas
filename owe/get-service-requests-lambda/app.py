import json
import boto3
import os
from datetime import datetime
from uuid import uuid4

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('DYNAMODB_TABLE', 'ServiceRequests')
table = dynamodb.Table(table_name)

def handler(event, context):
    try:
        # Scan the entire table (be careful if large)
        response = table.scan()
        items = response.get('Items', [])

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'message': 'Service requests retrieved successfully',
                'data': items
            })
        }

    except Exception as e:
        print(f"Error retrieving service requests: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'message': 'Failed to retrieve service requests',
                'error': str(e)
            })
        }