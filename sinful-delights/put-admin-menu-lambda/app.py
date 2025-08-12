import json
import os
import uuid
import boto3
from decimal import Decimal
from typing import Any, Dict, List
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

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

def lambda_handler(event: Dict[str, Any], context: Any):
    # Security (enable when wired)
    # if not validate_api_key(event) or not validate_admin_token(event):
    #     return _resp(401, {"error": "Unauthorized"})

    if event.get("httpMethod") == "OPTIONS":
        return _resp(200, {"ok": True})

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
