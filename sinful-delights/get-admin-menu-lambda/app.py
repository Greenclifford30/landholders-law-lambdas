import json
import os
import sys
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access
    from shared.errors import handle_exceptions, create_success_response, NotFoundError, ValidationError
    from shared.dynamo import get_item, query_items, parse_dynamodb_item
    from shared.models import Menu
except ImportError:
    # Fallback for local testing
    import boto3
    from botocore.exceptions import ClientError
    
    # DynamoDB configuration
    TABLE_NAME = os.environ["TABLE_NAME"]
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        return 'X-API-Key' in event.get('headers', {}) and 'Authorization' in event.get('headers', {})
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return _response(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
        return wrapper
    
    def create_success_response(data, status_code=200):
        return _response(status_code, data)

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve a specific menu with all its items.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with menu details
    """
    validate_admin_access(event)
    
    # Get menu ID from path parameters
    menu_id = event.get('pathParameters', {}).get('menuId')
    if not menu_id:
        raise ValidationError("Missing menu ID")
    
    # Get menu details
    menu_item = get_item(f'MENU#{menu_id}', 'DETAILS')
    if not menu_item:
        raise NotFoundError("Menu not found")
    
    # Get menu items
    menu_items = query_items(f'MENU#{menu_id}', 'ITEM#')
    
    # Parse menu details
    menu_data = parse_dynamodb_item(menu_item)
    
    # Parse menu items
    items = []
    for item in menu_items:
        parsed_item = parse_dynamodb_item(item)
        items.append({
            'itemId': parsed_item.get('itemId', ''),
            'name': parsed_item.get('name', ''),
            'description': parsed_item.get('description', ''),
            'price': parsed_item.get('price', 0),
            'stockQty': parsed_item.get('stockQty', 0),
            'isSpecial': parsed_item.get('isSpecial', False),
            'available': parsed_item.get('available', True),
            'imageUrl': parsed_item.get('imageUrl', ''),
            'category': parsed_item.get('category', ''),
            'spiceLevel': parsed_item.get('spiceLevel', 0)
        })
    
    menu = {
        'menuId': menu_data.get('menuId', menu_id),
        'date': menu_data.get('date', ''),
        'title': menu_data.get('title', ''),
        'isActive': menu_data.get('isActive', False),
        'imageUrl': menu_data.get('imageUrl', ''),
        'items': items,
        'lastUpdated': menu_data.get('lastUpdated')
    }
    
    return create_success_response(menu)

def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback response formatter for local testing."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }