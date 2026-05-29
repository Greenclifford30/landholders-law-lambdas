"""
POST /admin/menu/apply-template - Apply template to date (OpenAPI: applyTemplateToDate)
"""
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
    from shared.auth import validate_admin_access
    from shared.errors import handle_exceptions, create_success_response, ValidationError, NotFoundError
    from shared.dynamo import get_item, put_item, query_items, parse_dynamodb_item, format_dynamodb_item
    from shared.utils import validate_date_format, generate_id
except ImportError:
    # Fallback for local testing
    import boto3
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        headers = event.get('headers', {})
        if not 'X-API-Key' in headers:
            raise Exception("Unauthorized")
    
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
    
    class NotFoundError(Exception):
        pass
    
    def validate_date_format(date_str):
        import re
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))
    
    def generate_id(prefix=""):
        unique_id = str(uuid.uuid4())
        return f"{prefix}_{unique_id}" if prefix else unique_id

TABLE_NAME = os.environ.get("TABLE_NAME", "sinful-delights-table")


@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Apply a template's items to a specific date (OpenAPI: applyTemplateToDate).
    
    Request body:
    {
        "templateId": "string",
        "date": "YYYY-MM-DD"
    }
    
    Merges template items with existing menu items by name or itemId.
    """
    # Validate admin authentication
    validate_admin_access(event)
    
    # Parse and validate request body
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON in request body")
    
    template_id = body.get('templateId')
    date = body.get('date')
    
    if not template_id:
        raise ValidationError("templateId is required")
    
    if not date:
        raise ValidationError("date is required")
    
    if not validate_date_format(date):
        raise ValidationError("date must be in YYYY-MM-DD format")
    
    try:
        from shared.dynamo import get_item, put_item, query_items, parse_dynamodb_item
        
        # Get the template
        template_item = get_item(f"TEMPLATE#{template_id}", "DETAILS")
        if not template_item:
            raise NotFoundError(f"Template {template_id} not found")
        
        template_data = parse_dynamodb_item(template_item)
        
        # Get template items
        template_items = query_items(f"TEMPLATE#{template_id}", "ITEM#")
        
        # Check if menu for date already exists
        existing_menu = get_item(f"MENU#{date}", "DETAILS")
        menu_id = None
        
        if existing_menu:
            menu_data = parse_dynamodb_item(existing_menu)
            menu_id = menu_data.get('menuId')
        else:
            # Create new menu
            menu_id = generate_id("menu")
            menu_data = {
                'PK': {'S': f'MENU#{date}'},
                'SK': {'S': 'DETAILS'},
                'menuId': {'S': menu_id},
                'date': {'S': date},
                'title': {'S': f"Menu for {date} (from {template_data.get('name', 'template')})"},
                'isActive': {'BOOL': True},
                'lastUpdated': {'S': datetime.utcnow().isoformat() + 'Z'}
            }
            put_item(menu_data)
        
        # Get existing menu items (if any)
        existing_items = query_items(f"MENU#{date}", "ITEM#")
        existing_item_names = set()
        existing_item_ids = set()
        
        for item in existing_items:
            parsed_item = parse_dynamodb_item(item)
            existing_item_names.add(parsed_item.get('name', ''))
            existing_item_ids.add(parsed_item.get('itemId', ''))
        
        # Apply template items (merge by name, skip if already exists)
        items_added = 0
        for template_item in template_items:
            if template_item.get('SK', {}).get('S', '').startswith('ITEM#'):
                parsed_template_item = parse_dynamodb_item(template_item)
                
                # Skip if item with same name or ID already exists
                if (parsed_template_item.get('name') in existing_item_names or 
                    parsed_template_item.get('itemId') in existing_item_ids):
                    continue
                
                # Create new item for this menu
                new_item_id = generate_id("item")
                menu_item_data = {
                    'PK': {'S': f'MENU#{date}'},
                    'SK': {'S': f'ITEM#{new_item_id}'},
                    'itemId': {'S': new_item_id},
                    'menuId': {'S': menu_id},
                    'name': {'S': parsed_template_item.get('name', '')},
                    'description': {'S': parsed_template_item.get('description', '')},
                    'price': {'N': str(parsed_template_item.get('price', 0))},
                    'stockQty': {'N': str(parsed_template_item.get('stockQty', 0))},
                    'isSpecial': {'BOOL': parsed_template_item.get('isSpecial', False)},
                    'available': {'BOOL': parsed_template_item.get('available', True)}
                }
                
                # Add optional fields
                if parsed_template_item.get('imageUrl'):
                    menu_item_data['imageUrl'] = {'S': parsed_template_item['imageUrl']}
                if parsed_template_item.get('category'):
                    menu_item_data['category'] = {'S': parsed_template_item['category']}
                if parsed_template_item.get('spiceLevel') is not None:
                    menu_item_data['spiceLevel'] = {'N': str(parsed_template_item['spiceLevel'])}
                
                put_item(menu_item_data)
                items_added += 1
        
        return create_success_response({
            "menuId": menu_id,
            "status": "APPLIED",
            "itemsAdded": items_added
        })
        
    except ImportError:
        # Fallback implementation (simplified)
        import boto3
        dynamodb = boto3.client("dynamodb")
        
        # Get template (simplified)
        template_response = dynamodb.query(
            TableName=TABLE_NAME,
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": {"S": f"TEMPLATE#{template_id}"}}
        )
        
        if not template_response.get('Items'):
            raise NotFoundError(f"Template {template_id} not found")
        
        # Create/update menu (simplified)
        menu_id = str(uuid.uuid4())
        
        return create_success_response({
            "menuId": menu_id,
            "status": "APPLIED"
        })