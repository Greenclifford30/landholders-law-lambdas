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
    from shared.dynamo import scan_with_filter, parse_dynamodb_item
    from shared.utils import validate_date_format, parse_pagination_params
except ImportError:
    # Fallback for local testing
    import boto3
    
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        headers = event.get('headers', {})
        if not 'X-API-Key' in headers:
            raise Exception("Unauthorized")
        return True
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': {'code': 'INTERNAL', 'message': str(e)}})
                }
        return wrapper
    
    def create_success_response(data, status_code=200):
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(data)
        }
    
    def validate_date_format(date_str):
        import re
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))
    
    def parse_pagination_params(event):
        params = event.get('queryStringParameters') or {}
        page = max(1, int(params.get('page', 1)))
        limit = max(1, min(200, int(params.get('limit', 50))))
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
    
    # Scan for all menu headers using shared utility
    items = scan_with_filter('SK = :sk', {':sk': {'S': 'META'}})
    
    # Parse and filter menu data
    menus = []
    for item in items:
        parsed_item = parse_dynamodb_item(item)
        menu_id = parsed_item.get('PK', '').replace('MENU#', '')
        menu_data = {
            'menuId': menu_id,
            'date': parsed_item.get('date', ''),
            'title': parsed_item.get('title', ''),
            'isActive': parsed_item.get('isActive', True)
        }
        
        # Apply date filters
        if from_date and menu_data['date'] < from_date:
            continue
        if to_date and menu_data['date'] > to_date:
            continue
        
        # Apply active filter
        if active_filter is not None:
            is_active = active_filter.lower() == 'true'
            if menu_data['isActive'] != is_active:
                continue
        
        menus.append(menu_data)
    
    # Apply pagination
    total = len(menus)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_menus = menus[start_idx:end_idx]
    
    response_data = {
        'page': page,
        'limit': limit,
        'total': total,
        'data': paginated_menus
    }
    
    return create_success_response(response_data)