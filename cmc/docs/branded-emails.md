# Movie Club emails

All application emails use the pure Python renderer in `shared/cmc_email.py`.
Each SES message includes UTF-8 HTML and a complete plain-text alternative.
Content is escaped as text; callers supply existing application URLs. No images,
web fonts, third-party stylesheets, or new dependencies are required.

The sender display name is Movie Club. The mailbox still comes from the existing
`NOTIFICATION_EMAIL_FROM`, `INVITE_EMAIL_FROM`, or `MOVIE_NIGHT_EMAIL_FROM` setting.
Existing SES identities and notification configuration sets remain in use.

Email subjects include the action and movie or club where available. In-app and
push titles and bodies are unchanged. Only the email test action uses the club
schedule instead of the synthetic test movie-night ID. Notification footers link
to `/settings` as “Manage reminder preferences”; the setting controls reminders,
not milestone emails. Invitations and admin showtime emails omit this link.
Cognito verification and account recovery emails are outside this change.
Plan-change emails group previous and current details into separate paragraphs,
omit unavailable details, and retain the instruction to review tickets separately.

## Local review

From the repository root:

```sh
python3 cmc/scripts/preview_emails.py --output /tmp/cmc-email-previews
python3 -m unittest discover -s cmc/tests
python3 -m pytest -q cmc/tests cmc/gracenote-showtime-worker-lambda/test_app.py cmc/gracenote-showtime-coordinator-lambda/test_app.py --import-mode=importlib
```

Open `/tmp/cmc-email-previews/index.html` for all nine email variants in desktop
and mobile frames. Each variant also has standalone HTML and plain-text files.
The previews use sample data and never access AWS or send email. Do not commit
generated previews or deployment archives.

Review at 320px, 375px, and desktop widths: headings should wrap, the primary
action should remain visible, and fallback URLs should not cause horizontal
scrolling. The email is capped at 600px and uses inline styles, presentation
tables, explicit dark backgrounds, and an Outlook conditional width wrapper.
The violet button has dark text; the body uses light slate text on dark slate.
Browser previews do not replace rendering checks in Gmail, Apple Mail, or
Outlook, which can alter colors and styles.

## Deployment

Package and deploy these functions together through the existing Lambda workflow:

- `cmc-notification-worker-lambda`
- `cmc-manage-invites-lambda`
- `cmc-gracenote-showtime-worker-lambda`

Both `build-lambda.sh` and `build-lambda-with-layer.sh` already copy
`cmc/shared/*.py` into each CMC package, including the new renderer. The deployment
workflow detects shared-module changes and may redeploy other CMC functions too.
No Terraform, API, database, or environment-variable changes are required.

After deployment, the existing admin test-notification action can verify a live
email, its club schedule link, and the existing SES delivery diagnostics. Sending
that test is an explicit operational step; preview generation and tests send no
real emails.
