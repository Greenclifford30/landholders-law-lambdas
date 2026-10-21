"""Generate local email previews without AWS access or sending messages."""
import argparse
from html import escape
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from cmc_email import invitation_email, notification_email, showtime_results_email


def sample_messages():
    base = "https://movies.example.com"
    link = f"{base}/clubs/chicago/movie-nights/arrival"
    samples = {
        "voting_open": ("Voting is open", "Vote for your preferred showtimes for Arrival."),
        "showtime_confirmed": ("Your movie night is confirmed", "Arrival has a confirmed showtime. Please RSVP."),
        "showtime_changed": (
            "Your movie night changed",
            "The confirmed showtime for Arrival changed. Please review and RSVP.",
        ),
        "movie_night_cancelled": (
            "Movie night cancelled",
            "Arrival has been cancelled.",
        ),
        "vote_reminder": ("Vote reminder", "Voting for Arrival closes in about 24 hours."),
        "rsvp_reminder": ("RSVP reminder", "Arrival is about 24 hours away. Let your club know if you are going."),
        "test_notification": (
            "Movie Club notification test",
            "This is a test of your in-app, email, and browser push notification channels.",
        ),
    }
    messages = {
        kind: notification_email(
            {"notificationType": kind, "movieTitle": "Arrival",
             "previousPlan": {"theaterName": "Music Box Theatre", "startsAtUtc": "2026-11-06T01:00:00Z", "screenFormat": "Standard"},
             "confirmedShowtime": {"theaterName": "AMC River East", "startsAtUtc": "2026-11-07T01:30:00Z", "screenFormat": "IMAX"}},
            heading=heading, body=body,
            link=f"{base}/clubs/chicago" if kind == "test_notification" else link,
            preferences_url=f"{base}/settings",
        )
        for kind, (heading, body) in samples.items()
    }
    messages["invitation"] = invitation_email("Chicago Film Friends", f"{base}/invites/sample-invite")
    messages["showtime_results"] = showtime_results_email("Arrival", 6, f"{link}/admin")
    return messages


def generate_previews(output):
    output.mkdir(parents=True, exist_ok=True)
    sections = []
    for index, (name, message) in enumerate(sample_messages().items()):
        (output / f"{name}.html").write_text(message["Body"]["Html"]["Data"], encoding="utf-8")
        (output / f"{name}.txt").write_text(message["Body"]["Text"]["Data"], encoding="utf-8")
        sections.append(f"""
<details {'open' if index == 0 else ''}>
  <summary>{escape(name.replace('_', ' ').title())}</summary>
  <p><strong>From:</strong> Movie Club &lt;notifications@example.com&gt;</p>
  <p><strong>Subject:</strong> {escape(message['Subject']['Data'])}</p>
  <p><a href="{name}.html">Standalone HTML</a> · <a href="{name}.txt">Plain text</a></p>
  <div class="previews">
    <div><p>Desktop · 680px viewport, 600px email</p><iframe title="{name} desktop" src="{name}.html" width="680" height="1000" loading="lazy"></iframe></div>
    <div><p>Mobile · 375px viewport</p><iframe title="{name} mobile" src="{name}.html" width="375" height="1000" loading="lazy"></iframe></div>
  </div>
</details>""")
    gallery = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Movie Club email previews</title><style>
body{margin:32px;background:#0b101c;color:#f8fafc;font:16px/1.5 Arial,Helvetica,sans-serif}
h1{margin-bottom:8px}a{color:#c4b5fd}details{padding:24px 0;border-top:1px solid #2d3748}
summary{cursor:pointer;font-size:20px;font-weight:bold}.previews{display:flex;gap:24px;overflow:auto}
iframe{border:1px solid #475569;display:block;background:#070a12}.previews>div{flex-shrink:0}
</style></head><body><h1>Movie Club email previews</h1>
<p>Sample data only. No emails are sent. The frames contain the actual HTML supplied to SES.</p>
""" + "".join(sections) + "</body></html>"
    (output / "index.html").write_text(gallery, encoding="utf-8")
    return output / "index.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/cmc-email-previews"))
    args = parser.parse_args()
    print(generate_previews(args.output).resolve())
