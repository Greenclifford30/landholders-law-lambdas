from boto3.dynamodb.conditions import Key

from cmc_shared import HISTORY_STATUSES, claims, handle, path_param, public_movie_night, require_membership, response, sort_by_date, table


def query_status(club_id, status):
    result = table().query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq(f"CLUB#{club_id}#STATUS#{status}"),
        ScanIndexForward=False,
    )
    return result.get("Items", [])


@handle
def handler(event, context):
    club_id = path_param(event, "clubId")
    user = claims(event)
    require_membership(club_id, user["userId"])
    items = []
    for status in HISTORY_STATUSES:
        items.extend(query_status(club_id, status))
    return response(200, {"movieNights": [public_movie_night(item) for item in sort_by_date(items)]})
