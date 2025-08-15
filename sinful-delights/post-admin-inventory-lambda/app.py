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
    from shared.dynamo import update_item_atomic
    from shared.models import InventoryAdjustment
except ImportError:
    # Fallback for local testing
    import boto3
    dynamodb = boto3.client("dynamodb")
    
    def validate_admin_access(event):
        headers = event.get('headers', {})
        if not 'X-API-Key' in headers:
            raise Exception("Unauthorized")
        # Basic admin validation fallback
        return True
    
    def handle_exceptions(func):
        return func
    
    def create_success_response(data, status_code=200):
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(data)
        }
    
    def update_item_atomic(table_name, key, update_expr, attr_values, condition_expr=None):
        return dynamodb.update_item(
            TableName=table_name,
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=attr_values,
            ConditionExpression=condition_expr,
            ReturnValues='UPDATED_NEW'
        )

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    POST /admin/inventory - Adjust stock quantity of a menu item (OpenAPI: postAdminInventory)
    """
    # Validate admin access
    validate_admin_access(event)
    
    # Parse and validate request body
    body = json.loads(event.get('body', '{}'))
    
    try:
        # Use shared model for validation if available
        adjustment_data = InventoryAdjustment(**body)
        item_id = adjustment_data.itemId
        adjustment = adjustment_data.adjustment
    except:
        # Fallback validation
        item_id = body.get('itemId')
        adjustment = body.get('adjustment')
        
        if not item_id or adjustment is None:
            raise ValidationError("Missing required fields: itemId, adjustment")
    
    # Update item stock in DynamoDB using shared utility
    table_name = os.environ.get("TABLE_NAME", "SinfulDelights")
    
    try:
        response = update_item_atomic(
            table_name=table_name,
            key={
                'PK': {'S': f'ITEM#{item_id}'},
                'SK': {'S': 'DETAILS'}
            },
            update_expr='SET stockQty = stockQty + :adj',
            attr_values={':adj': {'N': str(adjustment)}}
        )
        
        # Retrieve new stock quantity
        new_stock_qty = int(response.get('Attributes', {}).get('stockQty', {}).get('N', 0))
        
        return create_success_response({
            'itemId': item_id,
            'newStockQty': new_stock_qty,
            'adjustment': adjustment
        })
    except Exception as e:
        # Handle DynamoDB errors
        if 'ValidationException' in str(e):
            raise ValidationError(f"Invalid item ID: {item_id}")
        raise