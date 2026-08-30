from boto3.dynamodb.conditions import Key

from cmc_shared import ApiError, claims, get_item, handle, now_iso, path_param, put_item, response, table


def public_notification(item):
    return {key: value for key, value in item.items() if key not in {"PK", "SK", "GSI1PK", "GSI1SK", "emailStatus", "emailError"}}


@handle
def handler(event, context):
    user = claims(event)
    method = (event.get("httpMethod") or "GET").upper()
    notification_id = (event.get("pathParameters") or {}).get("notificationId")
    if method == "GET":
        result = table().query(KeyConditionExpression=Key("PK").eq(f"USER#{user['userId']}") & Key("SK").begins_with("NOTIFICATION#"), ScanIndexForward=False)
        items = result.get("Items", [])
        return response(200, {"notifications": [public_notification(item) for item in items], "unreadCount": sum(1 for item in items if not item.get("readAt"))})
    if method == "POST" and notification_id == "read-all":
        items = table().query(KeyConditionExpression=Key("PK").eq(f"USER#{user['userId']}") & Key("SK").begins_with("NOTIFICATION#")).get("Items", [])
        read_at = now_iso()
        for item in items:
            if not item.get("readAt"):
                table().update_item(Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression="SET readAt = :readAt", ExpressionAttributeValues={":readAt": read_at})
        return response(200, {"readAt": read_at})
    if method == "POST" and notification_id:
        item = get_item(f"USER#{user['userId']}", f"NOTIFICATION#{notification_id}")
        if not item:
            raise ApiError(404, "Notification not found.")
        read_at = item.get("readAt") or now_iso()
        table().update_item(Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression="SET readAt = :readAt", ExpressionAttributeValues={":readAt": read_at})
        item["readAt"] = read_at
        return response(200, {"notification": public_notification(item)})
    raise ApiError(405, "Method not allowed.")
