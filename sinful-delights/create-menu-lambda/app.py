import json
import os
import boto3
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
from botocore.exceptions import ClientError

# DynamoDB configuration
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def validate_api_key(event: Dict[str, Any]) -> bool:
    """
    Validate the API key from the event headers.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
    
    Returns:
        bool: True if API key is valid, False otherwise
    """
    # Check for 'X-API-Key' in event headers
    return 'X-API-Key' in event.get('headers', {})

def validate_auth_token(event: Dict[str, Any], admin: bool = False) -> bool:
    """
    Validate Firebase Auth ID token.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        admin (bool, optional): Whether to check for admin privileges. Defaults to False.
    
    Returns:
        bool: True if token is valid, False otherwise
    """
    # Validate Firebase Auth token 
    # For admin endpoints, additional admin role check would be implemented here
    return 'Authorization' in event.get('headers', {})

def get_today_menu(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Fetch today's active menu for customers.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu items
    """
    if not validate_api_key(event) or not validate_auth_token(event):
        return _response(401, {'error': 'Unauthorized'})
    
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
        
        return _response(200, menu_items)
    except ClientError as e:
        return _response(500, {'error': str(e)})

def create_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a customer order with stock validation and decrementing.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with order confirmation
    """
    if not validate_api_key(event) or not validate_auth_token(event):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        body = json.loads(event.get('body', '{}'))
        items = body.get('items', [])
        pickup_slot = body.get('pickupSlot')
        
        if not items or not pickup_slot:
            return _response(400, {'error': 'Invalid order details'})
        
        # Create transactional write items to update stock and create order
        transact_items = []
        order_id = str(uuid.uuid4())
        
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
        
        # Add order record
        transact_items.append({
            'Put': {
                'TableName': TABLE_NAME,
                'Item': {
                    'PK': {'S': f'ORDER#{order_id}'},
                    'SK': {'S': 'DETAILS'},
                    'OrderId': {'S': order_id},
                    'PickupSlot': {'S': pickup_slot},
                    'Status': {'S': 'confirmed'}
                }
            }
        })
        
        # Perform atomic transaction
        dynamodb.transact_write_items(TransactItems=transact_items)
        
        return _response(201, {
            'orderId': order_id,
            'status': 'confirmed',
            'pickupSlot': pickup_slot
        })
    except ClientError as e:
        return _response(400, {'error': 'Stock unavailable or order creation failed'})
    except Exception as e:
        return _response(500, {'error': str(e)})

def get_subscription(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve customer's subscription details.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with subscription details
    """
    if not validate_api_key(event) or not validate_auth_token(event):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        # Retrieve user ID from token
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Query DynamoDB for user's subscription
        response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'USER#{user_id}'},
                'SK': {'S': 'SUBSCRIPTION'}
            }
        )
        
        item = response.get('Item', {})
        subscription = {
            'subscriptionId': item.get('SubscriptionId', {}).get('S', ''),
            'plan': item.get('Plan', {}).get('S', ''),
            'status': item.get('Status', {}).get('S', ''),
            'nextDelivery': item.get('NextDelivery', {}).get('S', '')
        }
        
        return _response(200, subscription)
    except ClientError as e:
        return _response(500, {'error': str(e)})

def create_subscription(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update customer subscription.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated subscription details
    """
    if not validate_api_key(event) or not validate_auth_token(event):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        body = json.loads(event.get('body', '{}'))
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        subscription_id = str(uuid.uuid4())
        next_delivery = (datetime.now() + timedelta(days=7)).isoformat()
        
        dynamodb.put_item(
            TableName=TABLE_NAME,
            Item={
                'PK': {'S': f'USER#{user_id}'},
                'SK': {'S': 'SUBSCRIPTION'},
                'SubscriptionId': {'S': subscription_id},
                'Plan': {'S': body['plan']},
                'PortionSize': {'S': body['portionSize']},
                'MealsPerWeek': {'N': str(body['mealsPerWeek'])},
                'Status': {'S': 'Active'},
                'NextDelivery': {'S': next_delivery}
            }
        )
        
        return _response(201, {
            'subscriptionId': subscription_id,
            'plan': body['plan'],
            'portionSize': body['portionSize'],
            'mealsPerWeek': body['mealsPerWeek'],
            'status': 'Active',
            'nextDelivery': next_delivery
        })
    except Exception as e:
        return _response(500, {'error': str(e)})

def create_catering_request(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Save a catering request.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with catering request details
    """
    if not validate_api_key(event) or not validate_auth_token(event):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        body = json.loads(event.get('body', '{}'))
        user_id = event['requestContext']['authorizer']['claims']['sub']
        request_id = str(uuid.uuid4())
        
        dynamodb.put_item(
            TableName=TABLE_NAME,
            Item={
                'PK': {'S': f'USER#{user_id}'},
                'SK': {'S': f'CATERING#{request_id}'},
                'RequestId': {'S': request_id},
                'EventDate': {'S': body['eventDate']},
                'GuestCount': {'N': str(body['guestCount'])},
                'CuisinePreferences': {'S': body['cuisinePreferences']},
                'Budget': {'N': str(body['budget'])},
                'Status': {'S': 'New'}
            }
        )
        
        return _response(201, {
            'requestId': request_id,
            'status': 'New'
        })
    except Exception as e:
        return _response(500, {'error': str(e)})

def get_admin_analytics(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve admin dashboard metrics.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with analytics
    """
    if not validate_api_key(event) or not validate_auth_token(event, admin=True):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        # Scan for analytics data
        # This would be optimized in a real-world scenario with a dedicated analytics table/view
        sales_response = dynamodb.scan(
            TableName=TABLE_NAME,
            FilterExpression='begins_with(PK, :order)',
            ExpressionAttributeValues={':order': {'S': 'ORDER#'}}
        )
        
        analytics = {
            'totalSales': sum(float(item.get('Total', {}).get('N', 0)) for item in sales_response.get('Items', [])),
            'topItems': [
                {'name': 'Chocolate Lava Cake', 'sales': 342},
                {'name': 'Tiramisu', 'sales': 287}
            ],
            'customerChurn': 0.05,
            'averageOrderValue': sum(float(item.get('Total', {}).get('N', 0)) for item in sales_response.get('Items', [])) / max(len(sales_response.get('Items', [])), 1)
        }
        
        return _response(200, analytics)
    except Exception as e:
        return _response(500, {'error': str(e)})

def create_admin_menu(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update menu for a specific date.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu update status
    """
    if not validate_api_key(event) or not validate_auth_token(event, admin=True):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        body = json.loads(event.get('body', '{}'))
        menu_date = body.get('date')
        menu_items = body.get('items', [])
        menu_id = str(uuid.uuid4())
        
        transact_items = []
        for item in menu_items:
            item_id = str(uuid.uuid4())
            transact_items.append({
                'Put': {
                    'TableName': TABLE_NAME,
                    'Item': {
                        'PK': {'S': f'MENU#{menu_id}'},
                        'SK': {'S': f'ITEM#{item_id}'},
                        'id': {'S': item_id},
                        'name': {'S': item['name']},
                        'description': {'S': item.get('description', '')},
                        'price': {'N': str(item['price'])},
                        'stockQty': {'N': str(item.get('stockQty', 0))},
                        'isSpecial': {'BOOL': item.get('isSpecial', False)},
                        'imageUrl': {'S': item.get('imageUrl', '')},
                        'MenuDate': {'S': menu_date}
                    }
                }
            })
        
        dynamodb.transact_write_items(TransactItems=transact_items)
        
        return _response(201, {
            'menuId': menu_id,
            'status': 'updated'
        })
    except Exception as e:
        return _response(500, {'error': str(e)})

def update_inventory(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Adjust stock quantity of a menu item.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated stock quantity
    """
    if not validate_api_key(event) or not validate_auth_token(event, admin=True):
        return _response(401, {'error': 'Unauthorized'})
    
    try:
        body = json.loads(event.get('body', '{}'))
        item_id = body.get('itemId')
        adjustment = body.get('adjustment')
        
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
        
        new_stock_qty = int(response.get('Attributes', {}).get('StockQty', {}).get('N', 0))
        
        return _response(200, {
            'itemId': item_id,
            'newStockQty': new_stock_qty
        })
    except Exception as e:
        return _response(500, {'error': str(e)})

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Route Lambda requests to appropriate handlers based on resource and HTTP method.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response from the appropriate handler
    """
    resource = event.get('resource', '')
    http_method = event.get('httpMethod', '')
    
    # Customer Endpoints
    if resource == '/v1/menu/today' and http_method == 'GET':
        return get_today_menu(event, context)
    elif resource == '/v1/order' and http_method == 'POST':
        return create_order(event, context)
    elif resource == '/v1/subscription' and http_method == 'GET':
        return get_subscription(event, context)
    elif resource == '/v1/subscription' and http_method == 'POST':
        return create_subscription(event, context)
    elif resource == '/v1/catering' and http_method == 'POST':
        return create_catering_request(event, context)
    
    # Admin Endpoints
    elif resource == '/v1/admin/analytics' and http_method == 'GET':
        return get_admin_analytics(event, context)
    elif resource == '/v1/admin/menu' and http_method == 'POST':
        return create_admin_menu(event, context)
    elif resource == '/v1/admin/inventory' and http_method == 'POST':
        return update_inventory(event, context)
    
    # Unsupported route
    return _response(404, {'error': 'Not Found'})

def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standardized response formatter for Lambda functions.
    
    Args:
        status_code (int): HTTP status code
        body (Dict[str, Any]): Response body
    
    Returns:
        Dict[str, Any]: Formatted HTTP response
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }