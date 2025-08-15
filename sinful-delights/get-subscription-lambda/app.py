"""
GET /subscription - Get user subscription (OpenAPI: getSubscription)
"""
import json
import os
import sys
from typing import Dict, Any
from datetime import datetime, timedelta

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_customer_access, get_user_id
    from shared.errors import handle_exceptions, create_success_response, NotFoundError
    from shared.dynamo import get_item, parse_dynamodb_item
    from shared.models import Subscription, SubscriptionPlan
except ImportError:
    # Fallback for local testing
    import boto3
    dynamodb = boto3.client("dynamodb")
    
    def validate_customer_access(event):
        headers = event.get('headers', {})
        if not ('X-API-Key' in headers and 'Authorization' in headers):
            raise Exception("Unauthorized")
        return event['requestContext']['authorizer']['claims']
    
    def get_user_id(event):
        return event['requestContext']['authorizer']['claims']['sub']
    
    def handle_exceptions(func):
        return func
    
    def create_success_response(data, status_code=200):
        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(data, default=str)
        }
    
    class NotFoundError(Exception):
        pass

TABLE_NAME = os.environ.get("TABLE_NAME", "sinful-delights-table")


@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get the authenticated user's subscription (OpenAPI: getSubscription).
    
    Returns Subscription object according to OpenAPI spec.
    """
    # Validate customer authentication
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    try:
        from shared.dynamo import get_item, parse_dynamodb_item
        
        # Get user's subscription
        subscription_item = get_item(f"USER#{user_id}", "SUBSCRIPTION")
        
        if not subscription_item:
            raise NotFoundError("Subscription not found")
        
        parsed = parse_dynamodb_item(subscription_item)
        
        # Build response according to OpenAPI spec
        subscription_response = {
            'subscriptionId': parsed.get('subscriptionId', ''),
            'userId': user_id,
            'plan': {
                'planId': parsed.get('planId', ''),
                'mealsPerWeek': int(parsed.get('mealsPerWeek', 0)),
                'portion': parsed.get('portion', ''),
                'tags': parsed.get('tags', [])
            },
            'nextDelivery': parsed.get('nextDelivery', ''),
            'status': parsed.get('status', 'ACTIVE'),
            'skipDates': parsed.get('skipDates', []),
            'createdAt': parsed.get('createdAt', ''),
            'updatedAt': parsed.get('updatedAt')
        }
        
        return create_success_response(subscription_response)
        
    except ImportError:
        # Fallback to direct DynamoDB calls
        import boto3
        dynamodb = boto3.client("dynamodb")
        
        response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'USER#{user_id}'},
                'SK': {'S': 'SUBSCRIPTION'}
            }
        )
        
        if 'Item' not in response:
            raise NotFoundError("Subscription not found")
        
        item = response['Item']
        subscription_response = {
            'subscriptionId': item.get('subscriptionId', {}).get('S', ''),
            'userId': user_id,
            'plan': {
                'planId': item.get('planId', {}).get('S', ''),
                'mealsPerWeek': int(item.get('mealsPerWeek', {}).get('N', 0)),
                'portion': item.get('portion', {}).get('S', ''),
                'tags': [tag.get('S', '') for tag in item.get('tags', {}).get('L', [])]
            },
            'nextDelivery': item.get('nextDelivery', {}).get('S', ''),
            'status': item.get('status', {}).get('S', 'ACTIVE'),
            'skipDates': [skip.get('S', '') for skip in item.get('skipDates', {}).get('L', [])],
            'createdAt': item.get('createdAt', {}).get('S', ''),
            'updatedAt': item.get('updatedAt', {}).get('S')
        }
        
        return create_success_response(subscription_response)