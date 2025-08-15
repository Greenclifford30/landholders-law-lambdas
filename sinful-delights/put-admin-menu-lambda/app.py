import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List

# Add shared modules to path
sys.path.append('/opt/python')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from shared.auth import validate_admin_access
    from shared.errors import handle_exceptions, create_success_response, ValidationError, NotFoundError
    from shared.dynamo import put_item, get_item, query_items, delete_item, batch_write
    from shared.models import Menu, MenuItem
    from shared.utils import generate_uuid, validate_date_format
except ImportError:
    # Fallback for local testing
    import boto3
    from decimal import Decimal
    from boto3.dynamodb.conditions import Key
    
    TABLE_NAME = os.environ.get("TABLE_NAME", "SinfulDelights")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    
    def validate_admin_access(event):
        return 'X-API-Key' in event.get('headers', {})
    
    def handle_exceptions(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except Exception as e:
                return _resp(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
        return wrapper
    
    def create_success_response(data, status_code=200):
        return _resp(status_code, data)
    
    def generate_uuid():
        return str(uuid.uuid4())
    
    def validate_date_format(date_str):
        import re
        return bool(re.match(r'^\\d{4}-\\d{2}-\\d{2}$', date_str))

# --- helpers ---------------------------------------------------------------

def _to_decimal(v):
    if isinstance(v, float) or isinstance(v, int):
        # Avoid float binary issues
        return Decimal(str(v))
    if isinstance(v, list):
        return [_to_decimal(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_decimal(v2) for k, v2 in v.items()}
    return v

def _resp(code: int, body: Any):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-API-Key",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }

def validate_api_key(event: Dict[str, Any]) -> bool:
    return "X-API-Key" in (event.get("headers") or {})

def validate_admin_token(event: Dict[str, Any]) -> bool:
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
        return claims.get("role") == "admin"
    except Exception:
        return False

# --- handler ---------------------------------------------------------------

@handle_exceptions
def lambda_handler(event: Dict[str, Any], context: Any):
    """
    PUT /admin/menu/{menuId} - Update an existing menu (OpenAPI compatible)
    """
    # Validate admin access
    validate_admin_access(event)

    if event.get("httpMethod") == "OPTIONS":
        return _resp(200, {"ok": True})
    
    # Get menu ID from path parameters
    menu_id = event.get('pathParameters', {}).get('menuId')
    if not menu_id:
        raise ValidationError("Missing menu ID in path")

    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode("utf-8")
        payload = json.loads(body)

        # Required
        menu_id = payload.get("menuId")
        if not menu_id:
            return _resp(400, {"error": "menuId is required"})

        # Header fields
        title      = payload.get("title", "")
        menu_date  = payload.get("menuDate", "")
        is_active  = payload.get("isActive", True)
        image_url  = payload.get("imageUrl", "")
        last_updated = payload.get("lastUpdated")  # optional client-provided
        replace_items = bool(payload.get("replaceItems", False))

        # 1) Upsert header (itemId="META")
        header_item = {
            "menuId": menu_id,
            "itemId": "META",
            "title": title,
            "menuDate": menu_date,     # ensure present for GSI1MenuDate
            "isActive": is_active,
            "imageUrl": image_url,
            "lastUpdated": last_updated or __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        table.put_item(Item=_to_decimal(header_item))

        # 2) Collect existing ITEM#... if we may need to "replace"
        existing_item_ids: List[str] = []
        if replace_items:
            q = table.query(
                KeyConditionExpression=Key("menuId").eq(menu_id) & Key("itemId").begins_with("ITEM#")
            )
            existing_item_ids = [it["itemId"] for it in q.get("Items", [])]

        # 3) Process item operations
        items = payload.get("items") or []
        upserts, deletes, touched_ids = [], [], set()
        for it in items:
            op = (it.get("_op") or "upsert").lower()
            item_id = it.get("itemId")
            if op == "delete":
                if item_id and item_id.startswith("ITEM#"):
                    deletes.append({"menuId": menu_id, "itemId": item_id})
                    touched_ids.add(item_id)
                continue

            # upsert
            if not item_id:
                item_id = f"ITEM#{uuid.uuid4().hex}"
            record = {
                "menuId": menu_id,
                "itemId": item_id,
                "name": it.get("name", ""),
                "description": it.get("description", ""),
                "price": it.get("price", 0),
                "stockQty": it.get("stockQty", 0),
                "imageUrl": it.get("imageUrl", ""),
                "isSpecial": bool(it.get("isSpecial", False)),
                "category": it.get("category"),
                "available": bool(it.get("available", True)),
                "spiceLevel": it.get("spiceLevel"),
                # put menuDate on items so GSI1 can return header then items
                "menuDate": menu_date,
            }
            upserts.append(_to_decimal(record))
            touched_ids.add(item_id)

        # 4) If replaceItems=true, delete any not mentioned this round
        if replace_items and existing_item_ids:
            for eid in existing_item_ids:
                if eid not in touched_ids:
                    deletes.append({"menuId": menu_id, "itemId": eid})

        # 5) Write in batches (Put/Delete)
        with table.batch_writer(overwrite_by_pkeys=["menuId", "itemId"]) as bw:
            for it in upserts:
                bw.put_item(Item=it)
            for key in deletes:
                bw.delete_item(Key=key)

        return _resp(200, {
            "menuId": menu_id,
            "updatedHeader": True,
            "upsertedCount": len(upserts),
            "deletedCount": len(deletes),
            "itemIds": [it["itemId"] for it in upserts],
            "deletedItemIds": [d["itemId"] for d in deletes],
        })

    except Exception as e:
        return _resp(500, {"error": str(e)})
