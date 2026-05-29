# 📄 Sinful Delights – API Specification (v1.1)

**Updated:** August 15, 2025

This version aligns all request/response bodies to the latest data model from the PRD (menus with richer item metadata, ISO8601 timestamps, subscription `plan` object, and expanded catering fields).

---

## Base URLs
- **Production**: `https://api.sinfuldelights.com/v1/`
- **Staging/Dev**: `https://api-dev.sinfuldelights.com/v1/`

## Authentication
- **Customer endpoints:** `X-API-Key` header **and** Firebase ID token via `Authorization: Bearer <token>`.
- **Admin endpoints:** `X-API-Key` (admin scope) **and** optional Firebase ID token when using the admin UI.

### Common Headers
```
X-API-Key: <your-key>
Authorization: Bearer <firebase-id-token>   # required for customer-authenticated calls
Content-Type: application/json
```

## Conventions
- Times are **ISO8601** (`YYYY-MM-DDThh:mm:ssZ`). Dates without time use `YYYY-MM-DD`.
- Monetary amounts are decimal numbers **in USD**.
- All endpoints are under `/v1`.
- Pagination (where applicable): `?page=1&limit=50`. Responses include `page`, `limit`, `total`.

## Error Model
```json
{
  "error": {
    "code": "STRING_ENUM",
    "message": "Human-readable message",
    "details": {}  // optional object with field-level issues
  }
}
```
Example error codes: `UNAUTHENTICATED`, `UNAUTHORIZED`, `NOT_FOUND`, `VALIDATION_ERROR`, `OUT_OF_STOCK`, `RATE_LIMITED`, `INTERNAL`.

---

# 🔷 Schemas (JSON)

### MenuItem
```json
{
  "itemId": "string",               
  "menuId": "string",
  "name": "string",
  "description": "string",
  "price": 12.34,
  "stockQty": 25,
  "imageUrl": "https://.../img.jpg",
  "isSpecial": true,
  "category": "main",               // enum: main|dessert|appetizer|beverage|sides
  "spiceLevel": 3,                  // 0-5 optional
  "available": true                 // hides/disables when false
}
```

### Menu
```json
{
  "menuId": "string",
  "date": "YYYY-MM-DD",
  "title": "string",
  "isActive": true,
  "imageUrl": "https://.../menu.jpg",
  "lastUpdated": "2025-08-15T14:00:00Z",
  "items": [ <MenuItem> ]
}
```

### PredefinedMenu (Template)
```json
{
  "templateId": "string",
  "name": "string",
  "items": [ <MenuItem> ],
  "tags": ["bbq","spicy"],          // optional
  "createdAt": "2025-08-01T20:11:22Z",
  "updatedAt": "2025-08-10T10:00:00Z"
}
```

### Order
```json
{
  "orderId": "string",
  "userId": "string",
  "items": [{ "itemId": "string", "name": "string", "price": 9.99, "qty": 2 }],
  "total": 29.97,
  "status": "PAID",                 // enum: NEW|PAID|READY|PICKED_UP|CANCELLED
  "pickupSlot": "2025-08-23T17:30:00Z",
  "placedAt": "2025-08-15T14:05:00Z",
  "notes": "No onions please"
}
```

### Subscription
```json
{
  "subscriptionId": "string",
  "userId": "string",
  "plan": {                      
    "planId": "weekly-3",
    "mealsPerWeek": 3,
    "portion": "regular",
    "tags": ["keto","dairy-free"]
  },
  "nextDelivery": "2025-08-25",
  "status": "ACTIVE",               // enum: ACTIVE|PAUSED|CANCELLED
  "skipDates": ["2025-08-18", "2025-09-01"],
  "createdAt": "2025-07-15T18:00:00Z",
  "updatedAt": "2025-08-10T12:00:00Z"
}
```

### CateringRequest
```json
{
  "requestId": "string",
  "userId": "string",
  "eventDate": "2025-09-20",
  "guestCount": 80,
  "status": "NEW",                  // enum: NEW|QUOTED|INVOICED|SCHEDULED|COMPLETED|CANCELLED
  "depositInvoiceId": "in_123",     // optional (Stripe)
  "quoteAmount": 1200.00,           // optional
  "budget": 1500.00,                // optional
  "contact": { "name": "string", "email": "a@b.com", "phone": "+1-312-555-1234" },
  "createdAt": "2025-08-15T14:00:00Z",
  "updatedAt": "2025-08-15T14:00:00Z"
}
```

---

# 🎨 Customer Endpoints

## GET `/menu/today`
Fetch today’s active menu for the user’s locale/timezone.
### Response → **Menu**

## GET `/menu/{date}`
Fetch the active menu for a specific date (`YYYY-MM-DD`).
### Response → **Menu**

## GET `/menu/{menuId}`
Fetch a specific menu by id.
### Response → **Menu**

## POST `/order`
Place a pickup order.
### Request
```json
{
  "items": [ { "itemId": "string", "quantity": 2 } ],
  "pickupSlot": "2025-08-23T17:30:00Z",
  "notes": "Leave at front counter"   // optional
}
```
### Response → **Order**

## GET `/subscription`
Get the authenticated user’s subscription.
### Response → **Subscription**

## POST `/subscription`
Create or update the user’s subscription.
### Request
```json
{
  "plan": {
    "planId": "weekly-5",
    "mealsPerWeek": 5,
    "portion": "large",
    "tags": ["high-protein"]
  },
  "skipDates": ["2025-08-25"]
}
```
### Response
```json
{ "subscriptionId": "sub_123", "status": "UPDATED" }
```

## POST `/catering`
Submit a catering request.
### Request
```json
{
  "eventDate": "2025-09-20",
  "guestCount": 80,
  "cuisinePreferences": "Cajun",
  "budget": 1500,
  "contact": { "name": "Jane Doe", "email": "jane@x.com", "phone": "+1-312-555-1234" }
}
```
### Response
```json
{ "requestId": "req_123", "status": "NEW", "depositInvoiceId": null }
```

---

# 🛠️ Admin Endpoints

## GET `/admin/analytics`
Dashboard metrics (time-range via `?from=YYYY-MM-DD&to=YYYY-MM-DD`).
### Response
```json
{
  "dailyGrossSales": 1234.56,
  "topItems": [ { "itemId": "it_1", "name": "Jerk Chicken", "quantitySold": 42 } ],
  "subscriptionChurn": 0.03,
  "cateringPipeline": { "NEW": 2, "QUOTED": 1, "INVOICED": 0, "SCHEDULED": 1, "COMPLETED": 3, "CANCELLED": 0 }
}
```

## POST `/admin/menu`
Create or update a menu for a date. When `menuId` is provided, updates in-place.
### Request
```json
{
  "menuId": "string-optional",
  "date": "YYYY-MM-DD",
  "title": "string",
  "isActive": true,
  "imageUrl": "https://.../menu.jpg",
  "items": [ <MenuItem> ]
}
```
### Response
```json
{ "menuId": "m_123", "status": "SAVED" }
```

## GET `/admin/menus`
List menus with optional filters (`?from`, `to`, `active=true`).
### Response
```json
{
  "page": 1, "limit": 50, "total": 3,
  "data": [ { "menuId": "m_1", "date": "2025-08-15", "title": "Friday Menu", "isActive": true } ]
}
```

## GET `/admin/menu/{menuId}`
Return full menu, including items.
### Response → **Menu**

## DELETE `/admin/menu/{menuId}`
Delete a menu.
### Response
```json
{ "status": "DELETED" }
```

## POST `/admin/inventory`
Adjust stock for an item (atomic increment/decrement).
### Request
```json
{ "itemId": "it_123", "adjustment": -2 }
```
### Response
```json
{ "itemId": "it_123", "newStockQty": 23 }
```

## POST `/admin/menu-template`
Create a predefined menu (template).
### Request → **PredefinedMenu** (without `templateId`, `createdAt/updatedAt`)
### Response
```json
{ "templateId": "t_123", "status": "CREATED" }
```

## GET `/admin/menu-templates`
List templates (supports `?tag=bbq`).
### Response
```json
[ { "templateId": "t_123", "name": "BBQ Set", "createdAt": "2025-08-01T20:11:22Z" } ]
```

## GET `/admin/menu-template/{templateId}`
Return a template.
### Response → **PredefinedMenu**

## PUT `/admin/menu-template/{templateId}`
Update a template.
### Request → Partial **PredefinedMenu** (fields optional)
### Response
```json
{ "status": "UPDATED" }
```

## DELETE `/admin/menu-template/{templateId}`
Remove a template.
### Response
```json
{ "status": "DELETED" }
```

## POST `/admin/menu/apply-template`
Apply a template’s items to a specific date, merging with existing menu items (by `name` or `itemId`).
### Request
```json
{ "templateId": "t_123", "date": "2025-08-29" }
```
### Response
```json
{ "menuId": "m_999", "status": "APPLIED" }
```

## POST `/admin/image-upload-url`
Issue a pre-signed S3 URL.
### Request
```json
{ "fileName": "menu-0815.jpg", "contentType": "image/jpeg" }
```
### Response
```json
{ "uploadUrl": "https://s3/presigned...", "fileUrl": "https://cdn/.../menu-0815.jpg" }
```

---

## Webhooks (Stripe)
- **`/webhooks/stripe`** handles payment events:
  - One-time payments → set `Order.status=PAID`.
  - Invoice events (catering deposits, subscriptions) → update related entities.

## Rate Limits
- Default: **100 req/min** per API key (overrideable via Usage Plans).

## Security
- HTTPS required. API keys rotated monthly.
- Firebase ID token validated by a Lambda authorizer; `role` claim gates admin UI.
- CloudWatch + X-Ray for tracing; PII minimised in logs.

---

## Changelog
- **v1.1**: Align with PRD: richer `MenuItem` (category, spiceLevel, available), `Menu` (`isActive`, `imageUrl`, `lastUpdated`), ISO8601 `pickupSlot`, `Order.status` enums, `Subscription.plan` object, expanded `CateringRequest` with `contact`, `budget`, `quoteAmount`, and template tagging.
- **v1.0**: Initial release.
