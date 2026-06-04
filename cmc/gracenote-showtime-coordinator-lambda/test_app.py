import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path


class FakeSqs:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "message-1"}


class KeyExpression:
    def __init__(self, conditions):
        self.conditions = conditions


class FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return KeyExpression([(self.name, "eq", value)])


class FakeTable:
    def __init__(self):
        self.items = []
        self.queries = []

    def query(self, KeyConditionExpression, **kwargs):
        self.queries.append((KeyConditionExpression, kwargs))
        conditions = getattr(KeyConditionExpression, "conditions", [])
        matched = []
        for item in self.items:
            ok = True
            for attr, op, value in conditions:
                if op == "eq" and item.get(attr) != value:
                    ok = False
            if ok:
                matched.append(dict(item))
        return {"Items": matched}


class FakeDynamo:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


def load_app():
    fake_sqs = FakeSqs()
    fake_table = FakeTable()
    fake_boto3 = types.SimpleNamespace(
        client=lambda service_name: fake_sqs,
        resource=lambda service_name: FakeDynamo(fake_table),
    )
    fake_conditions = types.SimpleNamespace(Key=FakeKey)
    sys.modules["boto3"] = fake_boto3
    sys.modules["boto3.dynamodb"] = types.SimpleNamespace(conditions=fake_conditions)
    sys.modules["boto3.dynamodb.conditions"] = fake_conditions

    module_path = Path(__file__).with_name("app.py")
    spec = importlib.util.spec_from_file_location("coordinator_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_sqs, fake_table


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        os.environ.update(
            {
                "SHOWTIME_REFRESH_QUEUE_URL": "https://sqs.example/queue",
                "GRACENOTE_DEFAULT_ZIP": "60422",
                "GRACENOTE_DEFAULT_RADIUS": "30",
                "GRACENOTE_DEFAULT_NUM_DAYS": "14",
                "GRACENOTE_UNITS": "mi",
                "MOVIE_CLUB_TIMEZONE": "America/Chicago",
                "APP_TABLE_NAME": "cmc-app",
            }
        )
        self.app, self.fake_sqs, self.fake_table = load_app()

    def test_direct_invoke_enqueues_refresh_message(self):
        result = self.app.handler(
            {
                "source": "manual",
                "provider": "gracenote",
                "zip": "60422",
                "radius": 30,
                "numDays": 14,
                "units": "mi",
                "startDate": "2026-05-28",
            },
            None,
        )

        self.assertTrue(result["success"])
        self.assertEqual(1, len(self.fake_sqs.messages))
        body = json.loads(self.fake_sqs.messages[0]["MessageBody"])
        self.assertEqual("gracenote", body["provider"])
        self.assertEqual("60422", body["zip"])
        self.assertEqual(30, body["radius"])
        self.assertEqual("2026-05-28", body["startDate"])
        self.assertEqual("manual", body["requestedBy"])

    def test_api_gateway_invalid_units_returns_400(self):
        result = self.app.handler(
            {
                "body": json.dumps({"units": "miles"}),
                "requestContext": {
                    "httpMethod": "POST",
                    "resourcePath": "/admin/showtimes/gracenote/refresh",
                },
            },
            None,
        )

        self.assertEqual(400, result["statusCode"])
        self.assertEqual([], self.fake_sqs.messages)

    def test_search_cache_returns_frontend_shaped_showtimes(self):
        self.fake_table.items.append(
            {
                "PK": "SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#60422#DATE#2026-06-05",
                "SK": "MOVIE#MV0123456789#THEATER#999#START#2026-06-05T19:30:00#FORMAT#abc",
                "provider": "gracenote",
                "tmsId": "MV0123456789",
                "rootId": "12345",
                "title": "Mission: Impossible - The Final Reckoning",
                "theatreId": "999",
                "theatreName": "Music Box Theatre",
                "startsAtUtc": "2026-06-06T00:30:00Z",
                "localDateTime": "2026-06-05T19:30:00",
                "screenFormat": "IMAX",
                "ticketURI": "https://tickets.example",
                "quals": ["IMAX"],
                "radius": 30,
                "units": "mi",
            }
        )

        result = self.app.handler(
            {
                "httpMethod": "GET",
                "path": "/admin/showtimes/gracenote/search",
                "queryStringParameters": {
                    "title": "Mission Impossible The Final Reckoning",
                    "zip": "60422",
                    "radius": "30",
                    "numDays": "14",
                    "units": "mi",
                    "startDate": "2026-06-05",
                },
                "requestContext": {
                    "httpMethod": "GET",
                    "resourcePath": "/admin/showtimes/gracenote/search",
                },
            },
            None,
        )

        self.assertEqual(200, result["statusCode"])
        showtimes = json.loads(result["body"])["showtimes"]
        self.assertEqual(1, len(showtimes))
        showtime = showtimes[0]
        self.assertEqual("Music Box Theatre", showtime["theaterName"])
        self.assertEqual("999", showtime["providerTheaterId"])
        self.assertEqual("MV0123456789", showtime["providerMovieId"])
        self.assertEqual("2026-06-06T00:30:00Z", showtime["startsAtUtc"])
        queried_key = self.fake_table.queries[0][0].conditions[0][2]
        self.assertEqual("SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#60422#DATE#2026-06-05", queried_key)

    def test_search_cache_requires_title(self):
        result = self.app.handler(
            {
                "httpMethod": "GET",
                "path": "/admin/showtimes/gracenote/search",
                "queryStringParameters": {"zip": "60422", "radius": "30", "numDays": "14", "units": "mi"},
                "requestContext": {
                    "httpMethod": "GET",
                    "resourcePath": "/admin/showtimes/gracenote/search",
                },
            },
            None,
        )

        self.assertEqual(400, result["statusCode"])


if __name__ == "__main__":
    unittest.main()
