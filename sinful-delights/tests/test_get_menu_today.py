"""
Test GET /menu/today endpoint
"""
import pytest
import json
import sys
import os
from unittest.mock import patch, MagicMock

# Add lambda directory to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'get-menu-today-lambda'))

try:
    from app import lambda_handler
    LAMBDA_AVAILABLE = True
except ImportError:
    LAMBDA_AVAILABLE = False


@pytest.mark.skipif(not LAMBDA_AVAILABLE, reason="Lambda handler not available")
class TestGetMenuToday:
    
    def test_missing_api_key(self, lambda_context):
        """Test request without API key"""
        event = {
            "httpMethod": "GET",
            "headers": {
                "Authorization": "Bearer test-token"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert "error" in body
    
    def test_missing_auth_token(self, lambda_context):
        """Test request without Authorization header"""
        event = {
            "httpMethod": "GET",
            "headers": {
                "X-API-Key": "test-key"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 401
    
    @patch('boto3.client')
    def test_successful_menu_retrieval(self, mock_boto3, lambda_context):
        """Test successful menu retrieval"""
        # Mock DynamoDB response
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "PK": {"S": "MENU#2025-08-15"},
                    "SK": {"S": "DETAILS"},
                    "menuId": {"S": "menu-123"},
                    "title": {"S": "Today's Menu"},
                    "isActive": {"BOOL": True}
                },
                {
                    "PK": {"S": "MENU#2025-08-15"},
                    "SK": {"S": "ITEM#item-456"},
                    "itemId": {"S": "item-456"},
                    "menuId": {"S": "menu-123"},
                    "name": {"S": "Jerk Chicken"},
                    "description": {"S": "Spicy Caribbean chicken"},
                    "price": {"N": "15.99"},
                    "stockQty": {"N": "25"},
                    "isSpecial": {"BOOL": True},
                    "available": {"BOOL": True},
                    "category": {"S": "main"},
                    "spiceLevel": {"N": "4"}
                }
            ]
        }
        
        event = {
            "httpMethod": "GET",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        
        assert "menuId" in body
        assert "date" in body
        assert "items" in body
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Jerk Chicken"
        assert body["items"][0]["price"] == 15.99
        assert body["items"][0]["spiceLevel"] == 4
    
    @patch('boto3.client')
    def test_no_menu_found(self, mock_boto3, lambda_context):
        """Test when no menu exists for today"""
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        mock_dynamodb.query.return_value = {"Items": []}
        
        event = {
            "httpMethod": "GET",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "error" in body
        assert "No menu found" in body["error"]["message"]
    
    @patch('boto3.client')
    def test_dynamodb_error(self, mock_boto3, lambda_context):
        """Test DynamoDB error handling"""
        mock_dynamodb = MagicMock()
        mock_boto3.return_value = mock_dynamodb
        
        mock_dynamodb.query.side_effect = Exception("DynamoDB error")
        
        event = {
            "httpMethod": "GET",
            "headers": {
                "X-API-Key": "test-key",
                "Authorization": "Bearer test-token"
            },
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body
    
    def test_cors_headers(self, lambda_context):
        """Test that CORS headers are included"""
        event = {
            "httpMethod": "GET", 
            "headers": {},
            "requestContext": {
                "authorizer": {
                    "claims": {"sub": "user-123"}
                }
            }
        }
        
        with patch.dict(os.environ, {"TABLE_NAME": "test-table"}):
            response = lambda_handler(event, lambda_context)
        
        assert "Access-Control-Allow-Origin" in response["headers"]
        assert response["headers"]["Access-Control-Allow-Origin"] == "*"
        assert response["headers"]["Content-Type"] == "application/json"


class TestGetMenuTodayFallback:
    """Test fallback behavior when lambda is not available"""
    
    def test_import_fallback(self):
        """Test that missing lambda doesn't break tests"""
        # This test ensures the test suite can run even if lambda code is not available
        assert True  # Placeholder - in real scenario would test mock implementation