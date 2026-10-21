# Film suggestions and concurrent nights

Implemented locally October 19, 2026; Phase 2 extended October 21, 2026. AWS deployment and authenticated smoke tests remain outstanding.

## API contracts

All routes require Cognito authentication and active membership in the owning club. Browser requests continue through `/api/backend`. Suggestion routes and the new club-wide night listing require an admin or friend role; guests keep their existing event detail permissions. Membership reads use consistent reads. Proposal writes additionally condition-check the actor's current role/status in the same transaction.

| Method and route | Request | Response |
| --- | --- | --- |
| GET `/clubs/:clubId/movie-proposals` | `status` (default `open`), `cursor`, `limit` | `{proposals,nextCursor}` |
| POST `/clubs/:clubId/movie-proposals` | `{provider:"tmdb",externalId,reason?}` | `201 {proposal}` |
| PATCH `/clubs/:clubId/movie-proposals/:proposalId` | `{version,reason?,status?,moderationReason?}` | `{proposal}` |
| PUT / DELETE `/clubs/:clubId/movie-proposals/:proposalId/endorsement` | Empty | `{proposal}` |
| POST `/clubs/:clubId/movie-proposals/:proposalId/schedule` | Existing event planning fields plus `version,idempotencyKey` | `{proposal,movieNight}` |
| GET `/clubs/:clubId/movie-nights` | `scope=upcoming`, `cursor`, `limit` | `{movieNights,nextCursor}` |
| GET `/movie-nights/:movieNightId` | None | Existing active-night detail shape, including viewer role/vote/RSVP and permitted showtimes |

Proposal states are `open`, `scheduled`, `withdrawn`, and `dismissed`. Authors can change their reason or withdraw an open suggestion. Admins can dismiss it with a required moderation reason, with actor/time recorded. Moderators cannot rewrite another author's reason. Reasons are limited to 1,000 characters. Unknown client permission fields never grant access.

TMDB details are resolved on the backend. Duplicate open films return `409 {error,existingProposalId}`. Conflicting versions/transitions return `409`; invalid inputs return `400`. Provider failures leave no proposal/claim records. Endorsements start empty; proposing does not automatically endorse.

Endorsements are unique per user/proposal and updated atomically with the proposal version. Counts exclude inactive or departed members and users whose role no longer permits club-wide participation. Their endorsement records remain for attribution; counts are computed from current membership. Display names come from current membership, with `Former member` for departed authors; email addresses are not returned. Rejoining with the same user ID restores their existing endorsement unless they remove it.

Scheduling is an admin operation. A single transaction creates the night and any monitoring record, updates the versioned proposal, releases the open-film claim, and stores the idempotency result. Retry the exact body and key to recover the same night, including after a timeout. Reusing a key with changed input returns `409`. Competing scheduling requests cannot create a second night from the same suggestion. Cancelling the night leaves the suggestion scheduled. Hosts can propose the film again explicitly.

Ordinary night creation accepts an optional `idempotencyKey`; initial success returns `201`, an identical retry returns `200`, and changed input with the same key returns `409`. Existing callers without a key remain supported. Night IDs are allocated server-side; use the retry key rather than supplying a movie-night ID.

## Storage and access paths

The existing DynamoDB table and GSI1/GSI2 are retained. No index backfill or table migration is required.

| Record | PK | SK |
| --- | --- | --- |
| Proposal | `CLUB#clubId` | `PROPOSAL#proposalId` |
| Unique open-film claim | `CLUB#clubId` | `OPEN_FILM#tmdb#externalId` |
| Endorsement | `PROPOSAL#proposalId` | `ENDORSEMENT#userId` |
| Schedule retry record | `PROPOSAL#proposalId` | `SCHEDULE#sha256(key)` |
| Ordinary creation retry | `CLUB#clubId` | `CREATE_NIGHT#sha256(key)` |

Claims use provider-canonical IDs. Conditional writes and transactions provide uniqueness and optimistic concurrency. Schedule keys are scoped to a proposal; ordinary creation keys are scoped to a club. Retry records currently have no TTL, preserving retry behavior after event completion/cancellation. Proposal-linked nights include `proposalId` and `proposedByUserId`.

