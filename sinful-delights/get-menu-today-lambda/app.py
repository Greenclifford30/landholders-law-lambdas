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
    from shared.auth import validate_customer_access
    from shared.errors import handle_exceptions, create_success_response, NotFoundError
    from shared.dynamo import query_items, parse_dynamodb_item
    from shared.models import Menu, MenuItem
    from shared.utils import get_today_date
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
    
    def get_today_date():
        return datetime.now().strftime("%Y-%m-%d")

TABLE_NAME = os.environ.get("TABLE_NAME", "sinful-delights-table")

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Fetch today's active menu for customers (OpenAPI: getTodayMenu).
    
    Returns Menu object with today's active menu and items.
    """
    # Validate customer authentication
    validate_customer_access(event)
    
    today = get_today_date()
    
    # Query for today's active menu
    try:
        from shared.dynamo import query_items, parse_dynamodb_item
        
        menu_items = query_items(f"MENU#{today}", "ITEM#")
        
        if not menu_items:
            raise NotFoundError("No menu found for today")
        
        # Parse menu items
        items = []
        menu_data = None
        
        for item in menu_items:
            parsed = parse_dynamodb_item(item)
            
            if parsed.get('SK', '').startswith('ITEM#'):
                # This is a menu item
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
            elif parsed.get('SK') == 'DETAILS':
                # This is the menu metadata
                menu_data = parsed
        
        # Construct menu response according to OpenAPI spec
        menu_response = {
            'menuId': menu_data.get('menuId', str(uuid.uuid4())),
            'date': today,
            'title': menu_data.get('title', f"Menu for {today}"),
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
        
        response = dynamodb.query(
            TableName=TABLE_NAME,
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={
                ":pk": {"S": f"MENU#{today}"}
            }
        )
        
        if not response.get('Items'):
            raise NotFoundError("No menu found for today")
        
        # Parse items (simplified for fallback)
        items = []
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
        
        menu_response = {
            'menuId': str(uuid.uuid4()),
            'date': today,
            'title': f"Menu for {today}",
            'isActive': True,
            'items': items
        }
        
        return create_success_response(menu_response)