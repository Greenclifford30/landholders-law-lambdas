"""
Error handling utilities for Sinful Delights API
"""
import json
from typing import Dict, Any, Optional


class APIError(Exception):
    """Base exception for API errors"""
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class ValidationError(APIError):
    """Raised when request validation fails"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("VALIDATION_ERROR", message, 400, details)


class UnauthorizedError(APIError):
    """Raised when authentication fails"""
    def __init__(self, message: str = "API key or ID token is missing/invalid"):
        super().__init__("UNAUTHENTICATED", message, 401)


class ForbiddenError(APIError):
    """Raised when authorization fails"""
    def __init__(self, message: str = "Insufficient privileges"):
        super().__init__("UNAUTHORIZED", message, 403)


class NotFoundError(APIError):
    """Raised when resource is not found"""
    def __init__(self, message: str = "Resource not found"):
        super().__init__("NOT_FOUND", message, 404)


class OutOfStockError(APIError):
    """Raised when item is out of stock"""
    def __init__(self, message: str, item_id: Optional[str] = None):
        details = {"itemId": item_id} if item_id else None
        super().__init__("OUT_OF_STOCK", message, 409, details)


class RateLimitError(APIError):
    """Raised when rate limit is exceeded"""
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__("RATE_LIMITED", message, 429)


class InternalError(APIError):
    """Raised for internal server errors"""
    def __init__(self, message: str = "Internal server error"):
        super().__init__("INTERNAL", message, 500)


def create_error_response(error: APIError) -> Dict[str, Any]:
    """Create a standardized error response"""
    response = {
        'statusCode': error.status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'error': {
                'code': error.code,
                'message': error.message,
                **({"details": error.details} if error.details else {})
            }
        })
    }
    return response


def create_success_response(data: Any, status_code: int = 200) -> Dict[str, Any]:
    """Create a standardized success response"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(data, default=str)  # default=str handles datetime serialization
    }


def handle_exceptions(func):
    """Decorator to handle exceptions in Lambda handlers"""
    def wrapper(event, context):
        try:
            return func(event, context)
        except APIError as e:
            return create_error_response(e)
        except Exception as e:
            # Convert unexpected exceptions to InternalError
            internal_error = InternalError(f"Unexpected error: {str(e)}")
            return create_error_response(internal_error)
    return wrapper