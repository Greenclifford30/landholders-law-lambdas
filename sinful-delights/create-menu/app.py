import json
import os
import boto3
import uuid
from datetime import datetime
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME")
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

        for item in items:
            item_id = item.get("id") or str(uuid.uuid4())
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
                    "ConditionExpression": "attribute_not_exists(PK)"
                }
            })

        dynamodb.transact_write_items(TransactItems=transact_items)

        return _response(200, {"message": "Menu items added successfully"})

    except ClientError as e:
        print("DynamoDB Error:", e.response["Error"])
        return _response(500, {"error": e.response["Error"]["Message"]})
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
