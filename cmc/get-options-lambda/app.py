import json
import boto3
import os
from decimal import Decimal

def clean_decimals(obj):
    if isinstance(obj, list):
        return [clean_decimals(v) for v in obj]
    elif isinstance(obj, dict):
        return {k: clean_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        # return int(v) if v == int(v) else float(v)
        return float(obj)
    else:
        return obj

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("MOVIE_SHOWTIME_OPTIONS_TABLE", "movie_showtime_options"))

def handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}
        filter_theater = params.get("theater")  # Optional
        filter_date = params.get("date")        # Optional

        # Scan the entire table (there should only be one record)
        response = table.scan(Limit=14)
        items = response.get("Items", [])
        if not items:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "No showtimes found in table"})
            }

        all_results = []

        for item in items:
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

            # Only include results with theaters after filtering
            if theaters:
                all_results.append({
                    "movieId": item["movieId"],
                    "movieTitle": item["movieTitle"],
                    "showDate": item["showDate"],
                    "theaters": theaters
                })

        return {
            "statusCode": 200,
            "body": json.dumps(clean_decimals({
                "movieId": item["movieId"],
                "movieTitle": item["movieTitle"],
                "showDate": item["showDate"],
                "theaters": theaters
            }))
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