Listing queries existing club partitions, following all DynamoDB pages, then sorts and paginates in the service. Proposal ranking is endorsement count descending, then creation time and ID ascending. Limits default to 50, maximum 100; `nextCursor` is null at the end. Cursors are opaque, validated, and bound to the club and status/scope. These are live rankings: endorsements between page requests can move rows, so pagination does not promise snapshot consistency. Full partition reads and per-proposal endorsement queries are suitable for the current small-club workload; measure before introducing a materialized ranking index.

## Concurrent-event compatibility

`ACTIVE_MOVIE_NIGHT` records are retained but no longer read or written as authoritative state by updated handlers. Legacy `/active` responses are selected from actual nonterminal nights: confirmed first by confirmed start (fallback target date), then dated voting/planning nights, then undated plans, with ID tie-breaking. Past confirmed nights remain visible until completed or cancelled.

Club responses include `upcomingNightCount`, `nextMovieNight`, and derived `activeStatus`. Event details retain existing showtime visibility rules and participant payloads. Completion, cancellation, confirmation, and showtime changes operate on the specified night without requiring a shared pointer. Existing event records remain readable without rewriting them.

Monitoring, notification outbox IDs, reminders, and calendar identities already include movie-night IDs. The monitoring and reminder workers recheck each event's status, suppressing work for terminal events. Notification links now target `/clubs/:clubId/movie-nights/:movieNightId`, which reuses the existing member event page. Showtime-ready host emails target the corresponding `/clubs/:clubId/movie-nights/:movieNightId/admin` route, which reuses the existing admin workspace. The frontend now includes the schedule, personal agenda, explicit new-event creation, event navigation, and proposal scheduling controls.

## Validation and deployment

From the Lambda repository run `python3 -m unittest discover -s cmc/tests` and `python3 -m pytest cmc --import-mode=importlib -q`. The tests cover transactional interleavings using an in-memory DynamoDB test double; authenticated AWS smoke checks remain necessary to validate IAM, API Gateway, real provider responses, and deployed transaction behavior.

From the frontend run `npm run lint`, `npm test`, and `npm run build`. When Turbopack cannot bind a worker port in a restricted environment, use `npx next build --webpack` for additional validation and report the original build limitation.

From the Terraform repository run `terraform fmt -check` on changed module files, `terraform init -backend=false` for local provider setup, and `terraform validate`. Before deployment, run a normal plan in the real root module/workspace and review it; local validation is not an AWS plan.

Deployment order (not performed by this implementation):

1. Coordinate a short backend maintenance window so old single-active handlers and new independent-event handlers do not process writes together. Preserve existing data and take the normal backup/checkpoint.
2. Apply the reviewed Terraform changes from the existing root module/workspace. This creates proposal/list Lambdas, their configuration/permissions/logs, and authenticated API routes. New Lambda resources initially contain the repository's placeholder ZIP.
3. Deploy the new `cmc/manage-movie-proposals-lambda` and `cmc/list-movie-nights-lambda` artifacts and every existing CMC handler that consumes shared modules, including event lifecycle, club, membership, movie search, and notification handlers. Both packaging scripts now copy every shared Python module. The CI workflow already discovers new Lambda folders and rebuilds CMC handlers when shared modules change.
4. Smoke-test with two admins and two friends: simultaneous duplicate suggestions; repeated endorsements; withdrawal/dismissal; scheduling retry; two additional nights with independent ballots/RSVPs; complete/cancel one and verify the other nights and `/active`; remove membership and verify immediate access denial. Check monitoring/reminders and event-specific notification/calendar links. Verify guest restrictions and attempts across clubs.
5. Deploy the frontend contract/deep-link changes, verify proxy requests and direct event URLs, and end maintenance. Include the Phase 2 frontend and shared handlers in the same maintenance window.

Rollback requires redeploying a mutually compatible handler set. Do not restore single-active handlers while parallel nights remain active: resolve those nights first or retain the compatibility-selection/event-isolation changes. New proposal records may remain stored during rollback; do not delete club/event data to roll back code.

## Local validation results — October 19, 2026

- Backend: 94 tests and 11 subtests passed with pytest, including provider workers and collaboration handlers; the focused unittest suite contains 82 passing tests.
- Frontend: all 27 tests passed; ESLint and the production Next.js build passed. Build execution required permission for Next.js to open its local worker port. The existing admin page was extracted into a client component so page modules expose only supported Next.js exports, and both admin URLs share the same implementation.
- Terraform: changed module files pass `fmt -check`; an isolated copy of the CMC module passes `validate` with the root repository's pinned AWS provider 5.88.0. Validation used local provider schemas and did not contact AWS. No Terraform plan/apply or authenticated smoke test was performed.


## Phase 2 contracts and storage — October 21, 2026

- `GET /me/movie-nights` supports `scope=upcoming|recent`, cursor/limit pagination, current memberships, club names, viewer participation/acknowledgement, next actions, and advisory conflicts. Recent includes completed nights in the preceding 30 days. Club-wide aggregation excludes guests, preserving their existing direct-event permissions. Membership GSI pages are followed, then current memberships are re-read consistently.
- `PATCH /movie-nights/:movieNightId` accepts planning changes and a required entity `version`. Only admins may edit planning nights. Existing showtime setup actions remain compatible, condition-check event state/version, lock films once voting starts, and atomically remove old-film candidates/ballots and replace monitoring when the film changes. Oversized replacements return 409 rather than partially deleting records; create a new night instead.
- `PUT /movie-nights/:movieNightId/plan-acknowledgement/me` accepts the current `planRevision`, for confirmed/cancelled nights. Acknowledgement is stored independently at `MOVIE_NIGHT#id / ACK#userId`; it never updates RSVP/ticket records.
- Confirmation accepts `expectedVersion`, `idempotencyKey`, and optional `changeReason` (up to 1,000 characters). Cancellation/completion accept expected version and a retry key. Legacy bodies remain supported; new UI supplies versions. A changed confirmed theater/time/format advances plan revision and calendar sequence, preserves `previousPlan`, and records an audit entry. Equivalent snapshots are no-ops even when showtime IDs differ; changing the same showtime ID's material snapshot is a real change.
- RSVP now accepts `planRevision` and stores `rsvpPlanRevision`/`ticketPlanRevision`. Missing revisions are accepted only for initial revision one. Old responses remain stored, but host attendance treats stale commitments as pending and exposes prior values plus review flags. RSVP and ballot transactions check the event and current membership.
- Existing records need no rewrite: missing entity version means zero; existing confirmed plans and legacy participation mean revision one. Reads expose these defaults. The existing confirmed-first `/active` ordering is preserved, while schedule/agenda ordering compares UTC instants and date-only plans in their event timezone.

Lifecycle transactions write the event, `AUDIT#version`, `RETRY#userId#action#sha256(key)` result, milestone outbox record, and applicable reminder together, condition-checking the actor's membership. Failed transactions leave no partial plan or notification. Retry results have no TTL. Changed input with the same key returns 409; equivalent confirmations store the retry result without changing revisions or notices. Completion preserves plan/calendar revisions. Cancellation advances both, closes participation, and retains the confirmed snapshot for a cancelled calendar download using the same UID.

Outbox and reminder records carry calendar/plan revisions. Notification workers suppress superseded milestones and obsolete reminders, exclude removed members, and include stale-RSVP members in current-plan reminders. Provider work carries an event version and rechecks event status/version before importing results or continuing monitoring. The existing asynchronous delivery and channel retry mechanism remains; outbox deduplication does not promise exactly-once delivery from an external email provider.

The three added API routes reuse `list_movie_nights`, Cognito authorization, and existing DynamoDB transaction permissions. Deploy the complete compatible handler set (including the newly shared `cmc_lifecycle.py`, provider worker and monitor) before enabling the frontend. The frontend's `docs/phase-2-collaboration.md` contains the complete deployment/rollback and smoke-test checklist. No AWS operations were performed locally.


## Phase 2 local validation results — October 21, 2026

- `python3 -m pytest cmc --import-mode=importlib -q`: 115 tests and 11 subtests passed, including provider workers.
- `python3 -m unittest discover -s cmc/tests`: 103 tests passed.
- Terraform collaboration routes pass formatting and validation against the current complete CMC module with the pinned AWS provider 5.88.0. Initialization used the local provider cache and `-backend=false`; validation required permission for the provider's local plugin socket. No Terraform plan/apply or AWS calls were performed.
- Frontend validation and the deployment handoff are documented in `cmc/chi-movie-club/docs/phase-2-collaboration.md` in the frontend workspace.
