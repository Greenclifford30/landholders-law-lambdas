
# 📄 Sinful Delights – API Specification (v1) with JSON Schemas

### Base URL:
```
https://api.sinfuldelights.com/v1/
```

### Authentication:
- **Customer endpoints:** `X-API-Key` + Firebase ID Token (`Authorization: Bearer <token>`)
- **Admin endpoints:** `X-API-Key` (Admin key)

---

# 🎨 Customer Endpoints

## GET `/menu/today`
**Purpose:** Fetch today’s active menu.

### Response:
```json
{
  "menuId": "string",
  "date": "YYYY-MM-DD",
  "title": "string",
  "items": [
    {
      "itemId": "string",
      "name": "string",
      "description": "string",
      "price": number,
      "stockQty": number,
      "imageUrl": "string",
      "isSpecial": boolean
    }
  ]
}
```

---

## POST `/order`
**Purpose:** Place a pickup order.

### Request:
```json
{
  "items": [
    { "itemId": "string", "quantity": number }
  ],
  "pickupSlot": "HH:MM"
}
```

### Response:
```json
{
  "orderId": "string",
  "status": "CONFIRMED",
  "total": number,
  "placedAt": "ISO8601",
  "pickupSlot": "HH:MM"
}
```

---

## GET `/subscription`
**Purpose:** Retrieve current user subscription.

### Response:
```json
{
  "subscriptionId": "string",
  "plan": "string",
  "mealsPerWeek": number,
  "portionSize": "string",
  "nextDelivery": "YYYY-MM-DD",
  "status": "ACTIVE",
  "skipDates": ["YYYY-MM-DD"]
}
```

---

## POST `/subscription`
**Purpose:** Create or modify subscription.

### Request:
```json
{
  "plan": "string",
  "mealsPerWeek": number,
  "portionSize": "string",
  "skipDates": ["YYYY-MM-DD"]
}
```

### Response:
```json
{
  "subscriptionId": "string",
  "status": "UPDATED"
}
```

---

## POST `/catering`
**Purpose:** Submit a catering request.

### Request:
```json
{
  "eventDate": "YYYY-MM-DD",
  "guestCount": number,
  "cuisinePreferences": "string",
  "budget": number
}
```

### Response:
```json
{
  "requestId": "string",
  "status": "NEW",
  "depositInvoiceId": "string"
}
```

---

# 🛠️ Admin Endpoints

## GET `/admin/analytics`
**Purpose:** Dashboard metrics.

### Response:
```json
{
  "dailyGrossSales": number,
  "topItems": [
    { "itemId": "string", "name": "string", "quantitySold": number }
  ],
  "subscriptionChurn": number,
  "cateringPipeline": {
    "NEW": number,
    "QUOTED": number,
    "INVOICED": number,
    "SCHEDULED": number,
    "COMPLETED": number
  }
}
```

---

## POST `/admin/menu`
**Purpose:** Create or update a menu & items.

### Request:
```json
{
  "date": "YYYY-MM-DD",
  "title": "string",
  "items": [
    {
      "itemId": "string (optional)",
      "name": "string",
      "description": "string",
      "price": number,
      "stockQty": number,
      "imageUrl": "string",
      "isSpecial": boolean
    }
  ]
}
```

### Response:
```json
{
  "menuId": "string",
  "status": "SAVED"
}
```

---

## GET `/admin/menus`
**Purpose:** List all menus.

### Response:
```json
[
  { "menuId": "string", "date": "YYYY-MM-DD", "title": "string" }
]
```

---

## GET `/admin/menu/{menuId}`
**Purpose:** Get a specific menu.

### Response:
```json
{
  "menuId": "string",
  "date": "YYYY-MM-DD",
  "title": "string",
  "items": [ ... ]
}
```

---

## DELETE `/admin/menu/{menuId}`
**Purpose:** Delete a specific menu.

### Response:
```json
{ "status": "DELETED" }
```

---

## POST `/admin/menu-template`
**Purpose:** Create a new menu template.

### Request:
```json
{
  "name": "string",
  "items": [
    {
      "name": "string",
      "description": "string",
      "price": number,
      "stockQty": number,
      "isSpecial": boolean
    }
  ]
}
```

### Response:
```json
{
  "templateId": "string",
  "status": "CREATED"
}
```

---

## GET `/admin/menu-templates`
**Purpose:** List menu templates.

### Response:
```json
[
  { "templateId": "string", "name": "string", "createdAt": "ISO8601" }
]
```

---

## GET `/admin/menu-template/{templateId}`
**Purpose:** Get a specific template.

### Response:
```json
{
  "templateId": "string",
  "name": "string",
  "items": [ ... ]
}
```

---

## PUT `/admin/menu-template/{templateId}`
**Purpose:** Update a specific template.

### Request:
```json
{
  "name": "string (optional)",
  "items": [ ... ]
}
```

### Response:
```json
{ "status": "UPDATED" }
```

---

## DELETE `/admin/menu-template/{templateId}`
**Purpose:** Delete a specific template.

### Response:
```json
{ "status": "DELETED" }
```

---

## POST `/admin/menu/import`
**Purpose:** Bulk import menu items.

### Request:
- `multipart/form-data` with `file` containing CSV or JSON.

### Response:
```json
{ "status": "IMPORTED", "importedCount": number }
```

---

## POST `/admin/image-upload-url`
**Purpose:** Get a pre-signed S3 URL to upload an image.

### Request:
```json
{
  "fileName": "string",
  "contentType": "image/jpeg"
}
```

### Response:
```json
{
  "uploadUrl": "string",
  "fileUrl": "string"
}
```

---

## POST `/admin/inventory`
**Purpose:** Adjust stock quantities.

### Request:
```json
{
  "itemId": "string",
  "adjustment": number
}
```

### Response:
```json
{
  "itemId": "string",
  "newStockQty": number
}
```

---

# 🔷 Notes
- All endpoints are prefixed with `/v1/`.
- Customer endpoints require both an API Key and Firebase ID Token.
- Admin endpoints require an API Key with admin privileges.
- Bulk imports accept a `multipart/form-data` payload with a CSV/JSON file.
- Image uploads use a two-step process:
  1️⃣ Client calls `/admin/image-upload-url`.  
  2️⃣ Client uploads directly to S3.

---

# 🚀 Next Steps
✅ Align Terraform & Lambdas with updated spec.  
✅ Validate schemas against client code.  
✅ Define proper error codes & rate limits.
