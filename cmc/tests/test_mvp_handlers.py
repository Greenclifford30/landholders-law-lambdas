import importlib.util
import json
import os
import sys
import types
import unittest
from decimal import Decimal
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


class FakeTypeSerializer:
    def serialize(self, value):
        self._reject_float(value)
        return value

    def _reject_float(self, value):
        if isinstance(value, float):
            raise TypeError("Float types are not supported. Use Decimal types instead.")
        if isinstance(value, dict):
            for nested_value in value.values():
                self._reject_float(nested_value)
        if isinstance(value, list):
            for nested_value in value:
                self._reject_float(nested_value)


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
        self.fail_transact = False

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["PK"], Item["SK"])
        if ConditionExpression and key in self.items:
            raise FakeClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = dict(Item)
        return {}

    def transact_write_items(self, TransactItems):
        if self.fail_transact:
            raise FakeClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                "TransactWriteItems",
            )
        puts = [item["Put"] for item in TransactItems]
        for put in puts:
            item = put["Item"]
            existing = self.items.get((item["PK"], item["SK"]))
            condition = put.get("ConditionExpression")
            if condition and not self._condition_matches(condition, existing, put):
                raise FakeClientError(
                    {"Error": {"Code": "TransactionCanceledException", "Message": "condition failed"}},
                    "TransactWriteItems",
                )
        for put in puts:
            item = put["Item"]
            self.items[(item["PK"], item["SK"])] = dict(item)
        return {}

    def _condition_matches(self, condition, existing, put):
        if condition == "attribute_not_exists(PK) AND attribute_not_exists(SK)":
            return existing is None
        if condition == "attribute_not_exists(PK) OR NOT (#status IN (:planning, :voting, :confirmed))":
            if existing is None:
                return True
            names = put.get("ExpressionAttributeNames") or {}
            values = put.get("ExpressionAttributeValues") or {}
            status_attr = names.get("#status", "status")
            active_statuses = {values[":planning"], values[":voting"], values[":confirmed"]}
            return existing.get(status_attr) not in active_statuses
        return True

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


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake-message"}


class FakeDynamo:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


class FakeDynamoClient:
    def __init__(self, table):
        self.table = table

    def transact_write_items(self, TransactItems):
        return self.table.transact_write_items(TransactItems)


class FakeSecrets:
    def get_secret_value(self, SecretId):
        return {"SecretString": '{"access_token":"tmdb-token"}'}


def install_fake_aws(fake_table):
    fake_ses = FakeSes()
    fake_boto3 = types.SimpleNamespace(
        resource=lambda service_name: FakeDynamo(fake_table),
        client=lambda service_name: FakeDynamoClient(fake_table)
        if service_name == "dynamodb"
        else fake_ses
        if service_name == "ses"
        else FakeSecrets(),
    )
    fake_conditions = types.SimpleNamespace(Key=FakeKey)
    fake_types = types.SimpleNamespace(TypeSerializer=FakeTypeSerializer)
    fake_exceptions = types.SimpleNamespace(ClientError=FakeClientError)
    sys.modules["boto3"] = fake_boto3
    sys.modules["boto3.dynamodb"] = types.SimpleNamespace(conditions=fake_conditions)
    sys.modules["boto3.dynamodb.conditions"] = fake_conditions
    sys.modules["boto3.dynamodb.types"] = fake_types
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


