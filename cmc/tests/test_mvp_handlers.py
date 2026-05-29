import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


CMC_DIR = Path(__file__).resolve().parents[1]


class FakeClientError(Exception):
    def __init__(self, response, operation_name):
        super().__init__(response)
        self.response = response
        self.operation_name = operation_name


class KeyExpression:
    def __init__(self, conditions):
        self.conditions = conditions

    def __and__(self, other):
        return KeyExpression(self.conditions + other.conditions)


class FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return KeyExpression([(self.name, "eq", value)])

    def begins_with(self, value):
        return KeyExpression([(self.name, "begins_with", value)])


class FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def put_item(self, Item):
        self.table.put_item(Item=Item)


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["PK"], Item["SK"])
        if ConditionExpression and key in self.items:
            raise FakeClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = dict(Item)
        return {}

    def get_item(self, Key):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, ExpressionAttributeValues, ExpressionAttributeNames=None, **kwargs):
        item = self.items[(Key["PK"], Key["SK"])]
        names = ExpressionAttributeNames or {}
        for placeholder, value in ExpressionAttributeValues.items():
            if placeholder.startswith(":"):
                continue
        update_expr = kwargs.get("UpdateExpression", "")
        assignments = update_expr.replace("SET ", "").split(", ")
        for assignment in assignments:
            if not assignment:
                continue
            left, right = assignment.split(" = ")
            attr = names.get(left, left)
            item[attr] = ExpressionAttributeValues[right]
        return {"Attributes": dict(item)}

    def query(self, KeyConditionExpression, **kwargs):
        conditions = getattr(KeyConditionExpression, "conditions", [])
        matched = []
        for item in self.items.values():
            ok = True
            for attr, op, value in conditions:
                if op == "eq" and item.get(attr) != value:
                    ok = False
                if op == "begins_with" and not str(item.get(attr, "")).startswith(value):
                    ok = False
            if ok:
                matched.append(dict(item))
        return {"Items": matched[: kwargs.get("Limit") or len(matched)]}

    def batch_writer(self, **kwargs):
        return FakeBatch(self)


class FakeDynamo:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


class FakeSecrets:
    def get_secret_value(self, SecretId):
        return {"SecretString": '{"access_token":"tmdb-token"}'}


def install_fake_aws(fake_table):
    fake_boto3 = types.SimpleNamespace(
        resource=lambda service_name: FakeDynamo(fake_table),
        client=lambda service_name: FakeSecrets(),
    )
    fake_conditions = types.SimpleNamespace(Key=FakeKey)
    fake_exceptions = types.SimpleNamespace(ClientError=FakeClientError)
    sys.modules["boto3"] = fake_boto3
    sys.modules["boto3.dynamodb"] = types.SimpleNamespace(conditions=fake_conditions)
    sys.modules["boto3.dynamodb.conditions"] = fake_conditions
    sys.modules["botocore"] = types.SimpleNamespace(exceptions=fake_exceptions)
    sys.modules["botocore.exceptions"] = fake_exceptions
    sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))


def load_app(lambda_dir, fake_table):
    install_fake_aws(fake_table)
    sys.modules.pop("cmc_shared", None)
    sys.path.insert(0, str(CMC_DIR / "shared"))
    module_path = CMC_DIR / lambda_dir / "app.py"
    spec = importlib.util.spec_from_file_location(lambda_dir.replace("-", "_"), module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(method="GET", path=None, body=None, user_id="user-1", club_id=None, movie_night_id=None, query=None):
    path_params = {}
    if club_id:
        path_params["clubId"] = club_id
    if movie_night_id:
        path_params["movieNightId"] = movie_night_id
    return {
        "httpMethod": method,
        "path": path or "/",
        "pathParameters": path_params,
        "queryStringParameters": query or {},
        "body": json.dumps(body or {}),
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                    "email": f"{user_id}@example.com",
                    "cognito:groups": "Admin",
                }
            }
        },
    }


def body(result):
    return json.loads(result["body"])


