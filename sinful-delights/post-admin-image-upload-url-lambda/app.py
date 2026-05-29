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
    from shared.s3 import generate_presigned_upload_url
except ImportError:
    # Fallback for local testing
    import boto3
    from botocore.exceptions import ClientError
    from botocore.config import Config
    
    # S3 configuration
    BUCKET_NAME = os.environ["BUCKET_NAME"]
    s3_client = boto3.client('s3', config=Config(signature_version='s3v4'))
    
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
    
    def generate_presigned_upload_url(file_name, content_type):
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': f'menu-images/{file_name}',
                'ContentType': content_type
            },
            ExpiresIn=3600
        )
        file_url = f'https://{BUCKET_NAME}.s3.amazonaws.com/menu-images/{file_name}'
        return presigned_url, file_url

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate pre-signed S3 URL for image upload.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with upload and file URLs
    """
    validate_admin_access(event)
    
    body = json.loads(event.get('body', '{}'))
    file_name = body.get('fileName')
    content_type = body.get('contentType')
    
    if not file_name or not content_type:
        raise ValidationError("Missing fileName or contentType")
    
    # Validate content type
    if not content_type.startswith('image/'):
        raise ValidationError("Invalid content type - must be an image")
    
    # Generate pre-signed URL using shared utility
    upload_url, file_url = generate_presigned_upload_url(file_name, content_type)
    
    return create_success_response({
        'uploadUrl': upload_url,
        'fileUrl': file_url
    })

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