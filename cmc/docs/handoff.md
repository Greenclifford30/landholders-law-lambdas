# Lambda Implementation Handoff

This handoff reviews the Lambda infrastructure in `landholders-law-tf/chi-movie-club/lambda.tf` and maps it to the source expected under `landholders-law-lambdas/cmc`.

## Current State

All Lambda resources in Terraform currently deploy:

```hcl
handler  = "app.handler"
runtime  = "python3.13"
filename = "${path.module}/placeholder_lambda/placeholder_lambda.zip"
```

That means Terraform creates the Lambda functions, API Gateway integrations, SQS triggers, IAM roles, and environment variables, but it does not yet package or deploy the real source from this repo.

Source currently exists for these functions:

- `admin-selection-lambda`
- `movie-scraper-lambda`
- `get-selection-lambda`
- `get-options-lambda`
- `gracenote-showtime-coordinator-lambda`
- `gracenote-showtime-worker-lambda`

Source is missing for these Terraform-declared functions:

- `movie-search-lambda`
- `create-movie-night-lambda`
- `get-active-movie-night-lambda`
- `manage-showtimes-lambda`
- `submit-vote-lambda`
- `vote-results-lambda`
- `confirm-showtime-lambda`
- `update-rsvp-lambda`
- `list-history-lambda`
- `vote-handler`

## Highest Priority Work

1. Add packaging/deployment wiring so Terraform points at real Lambda zip artifacts instead of the placeholder zip.
2. Implement missing source directories for the newer Cognito-protected Movie Club API handlers.
3. Normalize existing legacy handlers to the single-table DynamoDB model used by `db.tf`.
4. Decide whether the legacy `/admin/selection`, `/selection`, `/options`, and `/vote` endpoints remain supported or are replaced by the newer club/movie-night routes.
5. Add tests for every handler before connecting it to production traffic.

## Infrastructure Map

### DynamoDB

Terraform creates one app table:

```text
Table: ${var.app}_app
PK: PK
SK: SK
GSI1: GSI1PK / GSI1SK
GSI2: GSI2PK / GSI2SK
TTL: expiresAt
```

All Lambda source should use `APP_TABLE_NAME` and the single-table keys above. Existing legacy handlers still assume older ad hoc item shapes such as `movieId`, `showDate`, and `theaters`; update those before relying on them for the MVP flows.

### Shared IAM Role

Most non-Gracenote Lambdas use `aws_iam_role.lambda_role`, which allows:

- CloudWatch logs
- SES send actions
- DynamoDB `PutItem`, `GetItem`, `UpdateItem`, `DeleteItem`, `Query`, and `Scan`
- SQS send/consume actions on `cmc-admin-selection-queue`

Use this role for the general API handlers unless a handler needs a narrower dedicated role.

### Gracenote IAM Roles

The Gracenote coordinator has a dedicated role with:

- `sqs:SendMessage` and `sqs:GetQueueAttributes` on the Gracenote refresh queue
- DynamoDB `GetItem` and `Query`

The Gracenote worker has a dedicated role with:

- `secretsmanager:GetSecretValue` on only the Gracenote secret
- DynamoDB read/write permissions on the app table and GSIs
- SQS consume/delete/change-visibility permissions on the Gracenote refresh queue

Do not give the coordinator access to the Gracenote API key.

## API Handler Matrix

| Route | Terraform Lambda | Source status | Notes |
| --- | --- | --- | --- |
| `GET /movies/search` | `cmc-movie-search-lambda` | Missing | Search external movie API and return selectable movie metadata. Needs API-key/secret design for the provider. |
| `POST /clubs/{clubId}/movie-nights` | `cmc-create-movie-night-lambda` | Missing | Admin-only create flow. Persist movie snapshot and active movie-night records. |
| `GET /clubs/{clubId}/movie-nights/active` | `cmc-get-active-movie-night-lambda` | Missing | Return current planning/voting/confirmed state for homepage. |
| `GET /clubs/{clubId}/movie-nights/history` | `cmc-list-history-lambda` | Missing | Query completed movie nights by club. |
| `POST /movie-nights/{movieNightId}/showtimes` | `cmc-manage-showtimes-lambda` | Missing | Admin adds or approves candidate showtimes for voting. |
| `PUT /movie-nights/{movieNightId}/vote` | `cmc-submit-vote-lambda` | Missing | Authenticated ranked-choice vote create/update. |
| `GET /movie-nights/{movieNightId}/vote-results` | `cmc-vote-results-lambda` | Missing | Calculate ranked-choice point totals and return standings. |
| `POST /movie-nights/{movieNightId}/confirm` | `cmc-confirm-showtime-lambda` | Missing | Admin confirms final showtime and closes voting. |
| `PUT /movie-nights/{movieNightId}/rsvp` | `cmc-update-rsvp-lambda` | Missing | Member RSVP and ticket purchase status updates. |
| `POST /admin/showtimes/gracenote/refresh` | `cmc-gracenote-showtime-coordinator-lambda` | Implemented | Enqueues a Gracenote refresh job. Cognito + API key protected. |
| `POST /admin/selection` | `cmc-admin-selection-lambda` | Exists, legacy shape | Enqueues 14 AMC scrape messages. Uses `lambda_handler`, but Terraform expects `app.handler`. |
| `GET /selection` | `cmc-get-selection-lambda` | Exists, legacy shape | Scans legacy showtime records. |
| `GET /options` | `cmc-get-options-lambda` | Exists, legacy shape, bug | Builds `all_results` but returns the last `item`/`theaters` only. |
| `POST /vote` | `cmc-vote-handler` | Missing | Legacy endpoint exists in Terraform, but no matching source directory was found. |

