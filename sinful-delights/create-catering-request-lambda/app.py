import json
import os
import boto3
import uuid
from typing import Dict, Any

# DynamoDB configuration
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def validate_api_key(event: Dict[str, Any]) -> bool:
    """Validate the API key from the event headers."""
    return 'X-API-Key' in event.get('headers', {})

def validate_auth_token(event: Dict[str, Any]) -> bool:
    """Validate Firebase Auth ID token."""
    return 'Authorization' in event.get('headers', {})

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Save a catering request.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with catering request details
    """
    # Validate API key and auth token
    if not validate_api_key(event) or not validate_auth_token(event):
        return {
            'statusCode': 401,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Unauthorized'})
        }
    
    try:
        body = json.loads(event.get('body', '{}'))
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Validate required fields
        required_fields = ['eventDate', 'guestCount', 'cuisinePreferences', 'budget']
        if not all(body.get(field) for field in required_fields):
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing catering request details'})
            }
        
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Prepare catering request item
        catering_request_item = {
            'PK': {'S': f'USER#{user_id}'},
            'SK': {'S': f'CATERING#{request_id}'},
            'RequestId': {'S': request_id},
            'EventDate': {'S': body['eventDate']},
            'GuestCount': {'N': str(body['guestCount'])},
            'CuisinePreferences': {'S': body['cuisinePreferences']},
            'Budget': {'N': str(body['budget'])},
            'Status': {'S': 'New'}
        }
        
        # Optional additional details
        if body.get('additionalNotes'):
            catering_request_item['AdditionalNotes'] = {'S': body['additionalNotes']}
        
        # Save to DynamoDB
        dynamodb.put_item(
            TableName=TABLE_NAME,
            Item=catering_request_item
        )
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'requestId': request_id,
                'status': 'New'
            })
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }