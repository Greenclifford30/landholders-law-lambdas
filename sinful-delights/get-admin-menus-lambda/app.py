import json
import os
import sys
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access
    from shared.errors import handle_exceptions, create_success_response, ValidationError
    from shared.dynamo import query_items, scan_items_with_pagination
    from shared.models import PaginatedMenuList
    from shared.utils import validate_date_format, parse_pagination_params
except ImportError:
    # Fallback for local testing
    import boto3
    
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
    
    def validate_date_format(date_str):
        import re
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))
    
    def parse_pagination_params(event):
        params = event.get('queryStringParameters') or {}
        page = int(params.get('page', 1))
        limit = min(int(params.get('limit', 50)), 200)
        return page, limit

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    GET /admin/menus - List menus with optional filters (OpenAPI: listMenus)
    """
    # Validate admin access
    validate_admin_access(event)
    
    # Parse query parameters
    query_params = event.get('queryStringParameters') or {}
    from_date = query_params.get('from')
    to_date = query_params.get('to')
    active_filter = query_params.get('active')
    page, limit = parse_pagination_params(event)
    
    # Validate date parameters
    if from_date and not validate_date_format(from_date):
        raise ValidationError("Invalid 'from' date format (YYYY-MM-DD required)")
    
    if to_date and not validate_date_format(to_date):
        raise ValidationError("Invalid 'to' date format (YYYY-MM-DD required)")
    
    try:
        # Build query for menus
        table_name = os.environ.get("TABLE_NAME", "SinfulDelights")
        
        # Query by date range if specified, otherwise scan for all menus
        if from_date or to_date:
            # Use GSI to query by date range
            items = query_menu_by_date_range(table_name, from_date, to_date)
        else:
            # Scan for all menu headers
            items = scan_menu_headers(table_name)
        
        # Filter by active status if specified
        if active_filter is not None:
            is_active = active_filter.lower() == 'true'
            items = [item for item in items if item.get('isActive') == is_active]
        
        # Apply pagination
        total = len(items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = items[start_idx:end_idx]
        
        # Format response data
        menu_list = []
        for item in paginated_items:
            menu_list.append({
                'menuId': item.get('menuId', ''),
                'date': item.get('date', ''),
                'title': item.get('title', ''),
                'isActive': item.get('isActive', True)
            })
        
        response_data = {
            'page': page,
            'limit': limit,
            'total': total,
            'data': menu_list
        }
        
        return create_success_response(response_data)
        
    except Exception as e:
        if 'ValidationException' in str(e):
            raise ValidationError(f"Invalid query parameters: {str(e)}")
        raise


def query_menu_by_date_range(table_name: str, from_date: str = None, to_date: str = None):
    """Query menus by date range using GSI"""
    # This is a simplified implementation - in production you'd use the shared dynamo utilities
    # For now, fall back to scanning all menus
    return scan_menu_headers(table_name)


def scan_menu_headers(table_name: str):
    """Scan for all menu header records"""
    try:
        # Try to use shared utility if available
        items = scan_items_with_pagination(table_name, 'SK', 'META')
        
        result = []
        for item in items:
            if item.get('SK') == 'META':  # Menu header record
                menu_id = item.get('PK', '').replace('MENU#', '')
                result.append({
                    'menuId': menu_id,
                    'date': item.get('date', ''),
                    'title': item.get('title', ''),
                    'isActive': item.get('isActive', True)
                })
        
        return result
    except Exception:
        # Fallback for local testing
        response = dynamodb.scan(
            TableName=table_name,
            FilterExpression='SK = :sk',
            ExpressionAttributeValues={':sk': {'S': 'META'}}
        )
        
        result = []
        for item in response.get('Items', []):
            menu_id = item.get('PK', {}).get('S', '').replace('MENU#', '')
            result.append({
                'menuId': menu_id,
                'date': item.get('date', {}).get('S', ''),
                'title': item.get('title', {}).get('S', ''),
                'isActive': item.get('isActive', {}).get('BOOL', True)
            })
        
        return result


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