## Required Source Updates

### Fix Handler Name Mismatch

Terraform expects `app.handler` for every Lambda. `admin-selection-lambda/app.py` currently defines `lambda_handler`, not `handler`.

Update one of these before deployment:

```python
def handler(event, context):
    ...
```

or:

```python
handler = lambda_handler
```

### Replace Placeholder Packages

Each Lambda directory should produce a zip with `app.py` at the zip root, plus dependencies installed at the zip root. For example:

```text
cmc/gracenote-showtime-worker-lambda/lambda.zip
  app.py
  requests/
  botocore is not required because AWS provides boto3/botocore in the runtime
```

Then update Terraform to use real artifacts. Prefer a `local.lambda_artifacts` map or explicit variables rather than hardcoding every source path repeatedly.

Example target shape:

```hcl
filename         = var.lambda_zip_paths.gracenote_showtime_worker
source_code_hash = filebase64sha256(var.lambda_zip_paths.gracenote_showtime_worker)
```

`source_code_hash` is important so Terraform detects source updates.

### Fix Legacy DynamoDB Shapes

`db.tf` defines a single-table schema with `PK` and `SK`. These legacy handlers need updates:

- `movie-scraper-lambda` currently writes items with only `movieId`, `showDate`, and `theaters`, which will fail against the Terraform table because `PK` and `SK` are required.
- `get-selection-lambda` and `get-options-lambda` scan for legacy item shapes and should query keyed records instead.
- `admin-selection-lambda` has `APP_TABLE_NAME` available but currently only uses SQS.

If the legacy AMC scraper remains, write records under a provider cache key, for example:

```text
PK = SHOWTIME_CACHE#PROVIDER#amc#MOVIE#{movieId}#DATE#{showDate}
SK = THEATER#{theaterSlug}
```

Then update readers to query by `PK` instead of scanning.

### Add Shared API Utilities

The new API handlers should share small helpers for:

- API Gateway JSON responses and CORS headers
- JSON body parsing and validation errors
- Cognito claim extraction from `event.requestContext.authorizer.claims`
- role checks for Admin/Friend/Guest
- DynamoDB Decimal JSON serialization
- conditional writes and optimistic concurrency where needed

Keep the shared code copyable into each zip, or package it as a small internal module included in each Lambda artifact.

## Proposed Data Model

Use stable single-table records that line up with the PRD and the API routes.

### Club

```text
PK = CLUB#{clubId}
SK = META
GSI1PK = USER#{userId}
GSI1SK = CLUB#{clubId}
```

### Club Membership

```text
PK = CLUB#{clubId}
SK = MEMBER#{userId}
role = admin | friend | guest
```

### Movie Night

```text
PK = CLUB#{clubId}
SK = MOVIE_NIGHT#{movieNightId}
GSI1PK = CLUB#{clubId}#STATUS#{status}
GSI1SK = START#{targetDate}#MOVIE_NIGHT#{movieNightId}
GSI2PK = MOVIE_NIGHT#{movieNightId}
GSI2SK = META
```

Statuses should include:

- `planning`
- `voting`
- `confirmed`
- `completed`
- `cancelled`

### Candidate Showtime

```text
PK = MOVIE_NIGHT#{movieNightId}
SK = SHOWTIME#{showtimeId}
GSI1PK = MOVIE_NIGHT#{movieNightId}#SHOWTIMES
GSI1SK = START#{startsAtUtc}#SHOWTIME#{showtimeId}
```

Store provider fields such as `provider`, `providerMovieId`, `providerTheaterId`, `ticketURI`, `screenFormat`, and `quals`.

### Vote

```text
PK = MOVIE_NIGHT#{movieNightId}
SK = VOTE#{userId}
GSI1PK = MOVIE_NIGHT#{movieNightId}#VOTES
GSI1SK = USER#{userId}
```

Store ranked showtime IDs:

```json
{
  "rankings": ["showtime-a", "showtime-b", "showtime-c"]
}
```

### RSVP

```text
PK = MOVIE_NIGHT#{movieNightId}
SK = RSVP#{userId}
GSI1PK = MOVIE_NIGHT#{movieNightId}#RSVPS
GSI1SK = STATUS#{status}#USER#{userId}
```

## New Handler Responsibilities

### `movie-search-lambda`

