"""Email rendering and SES integration, using the existing in-memory AWS fakes."""
import os
import sys
import types
import unittest
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock, patch

if __package__:
    from .test_mvp_handlers import FakeTable, load_app
else:
    from test_mvp_handlers import FakeTable, load_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from cmc_email import branded_sender, invitation_email, render_email, showtime_results_email


class EmailHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.tags = []
        self.content = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs)["href"])

    def handle_data(self, data):
        self.content.append(data)


class EmailTemplateTests(unittest.TestCase):
    def test_all_dynamic_html_content_and_urls_are_escaped(self):
        value = 'A & B <script>alert("film")</script> \'premiere\''
        url = 'https://movies.example.com/invites/token?club="A&B"&next=<film>'
        message = render_email(
            subject=value, heading=value, body=f"{value}\nSecond line\n\nAnother paragraph",
            label=value, action_label=value, action_url=url, preferences_url=url,
        )
        parsed = EmailHTML(message["Body"]["Html"]["Data"])
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("img", parsed.tags)
        self.assertIn(value, "".join(parsed.content))
        self.assertEqual([url, url, url], parsed.links)
        self.assertIn(value, message["Body"]["Text"]["Data"])
        self.assertIn(url, message["Body"]["Text"]["Data"])
        self.assertIn("<br>", message["Body"]["Html"]["Data"])
        self.assertEqual(value, message["Subject"]["Data"])
        for part in (message["Subject"], *message["Body"].values()):
            self.assertEqual("UTF-8", part["Charset"])

    def test_sender_keeps_mailbox_with_or_without_existing_display_name(self):
        for source in ("notifications@example.com", 'Old Brand <notifications@example.com>'):
            with self.subTest(source=source):
                self.assertEqual(("Movie Club", "notifications@example.com"), parseaddr(branded_sender(source)))

    def test_invitation_contains_expiry_and_escaped_club_without_member_settings(self):
        club = 'Friends & <Film> "Fans"'
        message = invitation_email(club, "https://movies.example.com/invites/abc")
        self.assertEqual(f"Join {club} on Movie Club", message["Subject"]["Data"])
        for part in message["Body"].values():
            self.assertIn("expires in 14 days", part["Data"])
            self.assertIn("Accept invitation", part["Data"])
            self.assertNotIn("Manage reminder preferences", part["Data"])
        self.assertIn(club, "".join(EmailHTML(message["Body"]["Html"]["Data"]).content))

    def test_missing_optional_names_have_readable_fallbacks(self):
        for message in (invitation_email(None, "https://movies.example.com/invites/abc"),
                        showtime_results_email(None, 0, "https://movies.example.com/admin")):
            for part in message["Body"].values():
                self.assertNotIn("None", part["Data"])
                self.assertNotIn("undefined", part["Data"])


class EmailDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "APP_BASE_URL": "https://movies.example.com/",
            "APP_TABLE_NAME": "cmc-test",
            "NOTIFICATION_EMAIL_FROM": "Old Name <notifications@example.com>",
            "NOTIFICATION_EMAIL_CONFIGURATION_SET": "delivery-events",
            "INVITE_EMAIL_FROM": "invites@example.com",
            "MOVIE_NIGHT_EMAIL_FROM": "showtimes@example.com",
            "WEB_PUSH_VAPID_PRIVATE_KEY": "", "WEB_PUSH_VAPID_CLAIMS_EMAIL": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.push_module = patch.dict(sys.modules, {
            "pywebpush": types.SimpleNamespace(WebPushException=Exception, webpush=Mock()),
        })
        self.push_module.start()
        self.addCleanup(self.push_module.stop)
        self.table = FakeTable()
        self.table.put_item(Item={
            "PK": "CLUB#club-1", "SK": "MEMBER#admin", "clubId": "club-1",
            "userId": "admin", "role": "admin", "status": "active", "email": "admin@example.com",
        })

    def notification(self, kind="voting_open", identifier=None):
        return {
            "eventId": identifier or kind, "notificationType": kind, "clubId": "club-1",
            "movieNightId": "synthetic-test-id" if kind == "test_notification" else "night-1",
            "movieTitle": 'Amélie & <Friends> "Premiere"', "targetUserId": "admin",
        }

    def assert_message(self, call, sender, action, link):
        self.assertEqual(("Movie Club", sender), parseaddr(call["Source"]))
        self.assertEqual("UTF-8", call["Message"]["Subject"]["Charset"])
        self.assertIn("Movie Club", call["Message"]["Subject"]["Data"])
        for part in call["Message"]["Body"].values():
            self.assertEqual("UTF-8", part["Charset"])
            self.assertIn("Movie Club", part["Data"])
            self.assertIn(action, part["Data"])
            self.assertIn(link, part["Data"])
        self.assertEqual([link, link], EmailHTML(call["Message"]["Body"]["Html"]["Data"]).links[:2])

    def test_all_seven_notifications_brand_email_and_preserve_in_app_and_push_copy(self):
        app = load_app("notification-worker-lambda", self.table)
        actions = {
            "voting_open": "Vote on showtimes", "showtime_confirmed": "RSVP",
            "showtime_changed": "Review updated plan", "movie_night_cancelled": "View cancellation",
            "vote_reminder": "Vote on showtimes", "rsvp_reminder": "RSVP",
            "test_notification": "View club schedule",
        }
        for kind, action in actions.items():
            with self.subTest(kind=kind):
                notification = self.notification(kind)
                subject, body = app.notification_copy(notification)
                with patch.object(app, "send_push") as push:
                    self.assertTrue(app.deliver(notification))
                call = app.ses.sent[-1]
                link = "https://movies.example.com/clubs/club-1"
                if kind != "test_notification":
                    link += "/movie-nights/night-1"
                    self.assertIn(notification["movieTitle"], call["Message"]["Subject"]["Data"])
                self.assert_message(call, "notifications@example.com", action, link)
                self.assertEqual("delivery-events", call["ConfigurationSetName"])
                item = self.table.items[("USER#admin", f"NOTIFICATION#{kind}")]
                self.assertEqual((subject, body), (item["title"], item["body"]))
                self.assertEqual((subject, body, item["href"]), push.call_args.args[1:4])
                self.assertEqual("sent", item["emailStatus"])
                for part in call["Message"]["Body"].values():
                    self.assertIn("Manage reminder preferences", part["Data"])
                    self.assertIn("https://movies.example.com/settings", part["Data"])
                    if kind == "test_notification":
                        self.assertNotIn("synthetic-test-id", part["Data"])

    def test_changed_and_cancelled_emails_preserve_plan_and_ticket_instructions(self):
        app = load_app("notification-worker-lambda", self.table)
        for kind in ("showtime_changed", "movie_night_cancelled"):
            with self.subTest(kind=kind):
                notification = self.notification(kind)
                notification["previousPlan"] = {"theaterName": "Old Cinema", "startsAtUtc": "2026-11-01T19:00:00Z", "screenFormat": "IMAX"}
                notification["confirmedShowtime"] = {"theaterName": "New Cinema", "startsAtUtc": "2026-11-02T20:00:00Z", "screenFormat": "Dolby"}
                app.deliver(notification)
                for part in app.ses.sent[-1]["Message"]["Body"].values():
                    for detail in ("Previous plan", "Old Cinema", "2026-11-01T19:00:00Z", "IMAX"):
                        self.assertIn(detail, part["Data"])
                    if kind == "showtime_changed":
                        for detail in ("Current plan", "New Cinema", "2026-11-02T20:00:00Z", "Dolby", "Review your tickets separately"):
                            self.assertIn(detail, part["Data"])

    def test_disabled_reminders_do_not_disable_milestone_email(self):
        app = load_app("notification-worker-lambda", self.table)
        self.table.put_item(Item={"PK": "USER#admin", "SK": "PREFERENCES", "reminderEmailsEnabled": False})
        app.deliver(self.notification("vote_reminder"))
        app.deliver(self.notification("rsvp_reminder"))
        self.assertEqual([], app.ses.sent)
        app.deliver(self.notification("showtime_confirmed"))
        self.assertEqual(1, len(app.ses.sent))

    def test_missing_sender_or_recipient_retains_delivery_status(self):
        app = load_app("notification-worker-lambda", self.table)
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL_FROM": ""}):
            self.assertTrue(app.deliver(self.notification()))
        self.assertEqual("not_configured", self.table.items[("USER#admin", "NOTIFICATION#voting_open")]["emailStatus"])
        self.table.items[("CLUB#club-1", "MEMBER#admin")].pop("email")
        self.assertTrue(app.deliver(self.notification("showtime_confirmed")))
        self.assertEqual("disabled", self.table.items[("USER#admin", "NOTIFICATION#showtime_confirmed")]["emailStatus"])
        self.assertEqual([], app.ses.sent)

    def test_failed_email_retries_but_sent_email_is_not_resent(self):
        app = load_app("notification-worker-lambda", self.table)
        notification = self.notification()
        with patch.object(app.ses, "send_email", side_effect=RuntimeError("unavailable")):
            self.assertFalse(app.deliver(notification))
        self.assertEqual("failed", self.table.items[("USER#admin", "NOTIFICATION#voting_open")]["emailStatus"])
        self.assertTrue(app.deliver(notification))
        self.assertTrue(app.deliver(notification))
        self.assertEqual(1, len(app.ses.sent))

    def test_configuration_set_is_optional(self):
        app = load_app("notification-worker-lambda", self.table)
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL_CONFIGURATION_SET": ""}):
            app.deliver(self.notification())
        self.assertNotIn("ConfigurationSetName", app.ses.sent[0])

    def test_notification_without_movie_title_renders_cleanly(self):
        app = load_app("notification-worker-lambda", self.table)
        notification = self.notification("showtime_changed")
        notification.pop("movieTitle")
        app.deliver(notification)
        message = app.ses.sent[0]["Message"]
        self.assertIn("Movie night", message["Subject"]["Data"])
        for part in message["Body"].values():
            self.assertNotIn("None", part["Data"])
            self.assertNotIn("undefined", part["Data"])
            self.assertNotIn("Current plan:", part["Data"])
            self.assertNotIn("Previous plan:", part["Data"])
            self.assertIn("Review your tickets separately.", part["Data"])

    def test_only_eligible_members_receive_each_notification(self):
        app = load_app("notification-worker-lambda", self.table)
        for user, status in (("friend", "active"), ("removed", "removed")):
            self.table.put_item(Item={"PK": "CLUB#club-1", "SK": f"MEMBER#{user}", "userId": user,
                                      "email": f"{user}@example.com", "role": "friend", "status": status})
        self.table.put_item(Item={"PK": "MOVIE_NIGHT#night-1", "SK": "VOTE#friend", "userId": "friend"})
        self.table.put_item(Item={"PK": "MOVIE_NIGHT#night-1", "SK": "RSVP#friend", "userId": "friend", "rsvpPlanRevision": 2})
        for kind in ("vote_reminder", "rsvp_reminder", "test_notification"):
            with self.subTest(kind=kind):
                app.ses.sent.clear()
                notification = self.notification(kind)
                notification["planRevision"] = 2
                app.deliver(notification)
                self.assertEqual([{"ToAddresses": ["admin@example.com"]}], [c["Destination"] for c in app.ses.sent])

    def test_invitation_sender_uses_shared_template_and_original_destination(self):
        app = load_app("manage-invites-lambda", self.table)
        app.send_invite_email("new@example.com", {"name": "Cinema & Friends"}, "invite-token", {})
        self.assertEqual({"ToAddresses": ["new@example.com"]}, app.ses.sent[0]["Destination"])
        self.assert_message(app.ses.sent[0], "invites@example.com", "Accept invitation", "https://movies.example.com/invites/invite-token")
        with patch.dict(os.environ, {"INVITE_EMAIL_FROM": ""}):
            app.send_invite_email("new@example.com", {}, "invite-token", {})
        self.assertEqual(1, len(app.ses.sent))

    def test_showtime_results_only_email_active_admins_with_deduplicated_addresses(self):
        app = load_app("gracenote-showtime-worker-lambda", self.table)
        self.table.put_item(Item={"PK": "CLUB#club-1", "SK": "MOVIE_NIGHT#night-1", "status": "planning", "showtimeMonitoring": {"status": "active"}})
        for user, role, status, email in (("duplicate", "admin", "active", "admin@example.com"),
                                         ("removed", "admin", "removed", "removed@example.com"),
                                         ("friend", "friend", "active", "friend@example.com")):
            self.table.put_item(Item={"PK": "CLUB#club-1", "SK": f"MEMBER#{user}", "role": role, "status": status, "email": email})
        message = {"monitoring": True, "monitorPK": "SHOWTIME_MONITOR", "monitorSK": "CHECK#one",
                   "clubId": "club-1", "movieNightId": "night-1", "movieTitle": 'Film & <Friends> "Premiere"'}
        app.finish_monitor(message, {"resultCount": 3})
        self.assertEqual(1, len(app.ses.sent))
        call = app.ses.sent[0]
        self.assertEqual({"ToAddresses": ["admin@example.com"]}, call["Destination"])
        self.assert_message(call, "showtimes@example.com", "Review showtimes", "https://movies.example.com/clubs/club-1/movie-nights/night-1/admin")
        for part in call["Message"]["Body"].values():
            self.assertIn("3 candidate listing(s)", part["Data"])
            self.assertNotIn("Manage reminder preferences", part["Data"])
        parsed = EmailHTML(call["Message"]["Body"]["Html"]["Data"])
        self.assertIn(message["movieTitle"], "".join(parsed.content))
        self.assertNotIn("friends", parsed.tags)


if __name__ == "__main__":
    unittest.main()
