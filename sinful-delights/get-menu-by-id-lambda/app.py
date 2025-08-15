"""
GET /menu/{menuId} - Fetch menu by ID (OpenAPI: getMenuById)
"""
import json
import os
import sys
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_customer_access
    from shared.errors import handle_exceptions, create_success_response, NotFoundError, ValidationError
    from shared.dynamo import get_item, query_items, parse_dynamodb_item
    from shared.models import Menu, MenuItem
    from shared.utils import extract_path_params
except ImportError:
    # Fallback for local testing
    import boto3
    dynamodb = boto3.client("dynamodb")
    
    def validate_customer_access(event):
        headers = event.get('headers', {})
        return 'X-API-Key' in headers and 'Authorization' in headers
    
    def handle_exceptions(func):
        return func
    
    def create_success_response(data, status_code=200):
        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(data, default=str)
        }
    
    class NotFoundError(Exception):
        pass
    
    class ValidationError(Exception):
        pass
    
    def extract_path_params(event):
        return event.get('pathParameters') or {}

TABLE_NAME = os.environ.get("TABLE_NAME", "sinful-delights-table")


@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Fetch menu by ID (OpenAPI: getMenuById).
    
    Path parameter: menuId
    Returns Menu object with menu and items for the specified menu ID.
    """
    # Validate customer authentication
    validate_customer_access(event)
    
    # Extract and validate menuId parameter
    path_params = extract_path_params(event)
    menu_id = path_params.get('menuId')
    
    if not menu_id:
        raise ValidationError("Menu ID parameter is required")
    
    # First try to get the menu metadata directly
    try:
        from shared.dynamo import get_item, query_items, parse_dynamodb_item
        
        # Get menu details
        menu_item = get_item(f"MENU#{menu_id}", "DETAILS")
        
        if not menu_item:
            raise NotFoundError(f"Menu with ID {menu_id} not found")
        
        menu_data = parse_dynamodb_item(menu_item)
        
        # Query for all items in this menu
        menu_items = query_items(f"MENU#{menu_id}", "ITEM#")
        
        # Parse menu items
        items = []
        for item in menu_items:
            parsed = parse_dynamodb_item(item)
            if parsed.get('SK', '').startswith('ITEM#'):
                items.append({
                    'itemId': parsed.get('itemId', ''),
                    'menuId': parsed.get('menuId', ''),
                    'name': parsed.get('name', ''),
                    'description': parsed.get('description'),
                    'price': float(parsed.get('price', 0)),
                    'stockQty': int(parsed.get('stockQty', 0)),
                    'imageUrl': parsed.get('imageUrl'),
                    'isSpecial': bool(parsed.get('isSpecial', False)),
                    'category': parsed.get('category'),
                    'spiceLevel': parsed.get('spiceLevel'),
                    'available': bool(parsed.get('available', True))
                })
        
        # Construct menu response according to OpenAPI spec
        menu_response = {
            'menuId': menu_data.get('menuId', menu_id),
            'date': menu_data.get('date', ''),
            'title': menu_data.get('title', f"Menu {menu_id}"),
            'isActive': bool(menu_data.get('isActive', True)),
            'imageUrl': menu_data.get('imageUrl'),
            'lastUpdated': menu_data.get('lastUpdated'),
            'items': items
        }
        
        return create_success_response(menu_response)
        
    except ImportError:
        # Fallback to direct DynamoDB calls for local testing
        import boto3
        dynamodb = boto3.client("dynamodb")
        
        # Try to find menu by scanning (not optimal but fallback)
        response = dynamodb.scan(
            TableName=TABLE_NAME,
            FilterExpression="contains(PK, :menu_id)",
            ExpressionAttributeValues={
                ":menu_id": {"S": menu_id}
            }
        )
        
        if not response.get('Items'):
            raise NotFoundError(f"Menu with ID {menu_id} not found")
        
        # Parse items (simplified for fallback)
        items = []
        menu_data = None
        
        for item in response.get('Items', []):
            if item.get('SK', {}).get('S', '').startswith('ITEM#'):
                items.append({
                    'itemId': item.get('itemId', {}).get('S', ''),
                    'menuId': item.get('menuId', {}).get('S', ''),
                    'name': item.get('name', {}).get('S', ''),
                    'description': item.get('description', {}).get('S'),
                    'price': float(item.get('price', {}).get('N', 0)),
                    'stockQty': int(item.get('stockQty', {}).get('N', 0)),
                    'imageUrl': item.get('imageUrl', {}).get('S'),
                    'isSpecial': item.get('isSpecial', {}).get('BOOL', False),
                    'category': item.get('category', {}).get('S'),
                    'spiceLevel': item.get('spiceLevel', {}).get('N'),
                    'available': item.get('available', {}).get('BOOL', True)
                })
            elif item.get('SK', {}).get('S') == 'DETAILS':
                menu_data = item
        
        if not menu_data:
            raise NotFoundError(f"Menu with ID {menu_id} not found")
        
        menu_response = {
            'menuId': menu_id,
            'date': menu_data.get('date', {}).get('S', ''),
            'title': menu_data.get('title', {}).get('S', f"Menu {menu_id}"),
            'isActive': menu_data.get('isActive', {}).get('BOOL', True),
            'imageUrl': menu_data.get('imageUrl', {}).get('S'),
            'lastUpdated': menu_data.get('lastUpdated', {}).get('S'),
            'items': items
        }
        
        return create_success_response(menu_response)