- Require Cognito auth.
- Accept `query`, optional `year`, and optional pagination params.
- Search the configured movie provider.
- Return normalized movie cards with external ID, title, poster URL, overview, runtime when available, release date/year, genres, and provider.
- Do not persist search results unless caching is intentionally added.

### `create-movie-night-lambda`

- Require Admin role for `clubId`.
- Validate movie metadata snapshot and target planning fields.
- Ensure only one active movie night per club for MVP.
- Create the movie-night record with status `planning`.
- Return the created movie night.

### `get-active-movie-night-lambda`

- Require membership in the club.
- Query active statuses for the club.
- Return movie metadata, candidate showtimes, current user vote, current user RSVP, and confirmed showtime if present.

### `manage-showtimes-lambda`

- Require Admin role for the movie night.
- Accept manually entered showtimes or selected cached Gracenote showtimes.
- Persist candidate showtime records.
- Transition `planning` to `voting` when requested.

### `submit-vote-lambda`

- Require membership in the movie night club.
- Reject votes after `votingClosesAt`.
- Validate every ranked showtime belongs to the movie night.
- Upsert the user vote with a conditional write.

### `vote-results-lambda`

- Require membership in the movie night club.
- Query votes and showtimes.
- Calculate ranked-choice point totals. A simple MVP scoring model can be `N` points for first choice, `N-1` for second, etc.
- Return sorted results and vote count.

### `confirm-showtime-lambda`

- Require Admin role.
- Validate selected showtime belongs to the movie night.
- Set status to `confirmed`, save `confirmedShowtimeId`, and preserve the final result snapshot.

### `update-rsvp-lambda`

- Require membership in the movie night club.
- Allow `yes`, `no`, and `maybe`.
- Track `ticketPurchased` as a boolean.
- Upsert the user's RSVP record.

### `list-history-lambda`

- Require membership in the club.
- Query completed movie nights for the club.
- Return compact history cards with movie title, poster, date, theater, attendance count, and result summary.

## Gracenote Source Handoff

Source exists for:

- `gracenote-showtime-coordinator-lambda/app.py`
- `gracenote-showtime-worker-lambda/app.py`

The coordinator:

- accepts EventBridge, API Gateway, or direct invoke events
- validates `zip`, `radius`, `numDays`, `units`, and `startDate`
- enqueues one SQS message to `SHOWTIME_REFRESH_QUEUE_URL`
- returns an API Gateway-compatible response for API invokes

The worker:

- processes SQS batches with partial batch failure response
- reads the API key from `GRACENOTE_SECRET_ARN`
- calls Gracenote server-side
- normalizes showtimes into the app table
- writes cache records with `PK`, `SK`, `GSI1PK`, `GSI1SK`, and `expiresAt`

Keep these safety rules:

- Never commit the Gracenote API key.
- Never put the key in Terraform variables or Lambda env vars.
- Never log a URL containing `api_key`.
- Keep the secret value in Secrets Manager and read it at runtime.

Current Gracenote cache key:

```text
PK = SHOWTIME_CACHE#PROVIDER#gracenote#ZIP#{zip}#DATE#{yyyy-mm-dd}
SK = MOVIE#{tmsId}#THEATER#{theatreId}#START#{localDateTime}#FORMAT#{qualifierHash}
GSI1PK = MOVIE#GRACENOTE#{tmsId}
GSI1SK = START#{startsAtUtc}#THEATER#{theatreId}
```

## Testing Checklist

Add or keep tests for:

- API Gateway event parsing and JSON response shape
- Cognito claim extraction and authorization failures
- missing/invalid request body fields
- DynamoDB key construction
- conditional write failures
- vote scoring and tie behavior
- SQS partial batch failures for worker Lambdas
- Gracenote API retryable vs non-retryable errors
- secret parsing for string and JSON secret values

Existing tests were found only for the two Gracenote handlers.

## Deployment Checklist

1. Build each Lambda zip from its source directory.
2. Ensure each zip has `app.py` at the zip root.
3. Update `lambda.tf` to use real zip paths and `source_code_hash`.
4. Run Terraform plan and confirm every Lambda package diff is intentional.
5. Populate `/cmc/production/gracenote/api-key` in Secrets Manager outside Terraform.
6. Deploy infrastructure.
7. Invoke smoke tests:

```text
POST /admin/showtimes/gracenote/refresh
GET /movies/search
POST /clubs/{clubId}/movie-nights
GET /clubs/{clubId}/movie-nights/active
```

8. Check CloudWatch logs for handler import errors, missing env vars, and DynamoDB validation failures.

## Open Decisions

- Whether to keep the legacy AMC scraping flow after Gracenote ingestion is available.
- Which movie search provider backs `movie-search-lambda`.
- Whether Lambda artifacts are built manually, by CI, or by Terraform `archive_file`.
- Whether shared code is vendored into each Lambda zip or moved into a Lambda layer.
- The exact Cognito group/claim convention for Admin, Friend, and Guest roles.
