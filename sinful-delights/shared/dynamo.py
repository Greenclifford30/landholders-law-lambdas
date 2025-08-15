"""
DynamoDB utilities for Sinful Delights API
"""
import boto3
import os
from typing import Dict, Any, List, Optional
from botocore.exceptions import ClientError
from .errors import OutOfStockError, NotFoundError, InternalError


# Initialize DynamoDB client
dynamodb = boto3.client('dynamodb')
dynamodb_resource = boto3.resource('dynamodb')


def get_table_name() -> str:
    """Get DynamoDB table name from environment"""
    table_name = os.environ.get('TABLE_NAME')
    if not table_name:
        raise InternalError("TABLE_NAME environment variable not set")
    return table_name


def decrement_stock(item_id: str, quantity: int) -> int:
    """
    Atomically decrement stock quantity for an item.
    Prevents negative stock by using conditional expression.
    Returns the updated stock quantity.
    Raises OutOfStockError if insufficient stock.
    """
    table_name = get_table_name()
    
    try:
        response = dynamodb.update_item(
            TableName=table_name,
            Key={
                'PK': {'S': f'ITEM#{item_id}'},
                'SK': {'S': 'DETAILS'}
            },
            UpdateExpression='SET stockQty = stockQty - :qty',
            ConditionExpression='stockQty >= :qty AND available = :true',
            ExpressionAttributeValues={
                ':qty': {'N': str(quantity)},
                ':true': {'BOOL': True}
            },
            ReturnValues='UPDATED_NEW'
        )
        return int(response['Attributes']['stockQty']['N'])
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ConditionalCheckFailedException':
            raise OutOfStockError(f"Insufficient stock for item {item_id}", item_id)
        else:
            raise InternalError(f"Failed to update stock: {str(e)}")


def adjust_stock(item_id: str, adjustment: int) -> int:
    """
    Adjust stock quantity for an item (can be positive or negative).
    For negative adjustments, prevents going below zero.
    Returns the updated stock quantity.
    """
    table_name = get_table_name()
    
    try:
        # If adjustment is negative, add condition to prevent negative stock
        if adjustment < 0:
            response = dynamodb.update_item(
                TableName=table_name,
                Key={
                    'PK': {'S': f'ITEM#{item_id}'},
                    'SK': {'S': 'DETAILS'}
                },
                UpdateExpression='SET stockQty = stockQty + :adj',
                ConditionExpression='stockQty >= :min_stock',
                ExpressionAttributeValues={
                    ':adj': {'N': str(adjustment)},
                    ':min_stock': {'N': str(abs(adjustment))}
                },
                ReturnValues='UPDATED_NEW'
            )
        else:
            response = dynamodb.update_item(
                TableName=table_name,
                Key={
                    'PK': {'S': f'ITEM#{item_id}'},
                    'SK': {'S': 'DETAILS'}
                },
                UpdateExpression='SET stockQty = stockQty + :adj',
                ExpressionAttributeValues={
                    ':adj': {'N': str(adjustment)}
                },
                ReturnValues='UPDATED_NEW'
            )
        
        return int(response['Attributes']['stockQty']['N'])
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ConditionalCheckFailedException':
            raise OutOfStockError(f"Cannot adjust stock below zero for item {item_id}", item_id)
        else:
            raise InternalError(f"Failed to adjust stock: {str(e)}")


def get_item(pk: str, sk: str) -> Optional[Dict[str, Any]]:
    """
    Get a single item from DynamoDB.
    Returns None if item not found.
    """
    table_name = get_table_name()
    
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={
                'PK': {'S': pk},
                'SK': {'S': sk}
            }
        )
        return response.get('Item')
    except ClientError as e:
        raise InternalError(f"Failed to get item: {str(e)}")


def put_item(item: Dict[str, Any]) -> None:
    """
    Put an item into DynamoDB.
    """
    table_name = get_table_name()
    
    try:
        dynamodb.put_item(
            TableName=table_name,
            Item=item
        )
    except ClientError as e:
        raise InternalError(f"Failed to put item: {str(e)}")


def query_items(pk: str, sk_prefix: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
    """
    Query items from DynamoDB by partition key and optional sort key prefix.
    """
    table_name = get_table_name()
    
    try:
        params = {
            'TableName': table_name,
            'KeyConditionExpression': 'PK = :pk',
            'ExpressionAttributeValues': {
                ':pk': {'S': pk}
            }
        }
        
        if sk_prefix:
            params['KeyConditionExpression'] += ' AND begins_with(SK, :sk)'
            params['ExpressionAttributeValues'][':sk'] = {'S': sk_prefix}
        
        # Add any additional parameters
        params.update(kwargs)
        
        response = dynamodb.query(**params)
        return response.get('Items', [])
    except ClientError as e:
        raise InternalError(f"Failed to query items: {str(e)}")


def scan_with_filter(filter_expression: str, expression_values: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
    """
    Scan table with filter expression.
    """
    table_name = get_table_name()
    
    try:
        params = {
            'TableName': table_name,
            'FilterExpression': filter_expression,
            'ExpressionAttributeValues': expression_values
        }
        params.update(kwargs)
        
        response = dynamodb.scan(**params)
        return response.get('Items', [])
    except ClientError as e:
        raise InternalError(f"Failed to scan items: {str(e)}")


def transact_write(transact_items: List[Dict[str, Any]]) -> None:
    """
    Perform a transaction write with multiple items.
    """
    try:
        dynamodb.transact_write_items(TransactItems=transact_items)
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'TransactionCanceledException':
            # Check cancellation reasons for specific errors
            raise OutOfStockError("Transaction failed - possible stock constraint violation")
        else:
            raise InternalError(f"Transaction failed: {str(e)}")


def parse_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse DynamoDB item format to regular Python dict.
    """
    if not item:
        return {}
    
    parsed = {}
    for key, value in item.items():
        if 'S' in value:
            parsed[key] = value['S']
        elif 'N' in value:
            parsed[key] = float(value['N']) if '.' in value['N'] else int(value['N'])
        elif 'BOOL' in value:
            parsed[key] = value['BOOL']
        elif 'L' in value:
            parsed[key] = [parse_dynamodb_item({'item': v})['item'] for v in value['L']]
        elif 'M' in value:
            parsed[key] = parse_dynamodb_item(value['M'])
        elif 'NULL' in value:
            parsed[key] = None
    
    return parsed


def format_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format regular Python dict to DynamoDB item format.
    """
    formatted = {}
    for key, value in item.items():
        if value is None:
            formatted[key] = {'NULL': True}
        elif isinstance(value, str):
            formatted[key] = {'S': value}
        elif isinstance(value, (int, float)):
            formatted[key] = {'N': str(value)}
        elif isinstance(value, bool):
            formatted[key] = {'BOOL': value}
        elif isinstance(value, list):
            formatted[key] = {'L': [format_dynamodb_item({'item': v})['item'] for v in value]}
        elif isinstance(value, dict):
            formatted[key] = {'M': format_dynamodb_item(value)}
    
    return formatted