"""Behavior and interleaving tests for proposals and independent movie nights."""
import copy
import json
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

if __package__:
    from .test_mvp_handlers import FakeTable, load_app, event, body
else:
    from test_mvp_handlers import FakeTable, load_app, event, body


class ConcurrentTable(FakeTable):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()

    def transact_write_items(self, *args, **kwargs):
        with self.lock:
            return super().transact_write_items(*args, **kwargs)

    def query(self, **kwargs):
        with self.lock:
            return copy.deepcopy(super().query(**kwargs))

    def get_item(self, **kwargs):
        with self.lock:
            return copy.deepcopy(super().get_item(**kwargs))


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        os.environ["APP_TABLE_NAME"] = "test-table"
        self.table = ConcurrentTable()
        for user, role in (("user-1", "admin"), ("user-2", "friend"), ("user-3", "friend"), ("guest", "guest")):
            self.table.put_item(Item={"PK": "CLUB#club-1", "SK": f"MEMBER#{user}", "userId": user, "role": role, "status": "active", "name": user, "email": "private@example.com"})
        self.app = load_app("manage-movie-proposals-lambda", self.table)
        self.service = self.app.proposals
        self.movie = {"provider": "tmdb", "externalId": "1", "title": "Future film", "releaseDate": "2099-01-01", "rating": 8.5}
        self.provider = patch.object(self.service, "resolve_movie", return_value=self.movie)
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def call(self, method="GET", identifier=None, suffix="", payload=None, user="user-1", club="club-1", query=None):
        request = event(method, path=f"/clubs/{club}/movie-proposals" + (f"/{identifier}" if identifier else "") + suffix,
                        club_id=club, user_id=user, body=payload, query=query)
        if identifier:
            request["pathParameters"]["proposalId"] = identifier
        return self.app.handler(request, None)

    def create(self, user="user-1"):
        result = self.call("POST", payload={"provider": "tmdb", "externalId": "1", "reason": "Let's watch"}, user=user)
        self.assertEqual(201, result["statusCode"], result)
        return body(result)["proposal"]

    def schedule_input(self, version=1, key="retry-key"):
        return {"targetDate": "2099-01-01", "version": version, "idempotencyKey": key}

    def records(self, prefix):
        return [v for (_, sk), v in self.table.items.items() if sk.startswith(prefix)]

    def test_duplicate_creation_and_concurrent_submission(self):
        barrier = threading.Barrier(2)
        def provider(*args):
            barrier.wait(timeout=5)
            return self.movie
        with patch.object(self.service, "resolve_movie", side_effect=provider), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda user: self.call("POST", payload={"provider": "tmdb", "externalId": "1"}, user=user), ["user-1", "user-2"]))
        self.assertEqual([201, 409], sorted(r["statusCode"] for r in results))
        identifier = next(body(r)["proposal"]["proposalId"] for r in results if r["statusCode"] == 201)
        self.assertEqual(identifier, next(body(r)["existingProposalId"] for r in results if r["statusCode"] == 409))
        self.assertEqual(1, len(self.records("PROPOSAL#")))
        self.assertEqual(1, len(self.records("OPEN_FILM#")))

    def test_member_permissions_and_viewer_fields(self):
        suggestion = self.create("user-2")
        identifier = suggestion["proposalId"]
        self.assertTrue(suggestion["viewerCanWithdraw"])
        listed = body(self.call())["proposals"][0]
        self.assertFalse(listed["viewerCanWithdraw"])
        for user, club in (("guest", "club-1"), ("outsider", "club-1"), ("user-1", "another-club")):
            self.assertEqual(403, self.call(user=user, club=club)["statusCode"])
        self.assertEqual(403, self.call("PATCH", identifier, payload={"version": 1, "reason": "admin rewrite", "viewerCanWithdraw": True})["statusCode"])
        self.assertEqual(404, self.call("PATCH", "missing", payload={"version": 1})["statusCode"])
        self.assertNotIn("private@example.com", json.dumps(listed))

    def test_endorsement_retries_concurrency_and_departed_members(self):
        identifier = self.create()["proposalId"]
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda user: self.call("PUT", identifier, "/endorsement", user=user), ["user-2", "user-3"]))
        self.assertEqual([200, 200], [r["statusCode"] for r in results])
        for _ in range(2):
            result = self.call("PUT", identifier, "/endorsement", user="user-2")
            self.assertEqual(2, body(result)["proposal"]["endorsementCount"])
        self.table.items[("CLUB#club-1", "MEMBER#user-3")]["status"] = "removed"
        self.assertEqual(1, body(self.call())["proposals"][0]["endorsementCount"])
        self.assertEqual(403, self.call("PUT", identifier, "/endorsement", user="user-3")["statusCode"])
        for _ in range(2):
            result = self.call("DELETE", identifier, "/endorsement", user="user-2")
            self.assertEqual(0, body(result)["proposal"]["endorsementCount"])

    def test_edit_withdraw_dismiss_and_repropose(self):
        identifier = self.create("user-2")["proposalId"]
        edited = self.call("PATCH", identifier, payload={"version": 1, "reason": "New reason"}, user="user-2")
        self.assertEqual("New reason", body(edited)["proposal"]["reason"])
        self.assertEqual(409, self.call("PATCH", identifier, payload={"version": 1, "status": "withdrawn"}, user="user-2")["statusCode"])
        self.assertEqual(400, self.call("PATCH", identifier, payload={"version": 2, "status": "dismissed"})["statusCode"])
        self.assertEqual(403, self.call("PATCH", identifier, payload={"version": 2, "status": "dismissed", "moderationReason": "No"}, user="user-2")["statusCode"])
        dismissed = self.call("PATCH", identifier, payload={"version": 2, "status": "dismissed", "moderationReason": "Not suitable"})
        self.assertEqual("user-1", body(dismissed)["proposal"]["moderatedByUserId"])
        self.assertEqual(409, self.call("PUT", identifier, "/endorsement")["statusCode"])
        new = self.create("user-2")
        withdrawn = self.call("PATCH", new["proposalId"], payload={"version": 1, "status": "withdrawn"}, user="user-2")
        self.assertEqual("withdrawn", body(withdrawn)["proposal"]["status"])
        self.assertEqual([], self.records("OPEN_FILM#"))
        self.create()

    def test_membership_revocation_during_provider_request_is_atomic(self):
        def revoke(*args):
            self.table.items[("CLUB#club-1", "MEMBER#user-1")]["status"] = "removed"
            return self.movie
        with patch.object(self.service, "resolve_movie", side_effect=revoke):
            result = self.call("POST", payload={"provider": "tmdb", "externalId": "1"})
        self.assertEqual(409, result["statusCode"])
        self.assertEqual([], self.records("PROPOSAL#"))
        self.assertEqual([], self.records("OPEN_FILM#"))

    def test_scheduling_retry_and_state_are_atomic(self):
        identifier = self.create("user-2")["proposalId"]
        payload = self.schedule_input()
        result = self.call("POST", identifier, "/schedule", payload)
        self.assertEqual(200, result["statusCode"], result)
        night = body(result)["movieNight"]
        self.assertEqual(identifier, night["proposalId"])
        self.assertEqual("user-2", night["proposedByUserId"])
        self.assertEqual(night, body(self.call("POST", identifier, "/schedule", payload))["movieNight"])
        self.assertEqual(1, len(self.records("MOVIE_NIGHT#")))
        self.assertEqual(1, len(self.records("CHECK#")))
        self.assertEqual([], self.records("OPEN_FILM#"))
        self.assertEqual(409, self.call("POST", identifier, "/schedule", {**payload, "targetDate": "2099-01-02"})["statusCode"])
        self.assertEqual(409, self.call("POST", identifier, "/schedule", self.schedule_input(key="different"))["statusCode"])
        self.table.items[("CLUB#club-1", "MEMBER#user-1")]["status"] = "removed"
        self.assertEqual(403, self.call("POST", identifier, "/schedule", payload)["statusCode"])

    def test_scheduling_concurrent_hosts_produces_one_night(self):
        identifier = self.create()["proposalId"]
        stale = self.service.load("club-1", identifier)
        member = self.table.get_item(Key={"PK": "CLUB#club-1", "SK": "MEMBER#user-1"})["Item"]
        barrier = threading.Barrier(2)
        real_build = self.service.build_night
        def build(*args):
            result = real_build(*args)
            barrier.wait(timeout=5)
            return result
        with patch.object(self.service, "build_night", side_effect=build), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.service.schedule, stale, {"userId": "user-1"}, member, self.schedule_input()) for _ in range(2)]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(results[0]["movieNight"]["movieNightId"], results[1]["movieNight"]["movieNightId"])
        self.assertEqual(1, len(self.records("MOVIE_NIGHT#")))
        self.assertEqual(1, len(self.records("CHECK#")))

    def test_different_admins_cannot_schedule_twice_with_different_keys(self):
        identifier = self.create()["proposalId"]
        self.table.items[("CLUB#club-1", "MEMBER#user-2")]["role"] = "admin"
        barrier = threading.Barrier(2)
        build = self.service.build_night
        def interleaved(*args):
            result = build(*args)
            barrier.wait(timeout=5)
            return result
        with patch.object(self.service, "build_night", side_effect=interleaved), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda user: self.call("POST", identifier, "/schedule", self.schedule_input(key=user), user=user), ["user-1", "user-2"]))
        self.assertEqual([200, 409], sorted(result["statusCode"] for result in results))
        self.assertEqual(1, len(self.records("MOVIE_NIGHT#")))
        self.assertEqual(1, len(self.records("CHECK#")))
        self.assertEqual(1, len(self.records("SCHEDULE#")))

    def test_failed_scheduling_has_no_partial_writes(self):
        identifier = self.create()["proposalId"]
        self.table.fail_transact = True
        with self.assertLogs("cmc_shared", level="ERROR"):
            result = self.call("POST", identifier, "/schedule", self.schedule_input())
        self.assertEqual(500, result["statusCode"])
        self.assertEqual([], self.records("MOVIE_NIGHT#"))
        self.assertEqual([], self.records("CHECK#"))
        self.assertEqual([], self.records("SCHEDULE#"))
        self.assertEqual("open", self.records("PROPOSAL#")[0]["status"])
        self.assertEqual(1, len(self.records("OPEN_FILM#")))

    def test_schedule_permissions_and_validation(self):
        identifier = self.create()["proposalId"]
        self.assertEqual(403, self.call("POST", identifier, "/schedule", self.schedule_input(), user="user-2")["statusCode"])
        for payload in ({"version": 1}, self.schedule_input(version=True), self.schedule_input(version=0)):
            self.assertEqual(400, self.call("POST", identifier, "/schedule", payload)["statusCode"])
        self.assertEqual(409, self.call("POST", identifier, "/schedule", self.schedule_input(version=2))["statusCode"])
        self.assertEqual(400, self.call("PATCH", identifier, payload={"version": 1, "reason": "x" * 1001})["statusCode"])
        self.assertEqual(400, self.call("PATCH", identifier, payload={"version": 1, "status": "scheduled"})["statusCode"])

    def test_pagination_with_ties_and_bad_cursors(self):
        for index in range(3):
            self.movie = {**self.movie, "externalId": str(index + 1)}
            with patch.object(self.service, "resolve_movie", return_value=self.movie):
                self.create()
        first = body(self.call(query={"limit": "2"}))
        second = body(self.call(query={"limit": "2", "cursor": first["nextCursor"]}))
        ids = [p["proposalId"] for p in first["proposals"] + second["proposals"]]
        self.assertEqual(3, len(set(ids)))
        self.assertIsNone(second["nextCursor"])
        for query in ({"cursor": "bad"}, {"limit": "0"}, {"limit": "101"}, {"status": "invalid"}, {"status": "scheduled", "cursor": first["nextCursor"]}):
            self.assertEqual(400, self.call(query=query)["statusCode"])

    def test_provider_failure_returns_no_partial_records(self):
        with patch.object(self.service, "resolve_movie", side_effect=sys.modules["cmc_shared"].ApiError(502, "Unavailable")):
            result = self.call("POST", payload={"provider": "tmdb", "externalId": "1"})
        self.assertEqual(502, result["statusCode"])
        self.assertEqual([], self.records("PROPOSAL#"))

    def test_provider_validates_identity_and_resolves_details(self):
        movies = sys.modules["cmc_movies"]
        for provider, identifier in (("other", "1"), ("tmdb", "bad"), ("tmdb", True), ("tmdb", 0)):
            with self.assertRaises(sys.modules["cmc_shared"].ApiError) as error:
                movies.resolve_movie(provider, identifier)
            self.assertEqual(400, error.exception.status_code)
        with patch.object(movies, "tmdb_get", return_value={"id": 1, "title": "Provider title", "runtime": 120, "vote_average": 8.5}) as get:
            movie = movies.resolve_movie("tmdb", "0001")
        get.assert_called_once_with("/movie/1", {})
        self.assertEqual("1", movie["externalId"])
        self.assertEqual("Provider title", movie["title"])
        self.assertEqual(120, movie["runtime"])
        with patch.object(movies, "tmdb_get", return_value={"id": 1}):
            with self.assertRaises(sys.modules["cmc_shared"].ApiError) as error:
                movies.resolve_movie("tmdb", "1")
            self.assertEqual(502, error.exception.status_code)

    def test_create_night_idempotency_and_club_isolation(self):
        create = load_app("create-movie-night-lambda", self.table)
        payload = {"targetDate": "2099-01-01", "movie": self.movie, "idempotencyKey": "same-request"}
        first = create.handler(event("POST", club_id="club-1", body=payload), None)
        retry = create.handler(event("POST", club_id="club-1", body=payload), None)
        self.assertEqual(201, first["statusCode"])
        self.assertEqual(200, retry["statusCode"])
        self.assertEqual(body(first)["movieNight"], body(retry)["movieNight"])
        changed = create.handler(event("POST", club_id="club-1", body={**payload, "targetDate": "2099-01-02"}), None)
        self.assertEqual(409, changed["statusCode"])
        listing = load_app("list-movie-nights-lambda", self.table)
        self.assertEqual(403, listing.handler(event(club_id="other-club"), None)["statusCode"])
        self.assertEqual(403, listing.handler(event(club_id="club-1", user_id="guest"), None)["statusCode"])
        self.assertEqual(400, listing.handler(event(club_id="club-1", query={"cursor": "bad"}), None)["statusCode"])
        self.assertEqual(400, listing.handler(event(club_id="club-1", query={"scope": "other"}), None)["statusCode"])

    def test_parallel_nights_detail_listing_and_completion(self):
        create = load_app("create-movie-night-lambda", self.table)
        nights = []
        for day in (3, 1, 2):
            result = create.handler(event("POST", club_id="club-1", body={"targetDate": f"2099-01-0{day}", "movie": self.movie}), None)
            self.assertEqual(201, result["statusCode"])
            nights.append(body(result)["movieNight"])
        def stored(night):
            return self.table.items[("CLUB#club-1", f"MOVIE_NIGHT#{night['movieNightId']}")]
        stored(nights[0])["status"] = "voting"
        stored(nights[2])["status"] = "confirmed"
        stored(nights[2])["confirmedShowtime"] = {"startsAtUtc": "2020-01-01T00:00:00Z"}
        listing = load_app("list-movie-nights-lambda", self.table)
        result = listing.handler(event(club_id="club-1"), None)
        self.assertEqual(["confirmed", "planning", "voting"], [n["status"] for n in body(result)["movieNights"]])
        self.assertEqual(nights[2]["movieNightId"], sys.modules["cmc_shared"].active_pointer("club-1")["movieNightId"])
        detail = listing.handler(event(movie_night_id=nights[0]["movieNightId"], user_id="user-2"), None)
        self.assertEqual(nights[0]["movieNightId"], body(detail)["movieNight"]["movieNightId"])
        complete = load_app("complete-movie-night-lambda", self.table)
        self.assertEqual(200, complete.handler(event("POST", movie_night_id=nights[2]["movieNightId"]), None)["statusCode"])
        self.assertEqual(nights[1]["movieNightId"], sys.modules["cmc_shared"].active_pointer("club-1")["movieNightId"])
        self.assertEqual("voting", stored(nights[0])["status"])
        listing = load_app("list-movie-nights-lambda", self.table)
        self.table.items[("CLUB#club-1", "MEMBER#user-2")]["status"] = "removed"
        self.assertEqual(403, listing.handler(event(movie_night_id=nights[0]["movieNightId"], user_id="user-2"), None)["statusCode"])
        cancel = load_app("cancel-movie-night-lambda", self.table)
        self.assertEqual(200, cancel.handler(event("POST", movie_night_id=nights[0]["movieNightId"]), None)["statusCode"])
        self.assertEqual("planning", stored(nights[1])["status"])


if __name__ == "__main__":
    unittest.main()
