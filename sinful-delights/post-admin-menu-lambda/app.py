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

def validate_admin_token(event: Dict[str, Any]) -> bool:
    """Validate admin Firebase Auth ID token."""
    try:
        # In a real-world scenario, this would check for admin role
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update menu for a specific date.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu update status
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
        body = json.loads(event.get('body', '{}'))
        menu_date = body.get('date')
        menu_items = body.get('items', [])
        
        # Validate input
        if not menu_date or not menu_items:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing menu details'})
            }
        
        # Generate menu ID
        menu_id = str(uuid.uuid4())
        
        # Prepare batch write items
        transact_items = []
        
        for item in menu_items:
            # Validate item details
            required_fields = ['name', 'price']
            if not all(item.get(field) for field in required_fields):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': f'Missing required fields for item: {item}'})
                }
            
            # Generate unique item ID
            item_id = str(uuid.uuid4())
            
            # Prepare menu item for DynamoDB
            menu_item_entry = {
                'menuId': {'S': f'MENU#{menu_id}'},
                'itemId': {'S': f'ITEM#{item_id}'},
                'id': {'S': item_id},
                'name': {'S': item['name']},
                'description': {'S': item.get('description', '')},
                'price': {'N': str(item['price'])},
                'stockQty': {'N': str(item.get('stockQty', 0))},
                'isSpecial': {'BOOL': item.get('isSpecial', False)},
                'imageUrl': {'S': item.get('imageUrl', '')},
                'MenuDate': {'S': menu_date}
            }
            
            transact_items.append({
                'Put': {
                    'TableName': TABLE_NAME,
                    'Item': menu_item_entry,
                    'ConditionExpression': 'attribute_not_exists(PK) AND attribute_not_exists(SK)'
                }
            })
        
        # Perform batch write
        dynamodb.transact_write_items(TransactItems=transact_items)
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'menuId': menu_id,
                'status': 'updated',
                'date': menu_date
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