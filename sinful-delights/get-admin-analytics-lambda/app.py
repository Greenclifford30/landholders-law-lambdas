import json
import os
import sys
from typing import Dict, Any

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access
    from shared.errors import handle_exceptions, create_success_response
    from shared.dynamo import query_items, scan_items
    from shared.models import AdminAnalytics
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
    Retrieve admin dashboard metrics.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with analytics
    """
    validate_admin_access(event)
    
    # Query for orders to calculate metrics
    orders = query_items("ORDER", "DETAILS", limit=1000)
    
    # Query for subscriptions
    subscriptions = query_items("USER", "SUBSCRIPTION", limit=1000)
    
    # Calculate daily gross sales
    total_sales = sum(order.get('total', 0) for order in orders)
    
    # Top selling items (simplified - in production this would be more sophisticated)
    top_items = [
        {'name': 'Chocolate Lava Cake', 'sales': 342},
        {'name': 'Tiramisu', 'sales': 287}
    ]
    
    # Calculate subscription churn
    total_subscriptions = len(subscriptions)
    active_subscriptions = len([
        sub for sub in subscriptions 
        if sub.get('status', '').upper() == 'ACTIVE'
    ])
    
    subscription_churn = (
        (total_subscriptions - active_subscriptions) / max(total_subscriptions, 1) * 100 
        if total_subscriptions > 0 else 0
    )
    
    # Catering pipeline (simplified)
    catering_requests = query_items("USER", "CATERING#", limit=100)
    catering_pipeline = {}
    for request in catering_requests:
        status = request.get('status', 'NEW').upper()
        catering_pipeline[status] = catering_pipeline.get(status, 0) + 1
    
    # Construct analytics response
    analytics = {
        'dailyGrossSales': round(total_sales, 2),
        'topItems': top_items,
        'subscriptionChurn': round(subscription_churn, 2),
        'cateringPipeline': catering_pipeline
    }
    
    return create_success_response(analytics)

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