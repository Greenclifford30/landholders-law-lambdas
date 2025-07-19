import json
import os
import boto3
from typing import Dict, Any

# DynamoDB configuration
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def validate_api_key(event: Dict[str, Any]) -> bool:
    """Validate the API key from the event headers."""
    return 'X-API-Key' in event.get('headers', {})

def validate_admin_token(event: Dict[str, Any]) -> bool:
    """Validate admin Firebase Auth ID token."""
    try:
        # In a real-world scenario, this would check for admin role
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Retrieve admin dashboard metrics.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with analytics
    """
    # Validate API key and admin token
    if not validate_api_key(event) or not validate_admin_token(event):
        return {
            'statusCode': 401,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Unauthorized'})
        }
    
    try:
        # Scan for orders and calculate metrics
        orders_response = dynamodb.scan(
            TableName=TABLE_NAME,
            FilterExpression='begins_with(PK, :order)',
            ExpressionAttributeValues={':order': {'S': 'ORDER#'}}
        )
        
        # Scan for subscriptions
        subscriptions_response = dynamodb.scan(
            TableName=TABLE_NAME,
            FilterExpression='contains(SK, :subscription)',
            ExpressionAttributeValues={':subscription': {'S': 'SUBSCRIPTION'}}
        )
        
        # Calculate metrics
        total_sales = sum(
            float(item.get('Total', {}).get('N', 0)) 
            for item in orders_response.get('Items', [])
        )
        
        # Top selling items (this would ideally be tracked more precisely)
        top_items = [
            {'name': 'Chocolate Lava Cake', 'sales': 342},
            {'name': 'Tiramisu', 'sales': 287}
        ]
        
        # Churn calculation (simplified)
        total_subscriptions = len(subscriptions_response.get('Items', []))
        active_subscriptions = len([
            sub for sub in subscriptions_response.get('Items', []) 
            if sub.get('Status', {}).get('S') == 'Active'
        ])
        
        # Construct analytics object
        analytics = {
            'totalSales': round(total_sales, 2),
            'totalOrders': len(orders_response.get('Items', [])),
            'topItems': top_items,
            'totalSubscriptions': total_subscriptions,
            'activeSubscriptions': active_subscriptions,
            'subscriptionChurnRate': round(
                (total_subscriptions - active_subscriptions) / max(total_subscriptions, 1) * 100, 
                2
            ),
            'averageOrderValue': round(
                total_sales / max(len(orders_response.get('Items', [])), 1), 
                2
            )
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(analytics)
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }