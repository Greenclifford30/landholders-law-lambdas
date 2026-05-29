import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeTable:
    def batch_writer(self, **kwargs):
        return self

    def __enter__(self):
        self.items = []
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def put_item(self, Item):
        self.items.append(Item)


class FakeDynamoResource:
    def __init__(self):
        self.table = FakeTable()

    def Table(self, name):
        return self.table


class FakeSecretsClient:
    def get_secret_value(self, SecretId):
        return {"SecretString": "secret-from-test"}


class FakeClientError(Exception):
    def __init__(self, response, operation_name):
        super().__init__(response)
        self.response = response
        self.operation_name = operation_name


def load_app():
    fake_dynamo = FakeDynamoResource()
    fake_boto3 = types.SimpleNamespace(
        resource=lambda service_name: fake_dynamo,
        client=lambda service_name: FakeSecretsClient(),
    )
    fake_botocore_exceptions = types.SimpleNamespace(ClientError=FakeClientError)

    sys.modules["boto3"] = fake_boto3
    sys.modules["botocore"] = types.SimpleNamespace(exceptions=fake_botocore_exceptions)
    sys.modules["botocore.exceptions"] = fake_botocore_exceptions

    module_path = Path(__file__).with_name("app.py")
    spec = importlib.util.spec_from_file_location("worker_app", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_dynamo


class WorkerTests(unittest.TestCase):
    def setUp(self):
        os.environ.update(
            {
                "APP_TABLE_NAME": "cmc-app",
                "GRACENOTE_SECRET_ARN": "arn:aws:secretsmanager:example",
                "GRACENOTE_BASE_URL": "http://data.tmsapi.com/v1.1",
                "GRACENOTE_DEFAULT_ZIP": "60422",
                "GRACENOTE_DEFAULT_RADIUS": "30",
                "GRACENOTE_DEFAULT_NUM_DAYS": "14",
                "GRACENOTE_UNITS": "mi",
                "GRACENOTE_IMAGE_SIZE": "Md",
                "GRACENOTE_IMAGE_TEXT": "true",
                "MOVIE_CLUB_TIMEZONE": "America/Chicago",
            }
        )
        self.app, self.fake_dynamo = load_app()

    def test_parse_secret_value_accepts_plain_string_and_json(self):
        self.assertEqual(
            "plain-secret",
            self.app.parse_secret_value({"SecretString": "plain-secret"}),
        )
        self.assertEqual(
            "json-secret",
            self.app.parse_secret_value({"SecretString": '{"api_key":"json-secret"}'}),
        )

    def test_normalize_items_builds_cache_keys_and_ttl(self):
        response = [
            {
                "tmsId": "MV0123456789",
                "rootId": "12345",
                "title": "Test Movie",
                "releaseYear": 2026,
                "showtimes": [
                    {
                        "theatre": {"id": "999", "name": "Test Theatre"},
                        "dateTime": "2026-05-28T19:30",
                        "quals": ["IMAX"],
                        "ticketURI": "https://tickets.example",
                    }
                ],
            }
        ]
        message = {
            "zip": "60422",
            "startDate": "2026-05-28",
            "radius": 30,
            "units": "mi",
        }

        items = self.app.normalize_items(response, message)

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual(
            "SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#60422#DATE#2026-05-28",
            item["PK"],
        )
        self.assertTrue(item["SK"].startswith("MOVIE#MV0123456789#THEATER#999#START#"))
        self.assertEqual("MOVIE#GRACENOTE#MV0123456789", item["GSI1PK"])
        self.assertEqual("IMAX", item["screenFormat"])
        self.assertIsInstance(item["expiresAt"], int)

    def test_handler_returns_only_retryable_batch_failures(self):
        records = {
            "Records": [
                {"messageId": "retry", "body": "{}"},
                {"messageId": "drop", "body": "{}"},
                {"messageId": "ok", "body": "{}"},
            ]
        }

        def fake_process_record(record):
            if record["messageId"] == "retry":
                raise self.app.RetryableError("try again")
            if record["messageId"] == "drop":
                raise self.app.NonRetryableError("bad payload")

        with patch.object(self.app, "process_record", side_effect=fake_process_record):
            result = self.app.handler(records, None)

        self.assertEqual({"batchItemFailures": [{"itemIdentifier": "retry"}]}, result)


if __name__ == "__main__":
    unittest.main()
