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


def load_app():
    fake_sqs = FakeSqs()
    fake_boto3 = types.SimpleNamespace(client=lambda service_name: fake_sqs)
    sys.modules["boto3"] = fake_boto3

    module_path = Path(__file__).with_name("app.py")
    spec = importlib.util.spec_from_file_location("coordinator_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_sqs


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
            }
        )
        self.app, self.fake_sqs = load_app()

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


if __name__ == "__main__":
    unittest.main()
