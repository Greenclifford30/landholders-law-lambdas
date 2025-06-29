import json
import os
import boto3
import uuid
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.client("dynamodb")

def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        menu_id = body.get("menuId")
        items = body.get("items", [])

        if not menu_id or not items:
            return _response(400, {"error": "menuId and items are required"})

        pk = f"MENU#{menu_id}"
        transact_items = []

        created_ids = []

        for item in items:
            # Use provided ID or generate a new one
            item_id = item.get("id") or str(uuid.uuid4())
            created_ids.append(item_id)

            item_entry = {
                "PK": {"S": pk},
                "SK": {"S": f"ITEM#{item_id}"},
                "id": {"S": item_id},
                "name": {"S": item["name"]},
                "price": {"N": str(item["price"])},
                "available": {"BOOL": item.get("available", True)},
                "description": {"S": item.get("description", "")},
                "category": {"S": item.get("category", "")},
                "spiceLevel": {"N": str(item.get("spiceLevel", 0))},
                "isSpecial": {"BOOL": item.get("isSpecial", False)},
                "imageUrl": {"S": item.get("imageUrl", "")},
                "entityType": {"S": "MENU_ITEM"}
            }

            transact_items.append({
                "Put": {
                    "TableName": TABLE_NAME,
                    "Item": item_entry,
                    "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                }
            })

        # Perform the DB transaction
        dynamodb.transact_write_items(TransactItems=transact_items)

        return _response(200, {
            "message": "Menu items added successfully",
            "itemIds": created_ids
        })

    except ClientError as e:
        # Likely a conditional check failure (duplicate)
        print("DynamoDB Error:", e.response["Error"])
        return _response(400, {"error": e.response["Error"]["Message"]})
    except Exception as e:
        print("Unhandled Exception:", str(e))
        return _response(500, {"error": str(e)})

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }
