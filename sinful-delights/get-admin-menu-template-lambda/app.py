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
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except:
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get a specific menu template with all its items.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with template details
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
        # Get template ID from path parameters
        template_id = event.get('pathParameters', {}).get('templateId')
        if not template_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing template ID'})
            }
        
        # Get template details
        template_response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                'PK': {'S': f'TEMPLATE#{template_id}'},
                'SK': {'S': 'DETAILS'}
            }
        )
        
        if 'Item' not in template_response:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Template not found'})
            }
        
        template = template_response['Item']
        
        # Get template items
        items_response = dynamodb.query(
            TableName=TABLE_NAME,
            KeyConditionExpression='PK = :pk AND begins_with(SK, :item)',
            ExpressionAttributeValues={
                ':pk': {'S': f'TEMPLATE#{template_id}'},
                ':item': {'S': 'ITEM#'}
            }
        )
        
        items = []
        for item in items_response.get('Items', []):
            items.append({
                'name': item.get('Name', {}).get('S', ''),
                'description': item.get('Description', {}).get('S', ''),
                'price': float(item.get('Price', {}).get('N', 0)),
                'stockQty': int(item.get('StockQty', {}).get('N', 0)),
                'isSpecial': item.get('IsSpecial', {}).get('BOOL', False)
            })
        
        template_data = {
            'templateId': template_id,
            'name': template.get('Name', {}).get('S', ''),
            'items': items
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(template_data)
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