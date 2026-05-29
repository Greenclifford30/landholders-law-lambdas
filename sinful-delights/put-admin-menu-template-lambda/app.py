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
    Update a specific menu template.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with update status
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
        # Get template ID from path parameters
        template_id = event.get('pathParameters', {}).get('templateId')
        if not template_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing template ID'})
            }
        
        body = json.loads(event.get('body', '{}'))
        new_name = body.get('name')
        new_items = body.get('items', [])
        
        # Update template details if name is provided
        if new_name:
            dynamodb.update_item(
                TableName=TABLE_NAME,
                Key={
                    'PK': {'S': f'TEMPLATE#{template_id}'},
                    'SK': {'S': 'DETAILS'}
                },
                UpdateExpression='SET #name = :name',
                ExpressionAttributeNames={'#name': 'Name'},
                ExpressionAttributeValues={':name': {'S': new_name}}
            )
        
        # Update items if provided
        if new_items:
            # Delete existing items
            existing_items = dynamodb.query(
                TableName=TABLE_NAME,
                KeyConditionExpression='PK = :pk AND begins_with(SK, :item)',
                ExpressionAttributeValues={
                    ':pk': {'S': f'TEMPLATE#{template_id}'},
                    ':item': {'S': 'ITEM#'}
                }
            )
            
            delete_requests = [
                {
                    'Delete': {
                        'TableName': TABLE_NAME,
                        'Key': {
                            'PK': {'S': f'TEMPLATE#{template_id}'},
                            'SK': item['SK']
                        }
                    }
                }
                for item in existing_items.get('Items', [])
            ]
            
            # Add new items
            put_requests = []
            for item in new_items:
                item_id = str(uuid.uuid4())
                put_requests.append({
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
            
            # Execute batch operations in chunks of 25
            all_requests = delete_requests + put_requests
            for i in range(0, len(all_requests), 25):
                batch = all_requests[i:i+25]
                dynamodb.transact_write_items(TransactItems=batch)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'status': 'UPDATED'})
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