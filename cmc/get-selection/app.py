import json
import boto3
import os

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("MOVIE_SHOWTIME_OPTIONS_TABLE", "movie_showtime_options"))

def lambda_handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}
        filter_theater = params.get("theater")  # Optional
        filter_date = params.get("date")        # Optional

        # Scan the entire table (there should only be one record)
        response = table.scan(Limit=1)
        items = response.get("Items", [])
        if not items:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "No showtimes found in table"})
            }

        item = items[0]
        theaters = item.get("theaters", [])

        # Optional theater filter
        if filter_theater:
            theaters = [t for t in theaters if filter_theater.lower() in t["name"].lower()]

        # Optional date filter
        if filter_date:
            for theater in theaters:
                for fmt in theater.get("formats", []):
                    fmt["slots"] = [
                        s for s in fmt.get("slots", [])
                        if s.get("date") == filter_date
                    ]
                theater["formats"] = [f for f in theater["formats"] if f["slots"]]
            theaters = [t for t in theaters if t["formats"]]

        return {
            "statusCode": 200,
            "body": json.dumps({
                "movieId": item["movieId"],
                "movieTitle": item["movieTitle"],
                "showDate": item["showDate"],
                "theaters": theaters
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
