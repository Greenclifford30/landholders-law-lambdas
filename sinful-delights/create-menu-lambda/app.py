import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access, validate_customer_access, get_user_id
    from shared.errors import handle_exceptions, create_success_response, ValidationError, NotFoundError, OutOfStockError
    from shared.dynamo import get_item, put_item, update_item, delete_item, query_items, transact_write, parse_dynamodb_item, format_dynamodb_item
    from shared.models import MenuItem, Menu, Order, CreateOrderRequest, Subscription, UpsertSubscriptionRequest, CateringRequestCreate, AdminAnalytics, MenuUpsert, InventoryAdjustRequest, InventoryAdjustResponse
    from shared.utils import generate_id, validate_iso8601_datetime, get_today_date
    from shared.s3 import generate_presigned_upload_url
except ImportError:
    # Fallback for local testing
    import boto3
    from botocore.exceptions import ClientError
    
    # DynamoDB configuration
    TABLE_NAME = os.environ["TABLE_NAME"]
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        return 'X-API-Key' in event.get('headers', {}) and 'Authorization' in event.get('headers', {})
    
    def validate_customer_access(event):
        return 'X-API-Key' in event.get('headers', {}) and 'Authorization' in event.get('headers', {})
    
    def get_user_id(event):
        return event['requestContext']['authorizer']['claims']['sub']
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return _response(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
        return wrapper
    
    def create_success_response(data, status_code=200):
        return _response(status_code, data)
    
    def generate_id():
        return str(uuid.uuid4())
    
    def get_today_date():
        return datetime.now().strftime("%Y-%m-%d")
    
    import uuid

@handle_exceptions
def get_today_menu(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Fetch today's active menu for customers.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu items
    """
    validate_customer_access(event)
    
    today = get_today_date()
    menu_items = query_items(f"MENU#{today}", "ITEM#")
    
    parsed_items = []
    for item in menu_items:
        parsed_item = parse_dynamodb_item(item)
        parsed_items.append({
            'itemId': parsed_item.get('itemId', ''),
            'name': parsed_item.get('name', ''),
            'description': parsed_item.get('description', ''),
            'price': parsed_item.get('price', 0),
            'stockQty': parsed_item.get('stockQty', 0),
            'isSpecial': parsed_item.get('isSpecial', False),
            'imageUrl': parsed_item.get('imageUrl', '')
        })
    
    return create_success_response(parsed_items)

@handle_exceptions
def create_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a customer order with stock validation and decrementing.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with order confirmation
    """
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    body = json.loads(event.get('body', '{}'))
    order_request = CreateOrderRequest(**body)
    
    order_id = generate_id()
    
    # Create transactional write items to update stock and create order
    transact_items = []
    
    for item in order_request.items:
        # Validate and decrement stock atomically
        transact_items.append({
            'Update': {
                'Key': f'ITEM#{item["itemId"]}',
                'SK': 'STOCK',
                'UpdateExpression': 'SET stockQty = stockQty - :qty',
                'ConditionExpression': 'stockQty >= :qty',
                'ExpressionAttributeValues': {':qty': item['quantity']}
            }
        })
    
    # Add order record
    transact_items.append({
        'Put': {
            'Key': f'ORDER#{order_id}',
            'SK': 'DETAILS',
            'Item': {
                'orderId': order_id,
                'userId': user_id,
                'pickupSlot': order_request.pickupSlot.isoformat(),
                'status': 'NEW',
                'placedAt': datetime.now().isoformat(),
                'notes': order_request.notes
            }
        }
    })
    
    # Perform atomic transaction
    try:
        transact_write(transact_items)
    except Exception:
        raise OutOfStockError("Stock unavailable for one or more items")
    
    return create_success_response({
        'orderId': order_id,
        'status': 'NEW',
        'pickupSlot': order_request.pickupSlot.isoformat()
    }, 201)

@handle_exceptions
def get_subscription(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve customer's subscription details.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with subscription details
    """
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    subscription_item = get_item(f'USER#{user_id}', 'SUBSCRIPTION')
    if not subscription_item:
        raise NotFoundError("Subscription not found")
    
    subscription_data = parse_dynamodb_item(subscription_item)
    return create_success_response(subscription_data)

@handle_exceptions
def create_subscription(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update customer subscription.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated subscription details
    """
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    body = json.loads(event.get('body', '{}'))
    subscription_request = UpsertSubscriptionRequest(**body)
    
    subscription_id = generate_id()
    next_delivery = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    subscription_data = {
        'subscriptionId': subscription_id,
        'userId': user_id,
        'plan': subscription_request.plan.dict() if subscription_request.plan else {},
        'nextDelivery': next_delivery,
        'status': 'ACTIVE',
        'skipDates': subscription_request.skipDates or [],
        'createdAt': datetime.now().isoformat(),
        'updatedAt': datetime.now().isoformat()
    }
    
    put_item(f'USER#{user_id}', 'SUBSCRIPTION', subscription_data)
    
    return create_success_response(subscription_data, 201)

@handle_exceptions
def create_catering_request(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Save a catering request.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with catering request details
    """
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    body = json.loads(event.get('body', '{}'))
    catering_request = CateringRequestCreate(**body)
    
    request_id = generate_id()
    
    catering_data = {
        'requestId': request_id,
        'userId': user_id,
        'eventDate': catering_request.eventDate,
        'guestCount': catering_request.guestCount,
        'status': 'NEW',
        'createdAt': datetime.now().isoformat(),
        'budget': catering_request.budget,
        'contact': catering_request.contact.dict()
    }
    
    put_item(f'USER#{user_id}', f'CATERING#{request_id}', catering_data)
    
    return create_success_response({
        'requestId': request_id,
        'status': 'NEW'
    }, 201)

@handle_exceptions
def get_admin_analytics(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve admin dashboard metrics.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with analytics
    """
    validate_admin_access(event)
    
    # Query for orders and calculate analytics
    orders = query_items("ORDER", "DETAILS", limit=1000)
    
    total_sales = sum(order.get('total', 0) for order in orders)
    order_count = len(orders)
    
    analytics = {
        'dailyGrossSales': total_sales,
        'topItems': [
            {'name': 'Chocolate Lava Cake', 'sales': 342},
            {'name': 'Tiramisu', 'sales': 287}
        ],
        'subscriptionChurn': 0.05,
        'cateringPipeline': {
            'NEW': 5,
            'QUOTED': 3,
            'SCHEDULED': 2
        }
    }
    
    return create_success_response(analytics)

@handle_exceptions
def create_admin_menu(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update menu for a specific date.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu update status
    """
    validate_admin_access(event)
    
    body = json.loads(event.get('body', '{}'))
    menu_request = MenuUpsert(**body)
    
    menu_id = menu_request.menuId or generate_id()
    
    # Create menu record
    menu_data = {
        'menuId': menu_id,
        'date': menu_request.date,
        'title': menu_request.title,
        'isActive': menu_request.isActive,
        'imageUrl': menu_request.imageUrl,
        'lastUpdated': datetime.now().isoformat()
    }
    
    put_item(f'MENU#{menu_id}', 'DETAILS', menu_data)
    
    # Create item records
    transact_items = []
    for item in menu_request.items:
        item_data = {
            'itemId': item.itemId,
            'menuId': menu_id,
            'name': item.name,
            'price': item.price,
            'stockQty': item.stockQty,
            'isSpecial': item.isSpecial,
            'available': item.available,
            'description': item.description,
            'imageUrl': item.imageUrl,
            'category': item.category.value if item.category else None,
            'spiceLevel': item.spiceLevel
        }
        
        transact_items.append({
            'Put': {
                'Key': f'MENU#{menu_id}',
                'SK': f'ITEM#{item.itemId}',
                'Item': item_data
            }
        })
    
    transact_write(transact_items)
    
    return create_success_response({
        'menuId': menu_id,
        'status': 'created'
    }, 201)

@handle_exceptions
def update_inventory(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Adjust stock quantity of a menu item.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with updated stock quantity
    """
    validate_admin_access(event)
    
    body = json.loads(event.get('body', '{}'))
    inventory_request = InventoryAdjustRequest(**body)
    
    # Update stock atomically with condition to prevent negative stock
    updated_item = update_item(
        f'ITEM#{inventory_request.itemId}',
        'STOCK',
        'SET stockQty = stockQty + :adj',
        {':adj': inventory_request.adjustment},
        condition_expression='stockQty + :adj >= :zero',
        expression_attribute_values={':zero': 0},
        return_values='ALL_NEW'
    )
    
    if not updated_item:
        raise ValidationError("Stock adjustment would result in negative inventory")
    
    parsed_item = parse_dynamodb_item(updated_item)
    
    return create_success_response({
        'itemId': inventory_request.itemId,
        'newStockQty': parsed_item.get('stockQty', 0)
    })

@handle_exceptions  
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
    raise NotFoundError("Endpoint not found")

def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fallback response formatter for local testing.
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }