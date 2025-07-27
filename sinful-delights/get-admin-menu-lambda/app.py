import json
import os
import boto3
from typing import Dict, Any

# DynamoDB configuration
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def validate_api_key(event: Dict[str, Any]) -> bool:
    """Validate the API key from the event headers."""
    return 'X-API-Key' in event.get('headers', {})

def validate_admin_token(event: Dict[str, Any]) -> bool:
    """Validate admin Firebase Auth ID token."""
    try:
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve a specific menu with all its items.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu details
    """
    # Validate API key and admin token
    if not validate_api_key(event) or not validate_admin_token(event):
        return {
            'statusCode': 401,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Unauthorized'})
        }
    
    try:
        # Get menu ID from path parameters
        menu_id = event.get('pathParameters', {}).get('menuId')
        if not menu_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing menu ID'})
            }
        
        # Get menu details
        menu_response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'MENU#{menu_id}'},
                'SK': {'S': 'DETAILS'}
            }
        )
        
        if 'Item' not in menu_response:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Menu not found'})
            }
        
        menu = menu_response['Item']
        
        # Get menu items
        items_response = dynamodb.query(
            TableName=TABLE_NAME,
            IndexName='MenuIndex',
            KeyConditionExpression='MenuId = :menu_id',
            ExpressionAttributeValues={':menu_id': {'S': f'MENU#{menu_id}'}}
        )
        
        items = []
        for item in items_response.get('Items', []):
            items.append({
                'itemId': item.get('ItemId', {}).get('S', ''),
                'name': item.get('Name', {}).get('S', ''),
                'description': item.get('Description', {}).get('S', ''),
                'price': float(item.get('Price', {}).get('N', 0)),
                'stockQty': int(item.get('StockQty', {}).get('N', 0)),
                'imageUrl': item.get('ImageUrl', {}).get('S', ''),
                'isSpecial': item.get('IsSpecial', {}).get('BOOL', False)
            })
        
        menu_data = {
            'menuId': menu_id,
            'date': menu.get('MenuDate', {}).get('S', ''),
            'title': menu.get('Title', {}).get('S', ''),
            'items': items
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(menu_data)
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