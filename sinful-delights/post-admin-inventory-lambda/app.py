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
        # In a real-world scenario, this would check for admin role
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Adjust stock quantity of a menu item.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated stock quantity
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
        item_id = body.get('itemId')
        adjustment = body.get('adjustment')
        
        # Validate input
        if not item_id or adjustment is None:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing inventory adjustment details'})
            }
        
        # Update item stock in DynamoDB
        response = dynamodb.update_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'ITEM#{item_id}'},
                'SK': {'S': 'STOCK'}
            },
            UpdateExpression='SET StockQty = StockQty + :adj',
            ExpressionAttributeValues={':adj': {'N': str(adjustment)}},
            ReturnValues='UPDATED_NEW'
        )
        
        # Retrieve new stock quantity
        new_stock_qty = int(response.get('Attributes', {}).get('StockQty', {}).get('N', 0))
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'itemId': item_id,
                'newStockQty': new_stock_qty,
                'adjustment': adjustment
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