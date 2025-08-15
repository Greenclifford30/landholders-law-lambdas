#!/usr/bin/env python3
"""
Batch conversion template for sinful-delights Lambda functions
to use shared layer imports.

This is a utility script to apply the shared layer conversion pattern
to remaining Lambda functions.
"""

import os
import re

# Standard shared layer imports template
SHARED_IMPORTS_TEMPLATE = '''import json
import os
import sys
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access, validate_customer_access
    from shared.errors import handle_exceptions, create_success_response, ValidationError, NotFoundError, OutOfStockError
    from shared.dynamo import get_item, put_item, update_item, delete_item, query_items, transact_write, parse_dynamodb_item, format_dynamodb_item
    from shared.models import {models}
    from shared.utils import generate_id, validate_iso8601_datetime, get_today_date
    from shared.s3 import generate_presigned_upload_url
except ImportError:
    # Fallback for local testing
    import boto3
    from botocore.exceptions import ClientError
    
    # DynamoDB configuration
    TABLE_NAME = os.environ.get("TABLE_NAME")
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        return 'X-API-Key' in event.get('headers', {{}}) and 'Authorization' in event.get('headers', {{}})
    
    def validate_customer_access(event):
        return 'X-API-Key' in event.get('headers', {{}}) and 'Authorization' in event.get('headers', {{}})
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return _response(500, {{'error': {{'code': 'INTERNAL', 'message': str(e)}}}}))
        return wrapper
    
    def create_success_response(data, status_code=200):
        return _response(status_code, data)

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:'''

# Fallback response function
FALLBACK_RESPONSE = '''
def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback response formatter for local testing."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }'''

def get_model_imports_for_function(function_name):
    """Return appropriate model imports based on function name"""
    if 'menu' in function_name:
        return 'Menu, MenuItem, MenuUpsert'
    elif 'template' in function_name:
        return 'PredefinedMenu, PredefinedMenuCreate, PredefinedMenuUpdate'
    elif 'subscription' in function_name:
        return 'Subscription, UpsertSubscriptionRequest'
    elif 'catering' in function_name:
        return 'CateringRequest, CateringRequestCreate'
    elif 'analytics' in function_name:
        return 'AdminAnalytics'
    elif 'inventory' in function_name:
        return 'InventoryAdjustRequest, InventoryAdjustResponse'
    else:
        return ''

# Functions that need conversion
REMAINING_FUNCTIONS = [
    "get-admin-menu-template-lambda",
    "get-admin-menu-templates-lambda", 
    "get-admin-menus-lambda",
    "post-admin-menu-import-lambda",
    "post-admin-menu-lambda",
    "post-admin-menu-template-lambda",
    "post-catering-lambda",
    "post-subscription-lambda",
    "put-admin-menu-lambda",
    "put-admin-menu-template-lambda"
]

print("Shared Layer Conversion Template")
print("=" * 40)
print("This template shows the standard pattern for converting")
print("Lambda functions to use the shared layer imports.")
print()
print("Key conversion steps:")
print("1. Replace imports with shared layer imports")
print("2. Add @handle_exceptions decorator to lambda_handler")
print("3. Replace validation functions with validate_admin_access/validate_customer_access")
print("4. Use shared error handling (raise ValidationError, NotFoundError, etc.)")
print("5. Use shared DynamoDB utilities")
print("6. Use create_success_response instead of manual response construction")
print("7. Add fallback functions for local testing")