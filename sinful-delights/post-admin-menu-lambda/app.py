import json
import os
import boto3
import uuid
from typing import Dict, Any
from botocore.exceptions import ClientError

# DynamoDB configuration
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def validate_api_key(event: Dict[str, Any]) -> bool:
    """Validate the API key from the event headers."""
    return 'X-API-Key' in (event.get('headers') or {})

def validate_admin_token(event: Dict[str, Any]) -> bool:
    """Validate admin Firebase Auth ID token."""
    try:
        claims = event['requestContext']['authorizer']['claims']
        return claims.get('role') == 'admin'
    except Exception:
        return False

def _ddb_string(val: str) -> Dict[str, Any]:
    return {"S": val}

def _ddb_number(n) -> Dict[str, Any]:
    return {"N": str(n)}

def _ddb_bool(b: bool) -> Dict[str, Any]:
    return {"BOOL": bool(b)}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create or update a menu for a specific date.
    Expects body: { "date": "YYYY-MM-DD", "title": "Steak Menu", "items": [...] }
    """
    # Auth (uncomment when ready)
    # if not validate_api_key(event) or not validate_admin_token(event):
    #     return _resp(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
        menu_date: str = body.get("date")
        menu_title: str = body.get("title", "")
        menu_items = body.get("items", [])

        # Validate input
        if not menu_date or not isinstance(menu_items, list) or len(menu_items) == 0:
            return _resp(400, {"error": "Missing menu details"})

        # Basic item validation
        for it in menu_items:
            if not it.get("name") or it.get("price") is None:
                return _resp(400, {"error": f"Missing required fields for item: {it}"})

        # Generate menu ID
        menu_id = str(uuid.uuid4())

        transact_items = []

        # 1) Header row (META)
        header_item = {
            "menuId":   _ddb_string(f"MENU#{menu_id}"),
            "itemId":   _ddb_string("META"),          # SK for header
            "menuDate": _ddb_string(menu_date),       # attribute for GSI queries
            "title":    _ddb_string(menu_title),
            "isActive": _ddb_bool(True),
        }
        transact_items.append({
            "Put": {
                "TableName": TABLE_NAME,
                "Item": header_item,
                "ConditionExpression": "attribute_not_exists(menuId) AND attribute_not_exists(itemId)"
            }
        })

        # 2) Menu items (ITEM#<uuid>)
        for raw in menu_items:
            item_id = str(uuid.uuid4())
            put_item = {
                "menuId":   _ddb_string(f"MENU#{menu_id}"),      # PK
                "itemId":   _ddb_string(f"ITEM#{item_id}"),      # SK
                "menuDate": _ddb_string(menu_date),              # for GSI on date
                "id":       _ddb_string(item_id),

                "name":        _ddb_string(str(raw["name"])),
                "description": _ddb_string(str(raw.get("description", ""))),
                "price":       _ddb_number(raw["price"]),
                "stockQty":    _ddb_number(raw.get("stockQty", 0)),
                "isSpecial":   _ddb_bool(bool(raw.get("isSpecial", False))),
            }

            # imageUrl: omit or set to NULL (don't pass "null" as a literal string)
            image_url = raw.get("imageUrl")
            if image_url and image_url != "null":
                put_item["imageUrl"] = _ddb_string(str(image_url))
            else:
                put_item["imageUrl"] = {"NULL": True}

            transact_items.append({
                "Put": {
                    "TableName": TABLE_NAME,
                    "Item": put_item,
                    "ConditionExpression": "attribute_not_exists(menuId) AND attribute_not_exists(itemId)"
                }
            })

        # Debug log (CloudWatch)
        print(f"TransactWriteItems count: {len(transact_items)}")

        # Write all rows atomically (max 25 ops per call)
        dynamodb.transact_write_items(TransactItems=transact_items)

        return _resp(201, {
            "menuId": menu_id,
            "status": "updated",
            "date": menu_date,
            "itemsCreated": len(menu_items)
        })

    except ClientError as e:
        # Surface cancellation reasons if present
        reasons = (e.response or {}).get("CancellationReasons")
        print(f"ClientError: {str(e)}")
        if reasons:
            try:
                print(f"CancellationReasons: {json.dumps(reasons)}")
            except Exception:
                print("CancellationReasons present but could not serialize.")
        return _resp(500, {"error": "DynamoDB error", "detail": str(e), "cancellationReasons": reasons})
    except Exception as e:
        print(f"Unhandled error: {str(e)}")
        return _resp(500, {"error": str(e)})

def _resp(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }
