import json
import os
import boto3
import uuid
import base64
import csv
import io
from typing import Dict, Any, List

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

def process_csv(csv_content: str) -> List[Dict[str, Any]]:
    """Process CSV content and return list of menu items."""
    items = []
    csv_file = io.StringIO(csv_content)
    reader = csv.DictReader(csv_file)
    
    for row in reader:
        try:
            item = {
                'name': row['name'],
                'description': row.get('description', ''),
                'price': float(row['price']),
                'stockQty': int(row.get('stockQty', 0)),
                'isSpecial': row.get('isSpecial', '').lower() == 'true'
            }
            items.append(item)
        except (KeyError, ValueError) as e:
            continue
    
    return items

def process_json(json_content: str) -> List[Dict[str, Any]]:
    """Process JSON content and return list of menu items."""
    try:
        data = json.loads(json_content)
        if not isinstance(data, list):
            return []
        
        items = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
            try:
                processed_item = {
                    'name': item['name'],
                    'description': item.get('description', ''),
                    'price': float(item['price']),
                    'stockQty': int(item.get('stockQty', 0)),
                    'isSpecial': bool(item.get('isSpecial', False))
                }
                items.append(processed_item)
            except (KeyError, ValueError):
                continue
        
        return items
    except json.JSONDecodeError:
        return []

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Import menu items from CSV or JSON file.
    
    Args:
        event (Dict[str, Any]): Lambda event dictionary
        context (Any): Lambda context object
    
    Returns:
        Dict[str, Any]: HTTP response with import status
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
        # Get content type and file content from multipart form data
        content_type = event.get('headers', {}).get('Content-Type', '')
        if not content_type.startswith('multipart/form-data'):
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Invalid content type'})
            }
        
        # Parse multipart form data
        body = event.get('body', '')
        if not body:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Missing file content'})
            }
        
        # Assuming the file content is base64 encoded
        file_content = base64.b64decode(body).decode('utf-8')
        
        # Process file based on content
        if file_content.startswith('{') or file_content.startswith('['):
            items = process_json(file_content)
        else:
            items = process_csv(file_content)
        
        if not items:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'No valid items found in file'})
            }
        
        # Prepare batch write items
        batch_items = []
        menu_id = str(uuid.uuid4())
        
        for item in items:
            item_id = str(uuid.uuid4())
            batch_items.append({
                'Put': {
                    'TableName': TABLE_NAME,
                    'Item': {
                        'PK': {'S': f'MENU#{menu_id}'},
                        'SK': {'S': f'ITEM#{item_id}'},
                        'ItemId': {'S': item_id},
                        'Name': {'S': item['name']},
                        'Description': {'S': item['description']},
                        'Price': {'N': str(item['price'])},
                        'StockQty': {'N': str(item['stockQty'])},
                        'IsSpecial': {'BOOL': item['isSpecial']}
                    }
                }
            })
        
        # Write items in batches of 25
        for i in range(0, len(batch_items), 25):
            batch = batch_items[i:i+25]
            dynamodb.transact_write_items(TransactItems=batch)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'status': 'IMPORTED',
                'importedCount': len(items)
            })
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