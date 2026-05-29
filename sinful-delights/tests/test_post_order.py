"""
Test POST /order endpoint
"""
import pytest
import json
import sys
import os
from unittest.mock import patch, MagicMock

# Add lambda directory to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'post-order-lambda'))

try:
    from app import lambda_handler
    LAMBDA_AVAILABLE = True
except ImportError:
    LAMBDA_AVAILABLE = False


@pytest.mark.skipif(not LAMBDA_AVAILABLE, reason="Lambda handler not available")
class TestPostOrder:
    
    def test_unauthorized_request(self, lambda_context):
        """Test request without proper authentication"""
        event = {
            "httpMethod": "POST",
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "items": [{"itemId": "item-123", "quantity": 2}],
                "pickupSlot": "2025-08-15T18:00:00Z"
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 401
    
    def test_invalid_json_body(self, lambda_context):
        """Test request with invalid JSON body"""
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": "invalid json"
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body
        assert "JSON" in body["error"]["message"]
    
    def test_missing_required_fields(self, lambda_context):
        """Test request missing required fields"""
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({})  # Missing items and pickupSlot
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body
        assert "required" in body["error"]["message"].lower()
    
    def test_invalid_items_format(self, lambda_context):
        """Test request with invalid items format"""
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key", 
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({
                "items": [{"itemId": "item-123"}],  # Missing quantity
                "pickupSlot": "2025-08-15T18:00:00Z"
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 400
    
    def test_invalid_pickup_slot_format(self, lambda_context):
        """Test request with invalid pickupSlot format"""
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({
                "items": [{"itemId": "item-123", "quantity": 2}],
                "pickupSlot": "2025-08-15 18:00:00"  # Invalid format
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "ISO8601" in body["error"]["message"]
    
    @patch('boto3.client')
    def test_successful_order_creation(self, mock_boto3, lambda_context):
        """Test successful order creation"""
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        # Mock item details response
        mock_dynamodb.get_item.return_value = {
            "Item": {
                "itemId": {"S": "item-123"},
                "name": {"S": "Jerk Chicken"},
                "price": {"N": "15.99"},
                "stockQty": {"N": "25"},
                "available": {"BOOL": True}
            }
        }
        
        # Mock successful transaction
        mock_dynamodb.transact_write_items.return_value = {}
        
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({
                "items": [{"itemId": "item-123", "quantity": 2}],
                "pickupSlot": "2025-08-15T18:00:00Z",
                "notes": "Extra spicy please"
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        
        assert "orderId" in body
        assert "userId" in body
        assert body["status"] == "NEW"
        assert body["total"] == 31.98  # 15.99 * 2
        assert body["pickupSlot"] == "2025-08-15T18:00:00Z"
        assert body["notes"] == "Extra spicy please"
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Jerk Chicken"
    
    @patch('boto3.client')
    def test_item_not_found(self, mock_boto3, lambda_context):
        """Test order with non-existent item"""
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        # Mock empty item response
        mock_dynamodb.get_item.return_value = {}
        
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({
                "items": [{"itemId": "non-existent", "quantity": 1}],
                "pickupSlot": "2025-08-15T18:00:00Z"
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "not found" in body["error"]["message"]
    
    @patch('boto3.client')
    def test_out_of_stock_error(self, mock_boto3, lambda_context):
        """Test order when item is out of stock"""
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        # Mock item details
        mock_dynamodb.get_item.return_value = {
            "Item": {
                "itemId": {"S": "item-123"},
                "name": {"S": "Jerk Chicken"},
                "price": {"N": "15.99"},
                "stockQty": {"N": "25"},
                "available": {"BOOL": True}
            }
        }
        
        # Mock stock constraint failure
        from botocore.exceptions import ClientError
        mock_dynamodb.transact_write_items.side_effect = ClientError(
            {"Error": {"Code": "TransactionCanceledException"}},
            "TransactWriteItems"
        )
        
        event = {
            "httpMethod": "POST",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            },
            "body": json.dumps({
                "items": [{"itemId": "item-123", "quantity": 30}],  # More than stock
                "pickupSlot": "2025-08-15T18:00:00Z"
            })
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert "OUT_OF_STOCK" in body["error"]["code"]
    
    def test_order_with_multiple_items(self, lambda_context):
        """Test order with multiple different items"""
        with patch('boto3.client') as mock_boto3:
            mock_dynamodb = MagicMock()
            mock_boto3.return_value = mock_dynamodb
            
            # Mock responses for different items
            def mock_get_item(TableName, Key):
                item_id = Key['PK']['S'].split('#')[1]
                if item_id == "item-123":
                    return {
                        "Item": {
                            "itemId": {"S": "item-123"},
                            "name": {"S": "Jerk Chicken"},
                            "price": {"N": "15.99"},
                            "available": {"BOOL": True}
                        }
                    }
                elif item_id == "item-456":
                    return {
                        "Item": {
                            "itemId": {"S": "item-456"},
                            "name": {"S": "Rice and Peas"},
                            "price": {"N": "8.50"},
                            "available": {"BOOL": True}
                        }
                    }
                return {}
            
            mock_dynamodb.get_item.side_effect = mock_get_item
            mock_dynamodb.transact_write_items.return_value = {}
            
            event = {
                "httpMethod": "POST",
                "headers": {
                    "X-API-Key": "test-key",
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json"
                },
                "requestContext": {
                    "authorizer": {
                        "claims": {"sub": "user-123"}
                    }
                },
                "body": json.dumps({
                    "items": [
                        {"itemId": "item-123", "quantity": 1},
                        {"itemId": "item-456", "quantity": 2}
                    ],
                    "pickupSlot": "2025-08-15T18:00:00Z"
                })
            }
            
            with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
                response = lambda_handler(event, lambda_context)
            
            assert response["statusCode"] == 201
            body = json.loads(response["body"])
            assert len(body["items"]) == 2
            assert body["total"] == 32.99  # 15.99 + (8.50 * 2)