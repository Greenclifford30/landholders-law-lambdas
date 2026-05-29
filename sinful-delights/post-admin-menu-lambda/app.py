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
    from shared.errors import handle_exceptions, create_success_response, ValidationError
    from shared.dynamo import put_item, transact_write_items
    from shared.models import MenuUpsert, MenuItem
    from shared.utils import generate_uuid, validate_date_format
except ImportError:
    # Fallback for local testing
    import boto3
    from botocore.exceptions import ClientError
    
    TABLE_NAME = os.environ.get("TABLE_NAME", "SinfulDelights")
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        return 'X-API-Key' in event.get('headers', {})
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return _resp(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
        return wrapper
    
    def create_success_response(data, status_code=200):
        return _resp(status_code, data)
    
    def generate_uuid():
        return str(uuid.uuid4())
    
    def validate_date_format(date_str):
        import re
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))
    
    def _ddb_string(val: str) -> Dict[str, Any]:
        return {"S": val}
    
    def _ddb_number(n) -> Dict[str, Any]:
        return {"N": str(n)}
    
    def _ddb_bool(b: bool) -> Dict[str, Any]:
        return {"BOOL": bool(b)}


def _ddb_string(val: str) -> Dict[str, Any]:
    return {"S": val}

def _ddb_number(n) -> Dict[str, Any]:
    return {"N": str(n)}

def _ddb_bool(b: bool) -> Dict[str, Any]:
    return {"BOOL": bool(b)}


def _resp(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback response formatter for local testing."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    POST /admin/menu - Create or update a menu (OpenAPI: upsertMenu)
    """
    # Validate admin access
    validate_admin_access(event)
    
    # Parse and validate request body
    body = json.loads(event.get('body', '{}'))
    
    try:
        # Use shared model for validation if available
        menu_data = MenuUpsert(**body)
        menu_id = menu_data.menuId or generate_uuid()
        menu_date = menu_data.date
        menu_title = menu_data.title
        is_active = menu_data.isActive
        image_url = menu_data.imageUrl
        menu_items = menu_data.items
    except Exception:
        # Fallback validation
        menu_id = body.get('menuId') or generate_uuid()
        menu_date = body.get('date')
        menu_title = body.get('title', '')
        is_active = body.get('isActive', True)
        image_url = body.get('imageUrl')
        menu_items = body.get('items', [])
        
        # Basic validation
        if not menu_date or not validate_date_format(menu_date):
            raise ValidationError("Missing or invalid date (YYYY-MM-DD required)")
        
        if not isinstance(menu_items, list) or len(menu_items) == 0:
            raise ValidationError("Missing menu items")
        
        for item in menu_items:
            if not item.get('name') or item.get('price') is None:
                raise ValidationError(f"Missing required fields for item: {item}")

    # Prepare DynamoDB items for transaction
    table_name = os.environ.get("TABLE_NAME", "SinfulDelights")
    transact_items = []
    
    # 1) Menu header (META)
    current_time = datetime.utcnow().isoformat() + 'Z'
    header_item = {
        "PK": _ddb_string(f"MENU#{menu_id}"),
        "SK": _ddb_string("META"),
        "menuId": _ddb_string(menu_id),
        "date": _ddb_string(menu_date),
        "title": _ddb_string(menu_title),
        "isActive": _ddb_bool(is_active),
        "lastUpdated": _ddb_string(current_time),
        "GSI1PK": _ddb_string(f"MENU_DATE#{menu_date}"),
        "GSI1SK": _ddb_string(f"MENU#{menu_id}")
    }
    
    if image_url:
        header_item["imageUrl"] = _ddb_string(image_url)
    
    transact_items.append({
        "Put": {
            "TableName": table_name,
            "Item": header_item
        }
    })
    
    # 2) Menu items
    for item_data in menu_items:
        item_id = item_data.get('itemId') or generate_uuid()
        
        item_record = {
            "PK": _ddb_string(f"MENU#{menu_id}"),
            "SK": _ddb_string(f"ITEM#{item_id}"),
            "itemId": _ddb_string(item_id),
            "menuId": _ddb_string(menu_id),
            "name": _ddb_string(str(item_data['name'])),
            "price": _ddb_number(item_data['price']),
            "stockQty": _ddb_number(item_data.get('stockQty', 0)),
            "isSpecial": _ddb_bool(item_data.get('isSpecial', False)),
            "available": _ddb_bool(item_data.get('available', True))
        }
        
        # Optional fields
        if item_data.get('description'):
            item_record["description"] = _ddb_string(str(item_data['description']))
        
        if item_data.get('imageUrl'):
            item_record["imageUrl"] = _ddb_string(str(item_data['imageUrl']))
        
        if item_data.get('category'):
            item_record["category"] = _ddb_string(str(item_data['category']))
        
        if item_data.get('spiceLevel') is not None:
            item_record["spiceLevel"] = _ddb_number(item_data['spiceLevel'])
        
        transact_items.append({
            "Put": {
                "TableName": table_name,
                "Item": item_record
            }
        })
    
    try:
        # Execute transaction using shared utility if available
        if 'transact_write_items' in globals():
            transact_write_items(transact_items)
        else:
            # Fallback for local testing
            dynamodb.transact_write_items(TransactItems=transact_items)
        
        return create_success_response({
            "menuId": menu_id,
            "status": "SAVED"
        })
    except Exception as e:
        if 'ValidationException' in str(e) or 'ConditionalCheckFailedException' in str(e):
            raise ValidationError(f"Failed to save menu: {str(e)}")
        raise


def _resp(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }
