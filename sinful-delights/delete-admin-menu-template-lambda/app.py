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
    from shared.dynamo import get_item, delete_item, query_items, transact_write
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
    Delete a specific menu template and all its items.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with deletion status
    """
    validate_admin_access(event)
    
    # Get template ID from path parameters
    template_id = event.get('pathParameters', {}).get('templateId')
    if not template_id:
        raise ValidationError("Missing template ID")
    
    # Check if template exists
    template_item = get_item(f'TEMPLATE#{template_id}', 'DETAILS')
    if not template_item:
        raise NotFoundError("Menu template not found")
    
    # Get all template items
    template_items = query_items(f'TEMPLATE#{template_id}')
    
    # Prepare delete requests
    delete_requests = []
    
    # Add all template items to delete request
    for item in template_items:
        sk_value = item.get('SK', {}).get('S', '') if isinstance(item.get('SK'), dict) else str(item.get('SK', ''))
        delete_requests.append({
            'Delete': {
                'Key': f'TEMPLATE#{template_id}',
                'SK': sk_value
            }
        })
    
    # Execute batch delete in chunks of 25 (DynamoDB limit)
    for i in range(0, len(delete_requests), 25):
        batch = delete_requests[i:i+25]
        transact_write(batch)
    
    return create_success_response({'status': 'DELETED'})

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