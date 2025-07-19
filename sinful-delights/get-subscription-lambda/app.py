import json
import os
import boto3
from typing import Dict, Any
from datetime import datetime, timedelta

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
    Retrieve customer's subscription details.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with subscription details
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
        # Retrieve user ID from token
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Query DynamoDB for user's subscription
        response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'USER#{user_id}'},
                'SK': {'S': 'SUBSCRIPTION'}
            }
        )
        
        item = response.get('Item', {})
        
        # If no subscription exists, return appropriate response
        if not item:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'No active subscription found'})
            }
        
        subscription = {
            'subscriptionId': item.get('SubscriptionId', {}).get('S', ''),
            'plan': item.get('Plan', {}).get('S', ''),
            'status': item.get('Status', {}).get('S', 'Inactive'),
            'portionSize': item.get('PortionSize', {}).get('S', ''),
            'mealsPerWeek': int(item.get('MealsPerWeek', {}).get('N', 0)),
            'nextDelivery': item.get('NextDelivery', {}).get('S', 
                (datetime.now() + timedelta(days=7)).isoformat())
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(subscription)
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