def event(method="GET", path=None, body=None, user_id="user-1", club_id=None, movie_night_id=None, query=None, groups="Admin"):
    path_params = {}
    if club_id:
        path_params["clubId"] = club_id
    if movie_night_id:
        path_params["movieNightId"] = movie_night_id
    if path and "/invites/" in path:
        parts = [part for part in path.split("/") if part]
        path_params["token"] = parts[1]
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
                    "cognito:groups": groups,
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
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "META", "clubId": "club-1", "name": "Club One"})
        self.table.put_item(
            Item={
                "PK": "CLUB#club-1",
                "SK": "MEMBER#user-1",
                "GSI1PK": "USER#user-1",
                "GSI1SK": "CLUB#club-1",
                "clubId": "club-1",
                "userId": "user-1",
                "email": "user-1@example.com",
                "role": "admin",
                "status": "active",
            }
        )
        self.table.put_item(
            Item={
                "PK": "CLUB#club-1",
                "SK": "MEMBER#user-2",
                "GSI1PK": "USER#user-2",
                "GSI1SK": "CLUB#club-1",
                "clubId": "club-1",
                "userId": "user-2",
                "email": "user-2@example.com",
                "role": "friend",
                "status": "active",
            }
        )

    def test_platform_admin_can_create_club(self):
        app = load_app("manage-clubs-lambda", self.table)
        result = app.handler(event("POST", body={"name": "Friday Films"}), None)
        self.assertEqual(201, result["statusCode"])
        club_id = body(result)["club"]["clubId"]
        self.assertIn((f"CLUB#{club_id}", "META"), self.table.items)
        self.assertIn((f"CLUB#{club_id}", "MEMBER#user-1"), self.table.items)
        self.assertEqual("admin", self.table.items[(f"CLUB#{club_id}", "MEMBER#user-1")]["role"])

    def test_duplicate_club_id_returns_conflict(self):
        app = load_app("manage-clubs-lambda", self.table)
        result = app.handler(event("POST", body={"name": "Duplicate", "clubId": "club-1"}), None)
        self.assertEqual(409, result["statusCode"])

    def test_non_platform_admin_cannot_create_club(self):
        app = load_app("manage-clubs-lambda", self.table)
        result = app.handler(event("POST", body={"name": "Friday Films"}, user_id="user-2", groups="Friend"), None)
        self.assertEqual(403, result["statusCode"])

    def test_list_clubs_returns_user_memberships(self):
        app = load_app("manage-clubs-lambda", self.table)
        result = app.handler(event(user_id="user-2"), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual(["club-1"], [club["clubId"] for club in body(result)["clubs"]])

    def test_club_admin_can_invite_email(self):
        app = load_app("manage-invites-lambda", self.table)
        result = app.handler(event("POST", club_id="club-1", body={"emails": ["NewUser@example.com"]}), None)
        self.assertEqual(201, result["statusCode"])
        invite = body(result)["invites"][0]
        self.assertEqual("newuser@example.com", invite["email"])
        self.assertNotIn("tokenHash", invite)

    def test_non_admin_cannot_invite_email(self):
        app = load_app("manage-invites-lambda", self.table)
        result = app.handler(event("POST", club_id="club-1", user_id="user-2", body={"emails": ["new@example.com"]}), None)
        self.assertEqual(403, result["statusCode"])

    def test_accept_invite_creates_friend_membership(self):
        app = load_app("manage-invites-lambda", self.table)
        created = app.handler(event("POST", club_id="club-1", body={"emails": ["joiner@example.com"]}), None)
        token = body(created)["invites"][0]["inviteUrl"].rsplit("/", 1)[-1]
        accepted = app.handler(event("POST", path=f"/invites/{token}", user_id="joiner", body={}), None)
        self.assertEqual(200, accepted["statusCode"])
        self.assertEqual("friend", self.table.items[("CLUB#club-1", "MEMBER#joiner")]["role"])

    def test_accept_invite_rejects_wrong_email(self):
        app = load_app("manage-invites-lambda", self.table)
        created = app.handler(event("POST", club_id="club-1", body={"emails": ["joiner@example.com"]}), None)
        token = body(created)["invites"][0]["inviteUrl"].rsplit("/", 1)[-1]
        accepted = app.handler(event("POST", path=f"/invites/{token}", user_id="someone-else", body={}), None)
        self.assertEqual(403, accepted["statusCode"])

    def test_list_invites_returns_pending_invites(self):
        app = load_app("manage-invites-lambda", self.table)
        app.handler(event("POST", club_id="club-1", body={"emails": ["pending@example.com"]}), None)
        result = app.handler(event("GET", club_id="club-1"), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual(["pending@example.com"], [invite["email"] for invite in body(result)["invites"]])

    def test_movie_search_returns_normalized_tmdb_results(self):
        app = load_app("movie-search-lambda", self.table)
        with patch.object(app.requests, "get") as fake_get:
            fake_get.return_value.status_code = 200
            fake_get.return_value.json.return_value = {"results": [{"id": 1, "title": "Heat", "release_date": "1995-12-15"}]}
            result = app.handler(event(query={"query": "Heat"}), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual("tmdb", body(result)["results"][0]["provider"])

    def test_movie_search_requires_two_character_query(self):
        app = load_app("movie-search-lambda", self.table)
        result = app.handler(event(query={"query": "H"}), None)
        self.assertEqual(400, result["statusCode"])

    def test_now_playing_returns_normalized_tmdb_results(self):
        app = load_app("movie-search-lambda", self.table)
        with patch.object(app.requests, "get") as fake_get:
            fake_get.return_value.status_code = 200
            fake_get.return_value.json.return_value = {"results": [{"id": 2, "title": "Sinners", "release_date": "2025-04-18"}]}
            result = app.handler(event(path="/movies/now-playing", query={"page": "2"}), None)
        self.assertEqual(200, result["statusCode"])
        self.assertEqual("tmdb", body(result)["results"][0]["provider"])
        self.assertEqual("/movie/now_playing", fake_get.call_args.args[0].rsplit("/3", 1)[1])
        self.assertEqual("2", fake_get.call_args.kwargs["params"]["page"])

    def test_create_movie_night_requires_admin_and_creates_active_pointer(self):
        app = load_app("create-movie-night-lambda", self.table)
        result = app.handler(
            event(
                "POST",
                club_id="club-1",
                body={
                    "targetDate": "2026-06-01",
                    "movie": {"externalId": "1", "title": "Heat", "rating": 8.5, "popularity": 123.4},
                },
            ),
            None,
        )
        self.assertEqual(201, result["statusCode"])
        movie_night_id = body(result)["movieNight"]["movieNightId"]
        self.assertIn(("CLUB#club-1", "ACTIVE_MOVIE_NIGHT"), self.table.items)
        self.assertEqual(movie_night_id, self.table.items[("CLUB#club-1", "ACTIVE_MOVIE_NIGHT")]["movieNightId"])
        stored_movie = self.table.items[("CLUB#club-1", f"MOVIE_NIGHT#{movie_night_id}")]["movie"]
        self.assertEqual(Decimal("8.5"), stored_movie["rating"])
        self.assertEqual(Decimal("123.4"), stored_movie["popularity"])

    def test_create_movie_night_duplicate_id_returns_conflict(self):
        self.table.put_item(
            Item={
                "PK": "CLUB#club-1",
                "SK": "MOVIE_NIGHT#mn-duplicate",
                "movieNightId": "mn-duplicate",
            }
        )
        app = load_app("create-movie-night-lambda", self.table)
        result = app.handler(
            event(
                "POST",
                club_id="club-1",
                body={
                    "movieNightId": "mn-duplicate",
                    "targetDate": "2026-06-01",
                    "movie": {"externalId": "1", "title": "Heat"},
                },
            ),
            None,
        )
        self.assertEqual(409, result["statusCode"])
        self.assertNotIn(("CLUB#club-1", "ACTIVE_MOVIE_NIGHT"), self.table.items)

    def test_create_movie_night_existing_active_pointer_returns_conflict(self):
        self.table.put_item(
            Item={
                "PK": "CLUB#club-1",
                "SK": "ACTIVE_MOVIE_NIGHT",
                "movieNightId": "mn-active",
                "status": "planning",
            }
        )
        app = load_app("create-movie-night-lambda", self.table)
        result = app.handler(
            event(
                "POST",
                club_id="club-1",
                body={
                    "movieNightId": "mn-new",
                    "targetDate": "2026-06-01",
                    "movie": {"externalId": "1", "title": "Heat"},
                },
            ),
            None,
        )
        self.assertEqual(409, result["statusCode"])
        self.assertNotIn(("CLUB#club-1", "MOVIE_NIGHT#mn-new"), self.table.items)
        self.assertEqual("mn-active", self.table.items[("CLUB#club-1", "ACTIVE_MOVIE_NIGHT")]["movieNightId"])

    def test_create_movie_night_transaction_failure_does_not_leave_partial_records(self):
        self.table.fail_transact = True
        app = load_app("create-movie-night-lambda", self.table)
        with self.assertLogs("cmc_shared", level="ERROR"):
            result = app.handler(
                event(
                    "POST",
                    club_id="club-1",
                    body={
                        "movieNightId": "mn-failed",
                        "targetDate": "2026-06-01",
                        "movie": {"externalId": "1", "title": "Heat"},
                    },
                ),
                None,
            )
        self.assertEqual(500, result["statusCode"])
        self.assertNotIn(("CLUB#club-1", "MOVIE_NIGHT#mn-failed"), self.table.items)
        self.assertNotIn(("CLUB#club-1", "ACTIVE_MOVIE_NIGHT"), self.table.items)

    def test_shared_handler_logs_client_error_without_leaking_details(self):
        load_app("create-movie-night-lambda", self.table)
        cmc_shared = sys.modules["cmc_shared"]

        def failing_handler(_event, _context):
            raise FakeClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "secret detail"}},
                "PutItem",
            )

        wrapped = cmc_shared.handle(failing_handler)
        with self.assertLogs("cmc_shared", level="ERROR") as logs:
            result = wrapped({}, None)

        self.assertEqual(500, result["statusCode"])
        self.assertEqual({"error": "AWS service request failed."}, body(result))
        self.assertIn("AccessDeniedException", "\n".join(logs.output))
        self.assertNotIn("secret detail", body(result)["error"])

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

    def seed_cached_showtime(self):
        key = {
            "PK": "SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#60422#DATE#2026-06-05",
            "SK": "MOVIE#MV0123456789#THEATER#999#START#2026-06-05T19:30:00#FORMAT#abc",
        }
        self.table.put_item(
            Item={
                **key,
                "provider": "gracenote",
                "tmsId": "MV0123456789",
                "rootId": "12345",
                "title": "Heat",
                "theatreId": "999",
                "theatreName": "Music Box Theatre",
                "theatreLocation": "3733 N Southport Ave",
                "startsAtUtc": "2026-06-06T00:30:00Z",
                "localDateTime": "2026-06-05T19:30:00",
                "screenFormat": "70mm",
                "ticketURI": "https://tickets.example",
                "quals": ["70mm"],
            }
        )
        return key

    def test_manage_showtimes_imports_cached_showtime(self):
        self.seed_movie_night("planning")
        cache_key = self.seed_cached_showtime()
        app = load_app("manage-showtimes-lambda", self.table)
        result = app.handler(event("POST", movie_night_id="mn-1", body={"cachedShowtimeKeys": [cache_key]}), None)

        self.assertEqual(201, result["statusCode"])
        imported = body(result)["showtimes"][0]
        self.assertEqual("Music Box Theatre", imported["theaterName"])
        self.assertEqual("2026-06-06T00:30:00Z", imported["startsAtUtc"])
        self.assertEqual("MV0123456789", imported["providerMovieId"])
        self.assertEqual("999", imported["providerTheaterId"])
        self.assertEqual("70mm", imported["screenFormat"])
        self.assertEqual("https://tickets.example", imported["ticketURI"])
        self.assertEqual(["70mm"], imported["quals"])
        self.assertIn(("MOVIE_NIGHT#mn-1", f"SHOWTIME#{imported['showtimeId']}"), self.table.items)

    def test_manage_showtimes_cached_import_is_idempotent(self):
        self.seed_movie_night("planning")
        cache_key = self.seed_cached_showtime()
        app = load_app("manage-showtimes-lambda", self.table)
        first = app.handler(event("POST", movie_night_id="mn-1", body={"cachedShowtimeKeys": [cache_key]}), None)
        second = app.handler(event("POST", movie_night_id="mn-1", body={"cachedShowtimeKeys": [cache_key]}), None)

        first_id = body(first)["showtimes"][0]["showtimeId"]
        second_id = body(second)["showtimes"][0]["showtimeId"]
        self.assertEqual(first_id, second_id)
        imported_keys = [key for key in self.table.items if key[0] == "MOVIE_NIGHT#mn-1" and key[1].startswith("SHOWTIME#")]
        self.assertEqual(1, len(imported_keys))

    def test_manage_showtimes_cached_import_rejects_missing_key(self):
        self.seed_movie_night("planning")
        app = load_app("manage-showtimes-lambda", self.table)
        result = app.handler(
            event(
                "POST",
                movie_night_id="mn-1",
                body={"cachedShowtimeKeys": [{"PK": "SHOWTIME_CACHE#missing", "SK": "MOVIE#missing"}]},
            ),
            None,
        )

        self.assertEqual(404, result["statusCode"])

    def test_manage_showtimes_cached_import_rejects_malformed_key(self):
        self.seed_movie_night("planning")
        app = load_app("manage-showtimes-lambda", self.table)
        result = app.handler(event("POST", movie_night_id="mn-1", body={"cachedShowtimeKeys": [{"PK": "SHOWTIME_CACHE#missing"}]}), None)

        self.assertEqual(400, result["statusCode"])

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
