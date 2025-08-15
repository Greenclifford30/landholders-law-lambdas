"""
General utilities for Sinful Delights API
"""
import re
import uuid
from datetime import datetime, date
from typing import Any, Dict, Optional


def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix"""
    unique_id = str(uuid.uuid4())
    return f"{prefix}_{unique_id}" if prefix else unique_id


def generate_uuid() -> str:
    """Generate a UUID string (alias for compatibility)"""
    return str(uuid.uuid4())


def validate_date_format(date_str: str) -> bool:
    """Validate YYYY-MM-DD date format"""
    if not isinstance(date_str, str):
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))


def validate_iso8601_datetime(dt_str: str) -> bool:
    """Validate ISO8601 datetime format"""
    if not isinstance(dt_str, str):
        return False
    try:
        # Handle both Z suffix and timezone offsets
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        datetime.fromisoformat(dt_str)
        return True
    except ValueError:
        return False


def parse_iso8601_datetime(dt_str: str) -> datetime:
    """Parse ISO8601 datetime string to datetime object"""
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str)


def format_datetime_iso8601(dt: datetime) -> str:
    """Format datetime object to ISO8601 string"""
    return dt.isoformat() + 'Z' if dt.tzinfo is None else dt.isoformat()


def get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format"""
    return date.today().strftime("%Y-%m-%d")


def validate_pagination_params(page: Optional[int], limit: Optional[int]) -> Dict[str, int]:
    """
    Validate and normalize pagination parameters.
    Returns dict with validated page and limit values.
    """
    validated_page = max(1, page or 1)
    validated_limit = max(1, min(200, limit or 50))  # Cap at 200
    
    return {
        "page": validated_page,
        "limit": validated_limit
    }


def calculate_pagination_offset(page: int, limit: int) -> int:
    """Calculate DynamoDB scan/query offset for pagination"""
    return (page - 1) * limit


def extract_query_params(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalize query parameters from Lambda event"""
    query_params = event.get('queryStringParameters') or {}
    if query_params is None:
        return {}
    
    # Convert string parameters to appropriate types
    normalized = {}
    for key, value in query_params.items():
        if value is None:
            continue
        
        # Handle boolean parameters
        if value.lower() in ('true', 'false'):
            normalized[key] = value.lower() == 'true'
        # Handle integer parameters
        elif value.isdigit():
            normalized[key] = int(value)
        # Handle float parameters
        elif '.' in value and value.replace('.', '').isdigit():
            normalized[key] = float(value)
        else:
            normalized[key] = value
    
    return normalized


def parse_pagination_params(event: Dict[str, Any]) -> tuple:
    """Parse pagination parameters from Lambda event"""
    params = event.get('queryStringParameters') or {}
    page = max(1, int(params.get('page', 1)))
    limit = max(1, min(200, int(params.get('limit', 50))))
    return page, limit


def extract_path_params(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract path parameters from Lambda event"""
    return event.get('pathParameters') or {}


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """Sanitize string input for security"""
    if not isinstance(value, str):
        return ""
    
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>"\']', '', value)
    
    # Limit length
    return sanitized[:max_length].strip()


def validate_email(email: str) -> bool:
    """Basic email validation"""
    if not isinstance(email, str) or len(email) > 254:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """Basic phone number validation (allows international formats)"""
    if not isinstance(phone, str):
        return False
    
    # Remove common formatting characters
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    
    # Check if remaining characters are digits and length is reasonable
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15


def format_currency(amount: float) -> float:
    """Format currency amount to 2 decimal places"""
    return round(float(amount), 2)


def validate_price(price: Any) -> bool:
    """Validate price value"""
    try:
        price_float = float(price)
        return price_float >= 0 and price_float <= 99999.99  # Reasonable max price
    except (ValueError, TypeError):
        return False


def validate_stock_quantity(qty: Any) -> bool:
    """Validate stock quantity"""
    try:
        qty_int = int(qty)
        return 0 <= qty_int <= 9999  # Reasonable max stock
    except (ValueError, TypeError):
        return False


def clean_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from dictionary"""
    return {k: v for k, v in data.items() if v is not None}