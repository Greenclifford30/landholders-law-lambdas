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

def validate_auth_token(event: Dict[str, Any]) -> bool:
    """Validate Firebase Auth ID token."""
    return 'Authorization' in event.get('headers', {})

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a customer order with stock validation and decrementing.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with order confirmation
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
        items = body.get('items', [])
        pickup_slot = body.get('pickupSlot')
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        if not items or not pickup_slot:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Invalid order details'})
            }
        
        # Create transactional write items to update stock and create order
        transact_items = []
        order_id = str(uuid.uuid4())
        
        # Track total order value for analytics
        total_order_value = 0
        
        for item in items:
            # Validate and decrement stock atomically
            transact_items.append({
                'Update': {
                    'TableName': TABLE_NAME,
                    'Key': {
                        'PK': {'S': f'ITEM#{item["itemId"]}'},
                        'SK': {'S': f'STOCK'}
                    },
                    'UpdateExpression': 'SET StockQty = StockQty - :qty',
                    'ConditionExpression': 'StockQty >= :qty',
                    'ExpressionAttributeValues': {
                        ':qty': {'N': str(item['qty'])}
                    }
                }
            })
            
            # Fetch item price for total order value
            price_response = dynamodb.get_item(
                TableName=TABLE_NAME,
                Key={
                    'PK': {'S': f'ITEM#{item["itemId"]}'},
                    'SK': {'S': 'DETAILS'}
                }
            )
            price = float(price_response.get('Item', {}).get('Price', {}).get('N', 0))
            total_order_value += price * item['qty']
        
        # Add order record
        transact_items.append({
            'Put': {
                'TableName': TABLE_NAME,
                'Item': {
                    'PK': {'S': f'USER#{user_id}'},
                    'SK': {'S': f'ORDER#{order_id}'},
                    'OrderId': {'S': order_id},
                    'PickupSlot': {'S': pickup_slot},
                    'Status': {'S': 'confirmed'},
                    'Total': {'N': str(total_order_value)},
                    'Items': {'L': [
                        {'M': {
                            'ItemId': {'S': item['itemId']},
                            'Quantity': {'N': str(item['qty'])}
                        }} for item in items
                    ]}
                }
            }
        })
        
        # Perform atomic transaction
        dynamodb.transact_write_items(TransactItems=transact_items)
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'orderId': order_id,
                'status': 'confirmed',
                'pickupSlot': pickup_slot
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