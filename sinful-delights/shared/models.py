"""
Pydantic models for Sinful Delights API v1.1
Generated from OpenAPI specification
"""
from datetime import datetime, date
from typing import List, Optional, Union, Dict, Any
from enum import Enum
import re

try:
    from pydantic import BaseModel, Field, validator, root_validator
except ImportError:
    # Fallback for basic validation if Pydantic is not available
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    def Field(**kwargs):
        return None
    
    def validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    
    def root_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


class CategoryEnum(str, Enum):
    MAIN = "main"
    DESSERT = "dessert"
    APPETIZER = "appetizer"
    BEVERAGE = "beverage"
    SIDES = "sides"


class OrderStatusEnum(str, Enum):
    NEW = "NEW"
    PAID = "PAID"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class SubscriptionStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CateringStatusEnum(str, Enum):
    NEW = "NEW"
    QUOTED = "QUOTED"
    INVOICED = "INVOICED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ErrorCodeEnum(str, Enum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"


# Core Domain Models
class MenuItem(BaseModel):
    itemId: str
    menuId: str
    name: str
    price: float
    stockQty: int
    isSpecial: bool
    available: bool
    description: Optional[str] = None
    imageUrl: Optional[str] = None
    category: Optional[CategoryEnum] = None
    spiceLevel: Optional[int] = None


class Menu(BaseModel):
    menuId: str
    date: str
    title: str
    isActive: bool
    items: List[MenuItem]
    imageUrl: Optional[str] = None
    lastUpdated: Optional[datetime] = None


class PredefinedMenu(BaseModel):
    templateId: str
    name: str
    items: List[MenuItem]
    createdAt: datetime
    tags: Optional[List[str]] = None
    updatedAt: Optional[datetime] = None


class PredefinedMenuCreate(BaseModel):
    name: str
    items: List[MenuItem]
    tags: Optional[List[str]] = None


class PredefinedMenuUpdate(BaseModel):
    name: Optional[str] = None
    items: Optional[List[MenuItem]] = None
    tags: Optional[List[str]] = None


class PredefinedMenuListItem(BaseModel):
    templateId: str
    name: str
    createdAt: datetime


class OrderItem(BaseModel):
    itemId: str
    name: str
    price: float
    qty: int


class Order(BaseModel):
    orderId: str
    userId: str
    items: List[OrderItem]
    total: float
    status: OrderStatusEnum
    pickupSlot: datetime
    placedAt: datetime
    notes: Optional[str] = None


class CreateOrderRequest(BaseModel):
    items: List[dict]  # {itemId: str, quantity: int}
    pickupSlot: datetime
    notes: Optional[str] = None

    @validator('items', each_item=True)
    def validate_order_item(cls, v):
        if not isinstance(v, dict) or 'itemId' not in v or 'quantity' not in v:
            raise ValueError('Each item must have itemId and quantity')
        if not isinstance(v['quantity'], int) or v['quantity'] < 1:
            raise ValueError('quantity must be a positive integer')
        return v


class SubscriptionPlan(BaseModel):
    planId: str
    mealsPerWeek: int
    portion: str
    tags: Optional[List[str]] = None


class Subscription(BaseModel):
    subscriptionId: str
    userId: str
    plan: SubscriptionPlan
    nextDelivery: str = Field(regex=r"^\d{4}-\d{2}-\d{2}$")
    status: SubscriptionStatusEnum
    skipDates: List[str] = []
    createdAt: datetime
    updatedAt: Optional[datetime] = None

    @validator('skipDates', each_item=True)
    def validate_skip_date(cls, v):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError('skipDates must be in YYYY-MM-DD format')
        return v


class UpsertSubscriptionRequest(BaseModel):
    plan: Optional[SubscriptionPlan] = None
    skipDates: Optional[List[str]] = None

    @validator('skipDates', each_item=True)
    def validate_skip_date(cls, v):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError('skipDates must be in YYYY-MM-DD format')
        return v


class CateringContact(BaseModel):
    name: str
    email: str
    phone: str


class CateringRequest(BaseModel):
    requestId: str
    userId: str
    eventDate: str = Field(regex=r"^\d{4}-\d{2}-\d{2}$")
    guestCount: int
    status: CateringStatusEnum
    createdAt: datetime
    updatedAt: Optional[datetime] = None
    depositInvoiceId: Optional[str] = None
    quoteAmount: Optional[float] = None
    budget: Optional[float] = None
    contact: Optional[CateringContact] = None


class CateringRequestCreate(BaseModel):
    eventDate: str = Field(regex=r"^\d{4}-\d{2}-\d{2}$")
    guestCount: int
    cuisinePreferences: Optional[str] = None
    budget: Optional[float] = None
    contact: CateringContact


# Admin Models
class AdminAnalytics(BaseModel):
    dailyGrossSales: float
    topItems: List[Dict[str, Union[str, int]]]
    subscriptionChurn: float
    cateringPipeline: Dict[str, int]


class MenuUpsert(BaseModel):
    menuId: Optional[str] = None
    date: str
    title: str
    isActive: bool
    imageUrl: Optional[str] = None
    items: List[MenuItem]


class PaginatedMenuList(BaseModel):
    page: int
    limit: int
    total: int
    data: List[Dict[str, Union[str, bool]]]


class InventoryAdjustRequest(BaseModel):
    itemId: str
    adjustment: int


class InventoryAdjustResponse(BaseModel):
    itemId: str
    newStockQty: int


class InventoryAdjustment(BaseModel):
    """Alias for backward compatibility"""
    itemId: str
    adjustment: int


# Error Models
class ErrorDetail(BaseModel):
    code: ErrorCodeEnum
    message: str
    details: Optional[Dict[str, Any]] = None


class Error(BaseModel):
    error: ErrorDetail


# Utility functions for validation
def validate_date_format(date_str: str) -> bool:
    """Validate YYYY-MM-DD date format"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))


def validate_iso8601_datetime(dt_str: str) -> bool:
    """Validate ISO8601 datetime format"""
    try:
        datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False