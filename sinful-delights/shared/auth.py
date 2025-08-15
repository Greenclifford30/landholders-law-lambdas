"""
Authentication and authorization utilities for Sinful Delights API
"""
from typing import Dict, Any, Optional
from .errors import UnauthorizedError, ForbiddenError


def validate_api_key(event: Dict[str, Any]) -> None:
    """
    Validate that the API key is present in request headers.
    Raises UnauthorizedError if missing.
    """
    headers = event.get('headers', {}) or {}
    # Handle case-insensitive headers (API Gateway normalizes some headers)
    api_key = headers.get('X-API-Key') or headers.get('x-api-key')
    
    if not api_key:
        raise UnauthorizedError("Missing X-API-Key header")


def validate_firebase_token(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate Firebase ID token and return claims.
    Expects claims to be available in requestContext.authorizer.claims
    Raises UnauthorizedError if missing or invalid.
    """
    headers = event.get('headers', {}) or {}
    auth_header = headers.get('Authorization') or headers.get('authorization')
    
    if not auth_header or not auth_header.startswith('Bearer '):
        raise UnauthorizedError("Missing or invalid Authorization header")
    
    # In actual deployment, the Lambda authorizer will validate the token
    # and populate the claims in requestContext
    try:
        claims = event['requestContext']['authorizer']['claims']
        if not claims:
            raise UnauthorizedError("Invalid Firebase ID token")
        return claims
    except (KeyError, TypeError):
        raise UnauthorizedError("Authentication failed - no user claims found")


def validate_admin_access(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that the user has admin access.
    First validates API key, then checks for admin role in claims.
    Returns claims if valid.
    """
    validate_api_key(event)
    
    # For admin endpoints, Firebase token is optional but if present, must have admin role
    headers = event.get('headers', {}) or {}
    auth_header = headers.get('Authorization') or headers.get('authorization')
    
    if auth_header and auth_header.startswith('Bearer '):
        claims = validate_firebase_token(event)
        # Check for admin role
        if claims.get('role') != 'admin':
            raise ForbiddenError("Admin access required")
        return claims
    
    # If no Firebase token, rely on admin-scoped API key (assumed to be validated by API Gateway)
    return {}


def validate_customer_access(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate customer access (API key + Firebase token required).
    Returns user claims.
    """
    validate_api_key(event)
    return validate_firebase_token(event)


def get_user_id(event: Dict[str, Any]) -> str:
    """
    Extract user ID from Firebase claims.
    Assumes validate_firebase_token has been called.
    """
    try:
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims.get('sub') or claims.get('user_id')
        if not user_id:
            raise UnauthorizedError("User ID not found in token claims")
        return user_id
    except (KeyError, TypeError):
        raise UnauthorizedError("User ID not found in token claims")