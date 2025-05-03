import json
import boto3
import os
from datetime import datetime
from uuid import uuid4

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('DYNAMODB_TABLE', 'ServiceRequests')
table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    try:
        # Parse the incoming request body
        body = json.loads(event.get('body', '{}'))

        # Generate UUID if not provided
        service_id = body.get('serviceId', str(uuid4()))
        requested_at = body.get('requestedAt', datetime.now(datetime.timezone.utc).isoformat() + 'Z')

        # Construct the item
        item = {
            "PK": f"SERVICE#{service_id}",
            "SK": f"REQUESTED_AT#{requested_at}",
            "serviceId": service_id,
            "customerName": body['customerName'],
            "customerPhone": body['customerPhone'],
            "customerEmail": body['customerEmail'],
            "serviceType": body['serviceType'],
            "description": body['description'],
            "requestedAt": requested_at,
            "status": body.get('status', 'Scheduled'),
            "assignedTechnician": body.get('assignedTechnician', 'unassigned')
        }

        # Insert item into DynamoDB
        table.put_item(Item=item)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Service request inserted successfully', 'serviceId': service_id})
        }

    except Exception as e:
        print(f"Error inserting service request: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to insert service request', 'details': str(e)})
        }
