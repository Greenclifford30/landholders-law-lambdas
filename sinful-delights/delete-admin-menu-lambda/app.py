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
    Delete a specific menu and all its items.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with deletion status
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
        
        # Get all menu items
        items_response = dynamodb.query(
            TableName=TABLE_NAME,
            IndexName='MenuIndex',
            KeyConditionExpression='MenuId = :menu_id',
            ExpressionAttributeValues={':menu_id': {'S': f'MENU#{menu_id}'}}
        )
        
        # Prepare batch delete request
        delete_requests = []
        
        # Add menu items to delete request
        for item in items_response.get('Items', []):
            delete_requests.append({
                'Delete': {
                    'TableName': TABLE_NAME,
                    'Key': {
                        'PK': {'S': f'MENU#{menu_id}'},
                        'SK': {'S': f'ITEM#{item["ItemId"]["S"]}'}
                    }
                }
            })
        
        # Add menu details to delete request
        delete_requests.append({
            'Delete': {
                'TableName': TABLE_NAME,
                'Key': {
                    'PK': {'S': f'MENU#{menu_id}'},
                    'SK': {'S': 'DETAILS'}
                }
            }
        })
        
        # Execute batch delete
        for i in range(0, len(delete_requests), 25):
            batch = delete_requests[i:i+25]
            dynamodb.transact_write_items(TransactItems=batch)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'status': 'DELETED'})
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