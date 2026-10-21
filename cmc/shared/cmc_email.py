"""Movie Club SES messages. Rendering is pure and requires no AWS clients."""

from email.utils import formataddr, parseaddr
from html import escape


def branded_sender(source):
    """Keep the configured SES mailbox while consistently naming the sender."""
    _, address = parseaddr(source)
    return formataddr(("Movie Club", address))


def render_email(*, subject, heading, body, label, action_label, action_url, preferences_url=None):
    """Return an SES Message with equivalent UTF-8 HTML and plain-text content.

    All content arguments are plain text, including body. URLs come from the
    application's existing link builders, never from HTML supplied by callers.
    """
    preheader = " ".join(body.split())[:160]
    paragraphs = "".join(
        '<p style="margin:0 0 20px;font-size:16px;line-height:26px;color:#CBD5E1;">'
        + escape(paragraph).replace("\n", "<br>")
        + "</p>"
        for paragraph in body.split("\n\n") if paragraph.strip()
    )
    settings_html = ""
    settings_text = ""
    if preferences_url:
        settings_html = (
            '<p style="margin:12px 0 0;font-size:14px;line-height:22px;">'
            f'<a href="{escape(preferences_url, quote=True)}" style="color:#C4B5FD;text-decoration:underline;">'
            'Manage reminder preferences</a></p>'
        )
        settings_text = f"\n\nManage reminder preferences: {preferences_url}"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="supported-color-schemes" content="dark">
  <title>{escape(subject)}</title>
</head>
<body bgcolor="#070A12" style="margin:0;padding:0;width:100%;background-color:#070A12;color:#F8FAFC;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
  <div style="display:none;font-size:1px;line-height:1px;color:#070A12;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{escape(preheader)}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#070A12" style="width:100%;background-color:#070A12;">
    <tr><td align="center" style="padding:32px 16px;">
      <!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;table-layout:fixed;">
        <tr><td style="padding:0 8px 24px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td width="40" height="40" align="center" bgcolor="#A78BFA" style="width:40px;height:40px;background-color:#A78BFA;border-radius:8px;color:#0C0A18;font-size:14px;font-weight:bold;letter-spacing:1px;">MC</td>
              <td style="padding-left:12px;color:#F8FAFC;font-size:20px;line-height:26px;font-weight:bold;">Movie Club</td>
            </tr>
          </table>
        </td></tr>
        <tr><td height="4" bgcolor="#A78BFA" style="height:4px;background-color:#A78BFA;font-size:1px;line-height:4px;">&nbsp;</td></tr>
        <tr><td bgcolor="#111827" style="padding:32px 24px;background-color:#111827;border:1px solid #2D3748;border-top:0;overflow-wrap:anywhere;word-wrap:break-word;">
          <p style="margin:0 0 16px;color:#C4B5FD;font-size:12px;font-weight:bold;line-height:20px;letter-spacing:2px;text-transform:uppercase;">{escape(label)}</p>
          <h1 style="margin:0 0 20px;color:#F8FAFC;font-size:30px;font-weight:bold;line-height:36px;letter-spacing:-0.5px;">{escape(heading)}</h1>
          {paragraphs}
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;max-width:100%;">
            <tr><td align="center" bgcolor="#A78BFA" style="background-color:#A78BFA;border-radius:8px;mso-padding-alt:14px 24px;">
              <a href="{escape(action_url, quote=True)}" style="display:inline-block;padding:14px 24px;border:1px solid #A78BFA;border-radius:8px;color:#0C0A18;font-size:16px;font-weight:bold;line-height:22px;text-align:center;text-decoration:none;mso-padding-alt:0;">{escape(action_label)}</a>
            </td></tr>
          </table>
          <p style="margin:28px 0 8px;color:#94A3B8;font-size:14px;line-height:22px;">If the button doesn’t work, open this link:</p>
          <p style="margin:0;font-size:14px;line-height:22px;overflow-wrap:anywhere;word-break:break-all;">
            <a href="{escape(action_url, quote=True)}" style="color:#C4B5FD;text-decoration:underline;word-break:break-all;">{escape(action_url)}</a>
          </p>
        </td></tr>
        <tr><td style="padding:24px 8px 0;color:#94A3B8;font-size:14px;line-height:22px;">
          <p style="margin:0;color:#CBD5E1;font-weight:bold;">Movie Club</p>
          <p style="margin:4px 0 0;">An update from your movie club.</p>
          {settings_html}
        </td></tr>
      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td></tr>
  </table>
</body>
</html>"""
    text = (
        f"Movie Club\n{label}\n\n{heading}\n\n{body}\n\n"
        f"{action_label}: {action_url}\n\nAn update from your movie club.{settings_text}"
    )
    return {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {
            "Html": {"Data": html, "Charset": "UTF-8"},
            "Text": {"Data": text, "Charset": "UTF-8"},
        },
    }


def notification_email(event, *, heading, body, link, preferences_url):
    title = event.get("movieTitle") or "Movie night"
    kind = event["notificationType"]
    label, action, subject = {
        "voting_open": ("Voting is open", "Vote on showtimes", f"Vote on showtimes for {title}"),
        "showtime_confirmed": ("Plan confirmed", "RSVP", f"RSVP for {title} — your movie night is confirmed"),
        "showtime_changed": ("Plan updated", "Review updated plan", f"Review the updated plan for {title}"),
        "movie_night_cancelled": ("Movie night cancelled", "View cancellation", f"Movie night cancelled: {title}"),
        "vote_reminder": ("Voting closes soon", "Vote on showtimes", f"Vote for {title} — voting closes in about 24 hours"),
        "rsvp_reminder": ("Your movie night is near", "RSVP", f"RSVP for {title} — your movie night is about 24 hours away"),
        "test_notification": ("Notification test", "View club schedule", "Your notification test"),
    }[kind]
    if kind in {"showtime_changed", "movie_night_cancelled"}:
        plans = [("previousPlan", "Previous plan")]
        if kind == "showtime_changed":
            plans.append(("confirmedShowtime", "Current plan"))
        for key, plan_label in plans:
            plan = event.get(key) or {}
            details = [str(plan[field]) for field in ("theaterName", "startsAtUtc", "screenFormat") if plan.get(field)]
            if details:
                body += f"\n\n{plan_label}: {', '.join(details)}."
        if kind == "showtime_changed":
            body += "\n\nReview your tickets separately."
    return render_email(
        subject=f"{subject} | Movie Club", heading=heading, body=body,
        label=label, action_label=action, action_url=link, preferences_url=preferences_url,
    )


def invitation_email(club_name, link):
    club_name = club_name or "Movie Club"
    return render_email(
        subject=f"Join {club_name} on Movie Club",
        heading="You’re invited to movie night.",
        body=f"You have been invited to join {club_name} on Movie Club.\n\nThis invite expires in 14 days.",
        label="Club invitation", action_label="Accept invitation", action_url=link,
    )


def showtime_results_email(movie_title, result_count, link):
    movie_title = movie_title or "Movie night"
    return render_email(
        subject=f"Review showtimes for {movie_title} | Movie Club",
        heading="Your showtimes are ready.",
        body=f"Showtimes are now available for {movie_title}.\n\nReview {result_count} candidate listing(s) and choose the options for your club.",
        label="Showtimes found", action_label="Review showtimes", action_url=link,
    )