class MvpHandlerTests(unittest.TestCase):
    def setUp(self):
        os.environ["APP_TABLE_NAME"] = "cmc_app"
        os.environ["TMDB_SECRET_ARN"] = "arn:aws:secretsmanager:tmdb"
        self.table = FakeTable()
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "MEMBER#user-1", "role": "admin"})
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "MEMBER#user-2", "role": "friend"})

    def test_movie_search_returns_normalized_tmdb_results(self):
        app = load_app("movie-search-lambda", self.table)
        with patch.object(app.requests, "get") as fake_get:
            fake_get.return_value.status_code = 200
            fake_get.return_value.json.return_value = {"results": [{"id": 1, "title": "Heat", "release_date": "1995-12-15"}]}
            result = app.handler(event(query={"query": "Heat"}), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual("tmdb", body(result)["results"][0]["provider"])

    def test_create_movie_night_requires_admin_and_creates_active_pointer(self):
        app = load_app("create-movie-night-lambda", self.table)
        result = app.handler(
            event(
                "POST",
                club_id="club-1",
                body={"targetDate": "2026-06-01", "movie": {"externalId": "1", "title": "Heat"}},
            ),
            None,
        )
        self.assertEqual(201, result["statusCode"])
        movie_night_id = body(result)["movieNight"]["movieNightId"]
        self.assertIn(("CLUB#club-1", "ACTIVE_MOVIE_NIGHT"), self.table.items)
        self.assertEqual(movie_night_id, self.table.items[("CLUB#club-1", "ACTIVE_MOVIE_NIGHT")]["movieNightId"])

    def test_get_active_movie_night_returns_404_when_empty(self):
        app = load_app("get-active-movie-night-lambda", self.table)
        result = app.handler(event(club_id="club-1"), None)
        self.assertEqual(404, result["statusCode"])

    def seed_movie_night(self, status="voting"):
        item = {
            "PK": "CLUB#club-1",
            "SK": "MOVIE_NIGHT#mn-1",
            "GSI1PK": f"CLUB#club-1#STATUS#{status}",
            "GSI1SK": "START#2026-06-01#MOVIE_NIGHT#mn-1",
            "GSI2PK": "MOVIE_NIGHT#mn-1",
            "GSI2SK": "META",
            "clubId": "club-1",
            "movieNightId": "mn-1",
            "status": status,
            "targetDate": "2026-06-01",
            "movie": {"title": "Heat"},
        }
        self.table.put_item(Item=item)
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "ACTIVE_MOVIE_NIGHT", "movieNightId": "mn-1", "status": status})

    def seed_showtime(self):
        self.table.put_item(
            Item={
                "PK": "MOVIE_NIGHT#mn-1",
                "SK": "SHOWTIME#st-1",
                "showtimeId": "st-1",
                "movieNightId": "mn-1",
                "theaterName": "Music Box",
                "startsAtUtc": "2026-06-01T01:00:00Z",
            }
        )

    def test_manage_showtimes_adds_manual_showtime(self):
        self.seed_movie_night("planning")
        app = load_app("manage-showtimes-lambda", self.table)
        result = app.handler(
            event("POST", movie_night_id="mn-1", body={"showtimes": [{"showtimeId": "st-1", "theaterName": "Music Box", "startsAtUtc": "2026-06-01T01:00:00Z"}]}),
            None,
        )
        self.assertEqual(201, result["statusCode"])
        self.assertIn(("MOVIE_NIGHT#mn-1", "SHOWTIME#st-1"), self.table.items)

    def test_submit_vote_rejects_duplicate_rankings(self):
        self.seed_movie_night()
        self.seed_showtime()
        app = load_app("submit-vote-lambda", self.table)
        result = app.handler(event("PUT", movie_night_id="mn-1", body={"rankings": ["st-1", "st-1"]}), None)
        self.assertEqual(400, result["statusCode"])

    def test_vote_results_scores_ranked_votes(self):
        self.seed_movie_night()
        self.seed_showtime()
        self.table.put_item(Item={"PK": "MOVIE_NIGHT#mn-1", "SK": "VOTE#user-1", "rankings": ["st-1"]})
        app = load_app("vote-results-lambda", self.table)
        result = app.handler(event(movie_night_id="mn-1"), None)
        self.assertEqual(3, body(result)["standings"][0]["points"])

    def test_confirm_showtime_sets_confirmed_status(self):
        self.seed_movie_night()
        self.seed_showtime()
        app = load_app("confirm-showtime-lambda", self.table)
        result = app.handler(event("POST", movie_night_id="mn-1", body={"showtimeId": "st-1"}), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual("confirmed", body(result)["status"])

    def test_update_rsvp_requires_confirmed_movie_night(self):
        self.seed_movie_night("confirmed")
        app = load_app("update-rsvp-lambda", self.table)
        result = app.handler(event("PUT", movie_night_id="mn-1", body={"status": "going", "ticketStatus": "purchased"}), None)
        self.assertEqual(200, result["statusCode"])

    def test_list_history_returns_confirmed_nights(self):
        self.seed_movie_night("confirmed")
        app = load_app("list-history-lambda", self.table)
        result = app.handler(event(club_id="club-1"), None)
        self.assertEqual(1, len(body(result)["movieNights"]))


if __name__ == "__main__":
    unittest.main()
