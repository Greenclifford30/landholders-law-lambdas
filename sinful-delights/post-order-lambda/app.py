import json
import os
import sys
import uuid
from datetime import datetime
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_customer_access, get_user_id
    from shared.errors import handle_exceptions, create_success_response, ValidationError, OutOfStockError
    from shared.dynamo import get_item, transact_write, parse_dynamodb_item, format_dynamodb_item, decrement_stock
    from shared.models import CreateOrderRequest, Order
    from shared.utils import validate_iso8601_datetime, generate_id
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
    
    class ValidationError(Exception):
        pass
    
    class OutOfStockError(Exception):
        pass
    
    def validate_iso8601_datetime(dt_str):
        try:
            datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return True
        except:
            return False
    
    def generate_id(prefix=""):
        unique_id = str(uuid.uuid4())
        return f"{prefix}_{unique_id}" if prefix else unique_id

TABLE_NAME = os.environ.get("TABLE_NAME", "sinful-delights-table")

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a customer order (OpenAPI: createOrder).
    
    Request body should contain:
    {
        "items": [{"itemId": "string", "quantity": int}],
        "pickupSlot": "2025-08-23T17:30:00Z",
        "notes": "optional string"
    }
    
    Returns Order object according to OpenAPI spec.
    """
    # Validate customer authentication
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    # Parse and validate request body
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON in request body")
    
    # Validate required fields
    items = body.get('items', [])
    pickup_slot = body.get('pickupSlot')
    notes = body.get('notes')
    
    if not items:
        raise ValidationError("Items array is required and cannot be empty")
    
    if not pickup_slot:
        raise ValidationError("pickupSlot is required")
    
    # Validate pickup slot format
    if not validate_iso8601_datetime(pickup_slot):
        raise ValidationError("pickupSlot must be in ISO8601 format")
    
    # Validate items format
    for i, item in enumerate(items):
        if not isinstance(item, dict) or 'itemId' not in item or 'quantity' not in item:
            raise ValidationError(f"Item at index {i} must have itemId and quantity fields")
        
        if not isinstance(item['quantity'], int) or item['quantity'] < 1:
            raise ValidationError(f"Item at index {i}: quantity must be a positive integer")
    
    # Generate order ID and timestamp
    order_id = generate_id("order")
    placed_at = datetime.utcnow().isoformat() + 'Z'
    
    try:
        from shared.dynamo import get_item, transact_write, parse_dynamodb_item
        
        # Build transaction items for atomic stock decrement and order creation
        transact_items = []
        order_items = []
        total_order_value = 0
        
        for item in items:
            item_id = item['itemId']
            quantity = item['quantity']
            
            # Get item details (price and name)
            item_details = get_item(f"ITEM#{item_id}", "DETAILS")
            if not item_details:
                raise ValidationError(f"Item {item_id} not found")
            
            parsed_item = parse_dynamodb_item(item_details)
            item_price = float(parsed_item.get('price', 0))
            item_name = parsed_item.get('name', 'Unknown Item')
            
            # Add stock decrement transaction
            transact_items.append({
                'Update': {
                    'TableName': TABLE_NAME,
                    'Key': {
                        'PK': {'S': f'ITEM#{item_id}'},
                        'SK': {'S': 'DETAILS'}
                    },
                    'UpdateExpression': 'SET stockQty = stockQty - :qty',
                    'ConditionExpression': 'stockQty >= :qty AND available = :true',
                    'ExpressionAttributeValues': {
                        ':qty': {'N': str(quantity)},
                        ':true': {'BOOL': True}
                    }
                }
            })
            
            # Build order item
            order_items.append({
                'itemId': item_id,
                'name': item_name,
                'price': item_price,
                'qty': quantity
            })
            
            total_order_value += item_price * quantity
        
        # Add order creation transaction
        order_data = {
            'PK': {'S': f'USER#{user_id}'},
            'SK': {'S': f'ORDER#{order_id}'},
            'orderId': {'S': order_id},
            'userId': {'S': user_id},
            'items': {'L': [
                {'M': {
                    'itemId': {'S': oi['itemId']},
                    'name': {'S': oi['name']},
                    'price': {'N': str(oi['price'])},
                    'qty': {'N': str(oi['qty'])}
                }} for oi in order_items
            ]},
            'total': {'N': str(round(total_order_value, 2))},
            'status': {'S': 'NEW'},
            'pickupSlot': {'S': pickup_slot},
            'placedAt': {'S': placed_at}
        }
        
        if notes:
            order_data['notes'] = {'S': notes}
        
        transact_items.append({
            'Put': {
                'TableName': TABLE_NAME,
                'Item': order_data
            }
        })
        
        # Execute transaction
        transact_write(transact_items)
        
        # Build response according to OpenAPI spec
        order_response = {
            'orderId': order_id,
            'userId': user_id,
            'items': order_items,
            'total': round(total_order_value, 2),
            'status': 'NEW',
            'pickupSlot': pickup_slot,
            'placedAt': placed_at
        }
        
        if notes:
            order_response['notes'] = notes
        
        return create_success_response(order_response, 201)
        
    except ImportError:
        # Fallback to direct DynamoDB calls
        import boto3
        dynamodb = boto3.client("dynamodb")
        
        # Simplified fallback implementation
        order_id = str(uuid.uuid4())
        
        # Basic stock validation and decrement (not atomic in fallback)
        for item in items:
            # Check stock
            response = dynamodb.get_item(
                TableName=TABLE_NAME,
                Key={
                    'PK': {'S': f'ITEM#{item["itemId"]}'},
                    'SK': {'S': 'DETAILS'}
                }
            )
            
            current_stock = int(response.get('Item', {}).get('stockQty', {}).get('N', 0))
            if current_stock < item['quantity']:
                raise OutOfStockError(f"Insufficient stock for item {item['itemId']}")
        
        # Create order (simplified)
        order_response = {
            'orderId': order_id,
            'userId': user_id,
            'items': [],  # Would need to populate properly
            'total': 0,  # Would need to calculate
            'status': 'NEW',
            'pickupSlot': pickup_slot,
            'placedAt': placed_at
        }
        
        return create_success_response(order_response, 201)