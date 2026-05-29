"""
Pytest configuration and shared fixtures for Sinful Delights API tests
"""
import pytest
import json
import os
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from typing import Dict, Any


@pytest.fixture
def lambda_context():
    """Mock Lambda context object"""
    context = Mock()
    context.aws_request_id = "test-request-id-123"
    context.log_group_name = "/aws/lambda/test-function"
    context.log_stream_name = "test-stream"
    context.function_name = "test-function"
    context.function_version = "$LATEST"
    context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
    context.memory_limit_in_mb = "128"
    context.get_remaining_time_in_millis = lambda: 5000
    return context


@pytest.fixture
def api_gateway_event():
    """Base API Gateway event structure"""
    return {
        "resource": "/test",
        "path": "/test",
        "httpMethod": "GET",
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        "multiValueHeaders": {},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "stageVariables": None,
        "requestContext": {
            "resourcePath": "/test",
            "httpMethod": "GET",
            "path": "/v1/test",
            "accountId": "123456789012",
            "apiId": "test-api",
            "stage": "v1",
            "requestId": "test-request-id",
            "requestTime": "01/Jan/2025:00:00:00 +0000",
            "requestTimeEpoch": 1735689600,
            "authorizer": {
                "claims": {
                    "sub": "test-user-123",
                    "email": "test@example.com",
                    "role": "user"
                }
            }
        },
        "body": None,
        "isBase64Encoded": False
    }


@pytest.fixture
def customer_headers():
    """Headers for customer endpoints"""
    return {
        "X-API-Key": "test-customer-api-key",
        "Authorization": "Bearer test-firebase-id-token",
        "Content-Type": "application/json"
    }


@pytest.fixture
def admin_headers():
    """Headers for admin endpoints"""
    return {
        "X-API-Key": "test-admin-api-key",
        "Authorization": "Bearer test-admin-firebase-token",
        "Content-Type": "application/json"
    }


@pytest.fixture
def admin_claims():
    """Admin user claims"""
    return {
        "sub": "admin-user-123",
        "email": "admin@sinfuldelights.com",
        "role": "admin",
        "name": "Test Admin"
    }


@pytest.fixture
def customer_claims():
    """Customer user claims"""
    return {
        "sub": "customer-user-456",
        "email": "customer@example.com",
        "role": "user",
        "name": "Test Customer"
    }


def make_api_gateway_event(
    method: str = "GET",
    path: str = "/test",
    headers: Dict[str, str] = None,
    query_params: Dict[str, str] = None,
    path_params: Dict[str, str] = None,
    body: Any = None,
    claims: Dict[str, str] = None
) -> Dict[str, Any]:
    """Helper function to create API Gateway events"""
    
    event = {
        "resource": path,
        "path": path,
        "httpMethod": method,
        "headers": headers or {},
        "multiValueHeaders": {},
        "queryStringParameters": query_params,
        "multiValueQueryStringParameters": None,
        "pathParameters": path_params,
        "stageVariables": None,
        "requestContext": {
            "resourcePath": path,
            "httpMethod": method,
            "path": f"/v1{path}",
            "accountId": "123456789012",
            "apiId": "test-api",
            "stage": "v1",
            "requestId": "test-request-id",
            "requestTime": "01/Jan/2025:00:00:00 +0000",
            "requestTimeEpoch": 1735689600,
            "authorizer": {
                "claims": claims or {
                    "sub": "test-user-123",
                    "email": "test@example.com",
                    "role": "user"
                }
            }
        },
        "body": json.dumps(body) if body else None,
        "isBase64Encoded": False
    }
    
    return event


@pytest.fixture
def sample_menu_item():
    """Sample menu item data"""
    return {
        "itemId": "item-123",
        "menuId": "menu-456",
        "name": "Jerk Chicken",
        "description": "Spicy Caribbean-style grilled chicken",
        "price": 15.99,
        "stockQty": 25,
        "imageUrl": "https://cdn.example.com/jerk-chicken.jpg",
        "isSpecial": True,
        "category": "main",
        "spiceLevel": 4,
        "available": True
    }


@pytest.fixture
def sample_menu():
    """Sample menu data"""
    return {
        "menuId": "menu-456",
        "date": "2025-08-15",
        "title": "Friday Special Menu",
        "isActive": True,
        "imageUrl": "https://cdn.example.com/friday-menu.jpg",
        "lastUpdated": "2025-08-15T14:00:00Z",
        "items": []
    }


@pytest.fixture
def sample_order():
    """Sample order data"""
    return {
        "orderId": "order-789",
        "userId": "customer-user-456",
        "items": [
            {
                "itemId": "item-123",
                "name": "Jerk Chicken",
                "price": 15.99,
                "qty": 2
            }
        ],
        "total": 31.98,
        "status": "NEW",
        "pickupSlot": "2025-08-15T18:00:00Z",
        "placedAt": "2025-08-15T14:30:00Z",
        "notes": "Extra spicy please"
    }


@pytest.fixture
def sample_subscription():
    """Sample subscription data"""
    return {
        "subscriptionId": "sub-101",
        "userId": "customer-user-456",
        "plan": {
            "planId": "weekly-3",
            "mealsPerWeek": 3,
            "portion": "regular",
            "tags": ["keto", "dairy-free"]
        },
        "nextDelivery": "2025-08-22",
        "status": "ACTIVE",
        "skipDates": ["2025-08-29"],
        "createdAt": "2025-07-15T18:00:00Z",
        "updatedAt": "2025-08-10T12:00:00Z"
    }


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB client"""
    with pytest.MonkeyPatch.context() as m:
        mock_client = MagicMock()
        m.setattr("boto3.client", lambda service: mock_client if service == "dynamodb" else Mock())
        yield mock_client


@pytest.fixture
def mock_s3():
    """Mock S3 client"""
    with pytest.MonkeyPatch.context() as m:
        mock_client = MagicMock()
        m.setattr("boto3.client", lambda service: mock_client if service == "s3" else Mock())
        yield mock_client


@pytest.fixture(autouse=True)
def set_env_vars():
    """Set common environment variables for tests"""
    os.environ["TABLE_NAME"] = "test-sinful-delights-table"
    os.environ["BUCKET_NAME"] = "test-sinful-delights-bucket"
    os.environ["CDN_BASE_URL"] = "https://cdn-test.sinfuldelights.com"
    yield
    # Cleanup
    for key in ["TABLE_NAME", "BUCKET_NAME", "CDN_BASE_URL"]:
        if key in os.environ:
            del os.environ[key]


# Test data constants
TODAY = datetime.now().strftime("%Y-%m-%d")
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
VALID_DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"
VALID_ISO8601_REGEX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z?$"