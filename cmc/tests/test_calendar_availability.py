import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


CMC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CMC_DIR / "tests"))

from test_mvp_handlers import FakeTable, body, event, load_app  # noqa: E402


class CalendarAvailabilityTests(unittest.TestCase):
    def setUp(self):
        os.environ.update({
            "APP_TABLE_NAME": "cmc_app",
            "GOOGLE_CALENDAR_ENABLED": "true",
            "GOOGLE_CALENDAR_SECRET_ARN": "arn:aws:secretsmanager:google-calendar",
            "GOOGLE_CALENDAR_KMS_KEY_ARN": "arn:aws:kms:key/google-calendar",
            "GOOGLE_CALENDAR_REDIRECT_URIS": "https://movies.example.com/api/google-calendar/callback",
        })
        os.environ.pop("CALENDAR_SYNC_QUEUE_URL", None)
        self.table = FakeTable()
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "META", "clubId": "club-1", "name": "Club One"})
        for user_id, name, share in (("user-1", "Alex", True), ("user-2", "Sam", False)):
            self.table.put_item(Item={
                "PK": "CLUB#club-1",
                "SK": f"MEMBER#{user_id}",
                "GSI1PK": f"USER#{user_id}",
                "GSI1SK": "CLUB#club-1",
                "clubId": "club-1",
                "userId": user_id,
                "name": name,
                "email": f"{user_id}@example.com",
                "role": "admin" if user_id == "user-1" else "friend",
                "status": "active",
                "shareCalendarAvailability": share,
            })

    def seed_night(self, status="planning", voting_deadline=None):
        night = {
            "PK": "CLUB#club-1",
            "SK": "MOVIE_NIGHT#night-1",
            "GSI2PK": "MOVIE_NIGHT#night-1",
            "GSI2SK": "META",
            "entityType": "movieNight",
            "movieNightId": "night-1",
            "clubId": "club-1",
            "status": status,
            "availabilityRevision": 3,
            "movie": {"title": "Heat", "runtime": 120},
        }
        if voting_deadline:
            night["votingClosesAt"] = voting_deadline
        self.table.put_item(Item=night)
        self.table.put_item(Item={
            "PK": "MOVIE_NIGHT#night-1",
            "SK": "SHOWTIME#show-1",
            "showtimeId": "show-1",
            "movieNightId": "night-1",
            "status": "approved",
            "startsAtUtc": "2026-10-27T00:00:00Z",
            "theaterName": "Music Box",
        })
        self.table.put_item(Item={
            "PK": "USER#user-1",
            "SK": "PREFERENCES",
            "timeZone": "America/Chicago",
            "weeklyAvailability": [{"dayOfWeek": 1, "startTime": "18:00", "endTime": "23:30"}],
            "bufferBeforeMinutes": 30,
            "bufferAfterMinutes": 30,
        })

    def test_preferences_validate_and_persist_scheduling_defaults(self):
        app = load_app("manage-preferences-lambda", self.table)
        payload = {
            "defaultZipCode": "60614",
            "defaultRadiusMiles": 20,
            "preferredFormats": ["35mm"],
            "timeZone": "America/Chicago",
            "weeklyAvailability": [
                {"dayOfWeek": 5, "startTime": "18:00", "endTime": "21:00"},
                {"dayOfWeek": 6, "startTime": "14:00", "endTime": "22:00"},
            ],
            "bufferBeforeMinutes": 15,
            "bufferAfterMinutes": 45,
        }
        saved = app.handler(event("PUT", path="/me/preferences", body=payload), None)
        self.assertEqual(200, saved["statusCode"])
        self.assertEqual("America/Chicago", body(saved)["preferences"]["timeZone"])
        self.assertEqual(45, body(saved)["preferences"]["bufferAfterMinutes"])

        payload["weeklyAvailability"] = [
            {"dayOfWeek": 5, "startTime": "18:00", "endTime": "21:00"},
            {"dayOfWeek": 5, "startTime": "20:00", "endTime": "22:00"},
        ]
        overlap = app.handler(event("PUT", path="/me/preferences", body=payload), None)
        self.assertEqual(400, overlap["statusCode"])

        payload["weeklyAvailability"] = []
        payload["timeZone"] = "Not/A_Timezone"
        invalid_zone = app.handler(event("PUT", path="/me/preferences", body=payload), None)
        self.assertEqual(400, invalid_zone["statusCode"])

    def test_derivation_is_conservative_and_manual_answers_win(self):
        load_app("manage-availability-lambda", self.table)
        from cmc_availability import resolve_status, scheduling_preferences

        now = datetime.now(timezone.utc)
        showtime = {"showtimeId": "show-1", "startsAtUtc": "2026-10-27T00:00:00Z"}
        movie = {"runtime": 120}
        preferences = scheduling_preferences({
            "timeZone": "America/Chicago",
            "weeklyAvailability": [{"dayOfWeek": 1, "startTime": "18:00", "endTime": "23:30"}],
        })
        membership = {"shareCalendarAvailability": True}
        fresh = (now - timedelta(minutes=5)).isoformat()

        self.assertEqual("available", resolve_status(
            showtime=showtime, movie=movie, preferences=preferences, membership=membership,
            availability={}, integration={}, revision=1, at=now,
        ))
        self.assertEqual("unknown", resolve_status(
            showtime=showtime, movie=movie, preferences=preferences, membership=membership,
            availability={"availabilityRevision": 1, "calendarSyncStatus": "current", "calendarSyncedAt": fresh, "calendarStatuses": {"show-1": "free"}},
            integration={"status": "needs_reauth", "selectedCalendarIds": ["primary"]}, revision=1, at=now,
        ))
        self.assertEqual("unknown", resolve_status(
            showtime=showtime, movie=movie, preferences=preferences, membership=membership,
            availability={"availabilityRevision": 1, "calendarSyncStatus": "partial", "calendarSyncedAt": fresh, "calendarStatuses": {"show-1": "free"}},
            integration={"status": "connected", "selectedCalendarIds": ["primary"]}, revision=1, at=now,
        ))
        self.assertEqual("unavailable", resolve_status(
            showtime=showtime, movie=movie, preferences=preferences, membership=membership,
            availability={"availabilityRevision": 1, "calendarSyncStatus": "partial", "calendarSyncedAt": fresh, "calendarStatuses": {"show-1": "conflict"}},
            integration={"status": "connected", "selectedCalendarIds": ["primary"]}, revision=1, at=now,
        ))
        self.assertEqual("maybe", resolve_status(
            showtime=showtime, movie=movie, preferences=preferences, membership={"shareCalendarAvailability": False},
            availability={"availabilityRevision": 1, "manualOverrides": {"show-1": "maybe"}},
            integration={}, revision=1, at=now,
        ))

    def test_matrix_is_named_private_and_revision_safe(self):
        self.seed_night()
        app = load_app("manage-availability-lambda", self.table)
        response = app.handler(event("GET", path="/movie-nights/night-1/availability", movie_night_id="night-1"), None)
        self.assertEqual(200, response["statusCode"])
        payload = body(response)
        self.assertEqual(["Alex", "Sam"], [member["displayName"] for member in payload["showtimes"][0]["members"]])
        self.assertEqual({"available": 1, "maybe": 0, "unavailable": 0, "unknown": 1}, payload["showtimes"][0]["counts"])
        self.assertNotIn("calendar", json.dumps(payload["showtimes"]))
        self.assertNotIn("userId", json.dumps(payload))
        friend_payload = body(app.handler(event("GET", path="/movie-nights/night-1/availability", movie_night_id="night-1", user_id="user-2", groups="Friend"), None))
        self.assertIsNone(friend_payload["bestFitShowtimeId"])

        stale = app.handler(event("PUT", path="/movie-nights/night-1/availability/me", movie_night_id="night-1", body={
            "availabilityRevision": 2,
            "overrides": [{"showtimeId": "show-1", "status": "maybe"}],
        }), None)
        self.assertEqual(409, stale["statusCode"])

        saved = app.handler(event("PUT", path="/movie-nights/night-1/availability/me", movie_night_id="night-1", body={
            "availabilityRevision": 3,
            "overrides": [{"showtimeId": "show-1", "status": "maybe"}],
        }), None)
        self.assertEqual(200, saved["statusCode"])
        refreshed = body(app.handler(event("GET", path="/movie-nights/night-1/availability", movie_night_id="night-1"), None))
        self.assertEqual("maybe", refreshed["showtimes"][0]["members"][0]["status"])

    def test_answers_freeze_after_voting_closes(self):
        self.seed_night(status="voting", voting_deadline="2020-01-01T00:00:00Z")
        app = load_app("manage-availability-lambda", self.table)
        result = app.handler(event("PUT", path="/movie-nights/night-1/availability/me", movie_night_id="night-1", body={
            "availabilityRevision": 3,
            "overrides": [],
        }), None)
        self.assertEqual(409, result["statusCode"])

    def test_oauth_state_is_one_time_and_refresh_token_is_encrypted(self):
        app = load_app("manage-calendar-integration-lambda", self.table)
        authorize = app.handler(event("POST", path="/me/integrations/google-calendar/authorize", body={
            "redirectUri": "https://movies.example.com/api/google-calendar/callback",
        }), None)
        self.assertEqual(200, authorize["statusCode"])
        authorization_url = body(authorize)["authorizationUrl"]
        query = parse_qs(urlparse(authorization_url).query)
        self.assertIn("https://www.googleapis.com/auth/calendar.freebusy", query["scope"][0])
        state = query["state"][0]

        with patch.object(app, "request_json", side_effect=[
            {"access_token": "short-lived-access", "refresh_token": "durable-refresh", "scope": " ".join(app.SCOPES)},
            {"sub": "google-subject", "email": "alex@gmail.com"},
        ]):
            callback = app.handler(event("GET", path="/integrations/google-calendar/callback", query={"state": state, "code": "oauth-code"}), None)
        self.assertEqual(200, callback["statusCode"])
        serialized = json.dumps(body(callback))
        self.assertNotIn("durable-refresh", serialized)
        self.assertNotIn("short-lived-access", serialized)
        integration = self.table.items[("USER#user-1", "CALENDAR#GOOGLE")]
        self.assertNotEqual("durable-refresh", integration["encryptedRefreshToken"])

        replay = app.handler(event("GET", path="/integrations/google-calendar/callback", query={"state": state, "code": "oauth-code"}), None)
        self.assertEqual(400, replay["statusCode"])

    def test_calendar_selection_enforces_provider_limit(self):
        app = load_app("manage-calendar-integration-lambda", self.table)
        result = app.handler(event("PUT", path="/me/integrations/google-calendar", body={
            "selectedCalendarIds": [f"calendar-{index}" for index in range(51)],
        }), None)
        self.assertEqual(400, result["statusCode"])

    def test_worker_handles_partial_results_and_marks_invalid_grant(self):
        self.seed_night()
        self.table.put_item(Item={
            "PK": "USER#user-1",
            "SK": "CALENDAR#GOOGLE",
            "GSI1PK": "CALENDAR_PROVIDER#google#connected",
            "GSI1SK": "USER#user-1",
            "userId": "user-1",
            "status": "connected",
            "selectedCalendarIds": ["primary", "team"],
            "encryptedRefreshToken": "ZW5jcnlwdGVkOnJlZnJlc2g=",
        })
        app = load_app("calendar-sync-worker-lambda", self.table)
        preferences = {
            "timeZone": "America/Chicago",
            "weeklyAvailability": [],
            "bufferBeforeMinutes": 30,
            "bufferAfterMinutes": 30,
        }
        night = self.table.items[("CLUB#club-1", "MOVIE_NIGHT#night-1")]
        showtime = self.table.items[("MOVIE_NIGHT#night-1", "SHOWTIME#show-1")]
        statuses, sync_status = app.calendar_statuses({"calendars": {
            "primary": {"busy": [{"start": "2026-10-26T23:45:00Z", "end": "2026-10-27T00:15:00Z"}]},
            "team": {"errors": [{"reason": "notFound"}]},
        }}, ["primary", "team"], [(night, [showtime])], preferences)
        self.assertEqual("partial", sync_status)
        self.assertEqual("conflict", statuses["night-1"]["show-1"])

        with patch.object(app, "access_token", side_effect=app.ProviderFailure("needs_reauth", retryable=False)):
            outcome = app.sync_user("user-1")
        self.assertEqual("reauth", outcome)
        integration = self.table.items[("USER#user-1", "CALENDAR#GOOGLE")]
        self.assertEqual("needs_reauth", integration["status"])
        self.assertEqual("CALENDAR_PROVIDER#google#needs_reauth", integration["GSI1PK"])


if __name__ == "__main__":
    unittest.main()
