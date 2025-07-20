import json
import os
import boto3
import uuid
from datetime import datetime, timedelta
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
    Create or update customer subscription.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated subscription details
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
        
        # Validate input
        required_fields = ['plan', 'portionSize', 'mealsPerWeek']
        if not all(body.get(field) for field in required_fields):
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing required subscription details'})
            }
        
        # Generate subscription details
        subscription_id = str(uuid.uuid4())
        next_delivery = (datetime.now() + timedelta(days=7)).isoformat()
        
        # Prepare subscription item
        subscription_item = {
            'PK': {'S': f'USER#{user_id}'},
            'SK': {'S': 'SUBSCRIPTION'},
            'SubscriptionId': {'S': subscription_id},
            'Plan': {'S': body['plan']},
            'PortionSize': {'S': body['portionSize']},
            'MealsPerWeek': {'N': str(body['mealsPerWeek'])},
            'Status': {'S': 'Active'},
            'NextDelivery': {'S': next_delivery}
        }
        
        # Optional: Add start date, billing info
        if body.get('startDate'):
            subscription_item['StartDate'] = {'S': body['startDate']}
        
        # Perform DynamoDB write
        dynamodb.put_item(
            TableName=TABLE_NAME,
            Item=subscription_item
        )
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'subscriptionId': subscription_id,
                'plan': body['plan'],
                'portionSize': body['portionSize'],
                'mealsPerWeek': body['mealsPerWeek'],
                'status': 'Active',
                'nextDelivery': next_delivery
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