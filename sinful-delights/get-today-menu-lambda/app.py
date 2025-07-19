import json
import os
import boto3
from datetime import datetime
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
    Fetch today's active menu for customers.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu items
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
        # Query DynamoDB for today's menu items
        today = datetime.now().strftime("%Y-%m-%d")
        response = dynamodb.query(
            TableName=TABLE_NAME,
            IndexName="DateIndex",
            KeyConditionExpression="MenuDate = :date",
            ExpressionAttributeValues={":date": {"S": today}}
        )
        
        menu_items = []
        for item in response.get('Items', []):
            menu_items.append({
                'itemId': item.get('id', {}).get('S', ''),
                'name': item.get('name', {}).get('S', ''),
                'description': item.get('description', {}).get('S', ''),
                'price': float(item.get('price', {}).get('N', 0)),
                'stockQty': int(item.get('stockQty', {}).get('N', 0)),
                'isSpecial': item.get('isSpecial', {}).get('BOOL', False),
                'imageUrl': item.get('imageUrl', {}).get('S', '')
            })
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(menu_items)
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