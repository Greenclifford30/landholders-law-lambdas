
import json
import os
import sys
from typing import Dict, Any
from datetime import datetime

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_customer_access, get_user_id
    from shared.errors import handle_exceptions, create_success_response, ValidationError
    from shared.dynamo import put_item
    from shared.models import CateringRequestCreate
    from shared.utils import generate_id
except ImportError:
    # Fallback for local testing
    import boto3
    import uuid
    from botocore.exceptions import ClientError
    
    # DynamoDB configuration
    TABLE_NAME = os.environ["TABLE_NAME"]
    dynamodb = boto3.client("dynamodb")
    
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

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
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
    
    if catering_request.cuisinePreferences:
        catering_data['cuisinePreferences'] = catering_request.cuisinePreferences
    
    put_item(f'USER#{user_id}', f'CATERING#{request_id}', catering_data)
    
    return create_success_response({
        'requestId': request_id,
        'status': 'NEW'
    }, 201)

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