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
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new menu template.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with template creation status
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
        template_name = body.get('name')
        template_items = body.get('items', [])
        
        # Validate input
        if not template_name or not template_items:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing template details'})
            }
        
        # Generate template ID
        template_id = str(uuid.uuid4())
        
        # Prepare template items for batch write
        items = []
        for item in template_items:
            # Validate required fields
            if not all(item.get(field) for field in ['name', 'price']):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Missing required item fields'})
                }
            
            item_id = str(uuid.uuid4())
            items.append({
                'Put': {
                    'TableName': TABLE_NAME,
                    'Item': {
                        'PK': {'S': f'TEMPLATE#{template_id}'},
                        'SK': {'S': f'ITEM#{item_id}'},
                        'ItemId': {'S': item_id},
                        'Name': {'S': item['name']},
                        'Description': {'S': item.get('description', '')},
                        'Price': {'N': str(item['price'])},
                        'StockQty': {'N': str(item.get('stockQty', 0))},
                        'IsSpecial': {'BOOL': item.get('isSpecial', False)}
                    }
                }
            })
        
        # Add template details
        items.append({
            'Put': {
                'TableName': TABLE_NAME,
                'Item': {
                    'PK': {'S': f'TEMPLATE#{template_id}'},
                    'SK': {'S': 'DETAILS'},
                    'TemplateId': {'S': template_id},
                    'Name': {'S': template_name},
                    'CreatedAt': {'S': context.get_remaining_time_in_millis().isoformat()}
                }
            }
        })
        
        # Execute batch write in chunks of 25 (DynamoDB limit)
        for i in range(0, len(items), 25):
            batch = items[i:i+25]
            dynamodb.transact_write_items(TransactItems=batch)
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'templateId': template_id,
                'status': 'CREATED'
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