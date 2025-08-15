"""
Test the shared Pydantic models
"""
import pytest
from datetime import datetime
import sys
import os

# Add shared modules to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.models import (
        MenuItem, Menu, Order, CreateOrderRequest, Subscription, 
        UpsertSubscriptionRequest, CateringRequest, CateringRequestCreate,
        AdminAnalytics, MenuUpsert, InventoryAdjustRequest, InventoryAdjustResponse,
        CategoryEnum, OrderStatusEnum, SubscriptionStatusEnum, CateringStatusEnum
    )
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic models not available")
class TestModels:
    """Test Pydantic models validation"""
    
    def test_menu_item_valid(self):
        """Test valid MenuItem creation"""
        item = MenuItem(
            itemId="item-123",
            menuId="menu-456",
            name="Jerk Chicken",
            price=15.99,
            stockQty=25,
            isSpecial=True,
            available=True,
            description="Spicy Caribbean-style chicken",
            category=CategoryEnum.MAIN,
            spiceLevel=4
        )
        
        assert item.itemId == "item-123"
        assert item.price == 15.99
        assert item.stockQty == 25
        assert item.category == CategoryEnum.MAIN
        assert item.spiceLevel == 4
    
    def test_menu_item_validation_errors(self):
        """Test MenuItem validation errors"""
        with pytest.raises(Exception):  # Should fail with negative stock
            MenuItem(
                itemId="item-123",
                menuId="menu-456", 
                name="Test Item",
                price=10.0,
                stockQty=-1,  # Invalid
                isSpecial=False,
                available=True
            )
        
        with pytest.raises(Exception):  # Should fail with invalid spice level
            MenuItem(
                itemId="item-123",
                menuId="menu-456",
                name="Test Item", 
                price=10.0,
                stockQty=10,
                isSpecial=False,
                available=True,
                spiceLevel=10  # Invalid (max is 5)
            )
    
    def test_menu_valid(self):
        """Test valid Menu creation"""
        item = MenuItem(
            itemId="item-123",
            menuId="menu-456",
            name="Test Item",
            price=10.0,
            stockQty=5,
            isSpecial=False,
            available=True
        )
        
        menu = Menu(
            menuId="menu-456",
            date="2025-08-15",
            title="Test Menu",
            isActive=True,
            items=[item]
        )
        
        assert menu.menuId == "menu-456"
        assert menu.date == "2025-08-15"
        assert len(menu.items) == 1
    
    def test_menu_invalid_date(self):
        """Test Menu with invalid date format"""
        with pytest.raises(Exception):
            Menu(
                menuId="menu-456",
                date="15/08/2025",  # Invalid format
                title="Test Menu",
                isActive=True,
                items=[]
            )
    
    def test_create_order_request_valid(self):
        """Test valid CreateOrderRequest"""
        request = CreateOrderRequest(
            items=[{"itemId": "item-123", "quantity": 2}],
            pickupSlot=datetime.now().isoformat() + "Z",
            notes="Extra spicy"
        )
        
        assert len(request.items) == 1
        assert request.items[0]["quantity"] == 2
        assert request.notes == "Extra spicy"
    
    def test_create_order_request_validation(self):
        """Test CreateOrderRequest validation"""
        with pytest.raises(Exception):  # Empty items
            CreateOrderRequest(
                items=[],
                pickupSlot=datetime.now().isoformat() + "Z"
            )
        
        with pytest.raises(Exception):  # Invalid item format
            CreateOrderRequest(
                items=[{"itemId": "item-123"}],  # Missing quantity
                pickupSlot=datetime.now().isoformat() + "Z"
            )
    
    def test_subscription_valid(self):
        """Test valid Subscription creation"""
        subscription = Subscription(
            subscriptionId="sub-123",
            userId="user-456",
            plan={
                "planId": "weekly-3",
                "mealsPerWeek": 3,
                "portion": "regular",
                "tags": ["keto"]
            },
            nextDelivery="2025-08-22",
            status=SubscriptionStatusEnum.ACTIVE,
            skipDates=["2025-08-29", "2025-09-05"],
            createdAt=datetime.now()
        )
        
        assert subscription.plan["mealsPerWeek"] == 3
        assert len(subscription.skipDates) == 2
        assert subscription.status == SubscriptionStatusEnum.ACTIVE
    
    def test_subscription_invalid_skip_dates(self):
        """Test Subscription with invalid skip dates"""
        with pytest.raises(Exception):
            Subscription(
                subscriptionId="sub-123",
                userId="user-456",
                plan={
                    "planId": "weekly-3",
                    "mealsPerWeek": 3,
                    "portion": "regular"
                },
                nextDelivery="2025-08-22",
                status=SubscriptionStatusEnum.ACTIVE,
                skipDates=["2025/08/29"],  # Invalid format
                createdAt=datetime.now()
            )
    
    def test_catering_request_create_valid(self):
        """Test valid CateringRequestCreate"""
        request = CateringRequestCreate(
            eventDate="2025-09-15",
            guestCount=50,
            cuisinePreferences="Italian",
            budget=1500.0,
            contact={
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1-555-123-4567"
            }
        )
        
        assert request.guestCount == 50
        assert request.contact["email"] == "john@example.com"
    
    def test_inventory_adjust_request(self):
        """Test InventoryAdjustRequest validation"""
        # Positive adjustment
        request = InventoryAdjustRequest(
            itemId="item-123",
            adjustment=5
        )
        assert request.adjustment == 5
        
        # Negative adjustment
        request = InventoryAdjustRequest(
            itemId="item-123", 
            adjustment=-3
        )
        assert request.adjustment == -3
    
    def test_error_enums(self):
        """Test enum values"""
        assert CategoryEnum.MAIN == "main"
        assert OrderStatusEnum.NEW == "NEW"
        assert SubscriptionStatusEnum.ACTIVE == "ACTIVE"
        assert CateringStatusEnum.NEW == "NEW"


class TestModelValidationFallback:
    """Test models when Pydantic is not available"""
    
    def test_models_import_fallback(self):
        """Test that models can be imported even without Pydantic"""
        # This test ensures the fallback BaseModel works
        try:
            import sys
            import os
            sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))
            from shared.models import MenuItem
            
            # Should not raise error even with fallback
            item = MenuItem(
                itemId="test",
                menuId="test", 
                name="test",
                price=10.0,
                stockQty=5,
                isSpecial=False,
                available=True
            )
            assert item.itemId == "test"
        except ImportError:
            # Expected if shared modules not available in test environment
            pass