# Movie Club PRD

## 1. Product Overview

Movie Club is a collaborative web application for planning movie outings with friends, clubs, and groups. The app helps a group select a movie, evaluate available showtimes, vote using ranked-choice preferences, RSVP to the final plan, and maintain a history of past movie nights.

The MVP will focus on a single active movie night per club, where an admin selects a movie, adds or imports candidate showtimes, invites members, collects ranked-choice votes, confirms the final showtime, and tracks attendance/ticket status.

## 2. Product Goals

### Primary Goal

Enable friend groups and movie clubs to collaboratively plan a movie outing with less coordination friction.

### Secondary Goals

* Support multiple independent clubs/groups over time.
* Allow admins to control whether the movie is selected by the admin or voted on by the group.
* Provide a clean homepage experience that changes based on the event state: planning, voting, confirmed, completed.
* Preserve historical movie nights for each club.
* Build a foundation that can later support recurring movie nights, richer social features, reminders, and deeper theater/showtime integrations.

## 3. Current Application Baseline

The current application has:

* A home page that displays the selected movie.
* Movie details fetched from TMDB using a stored movie ID.
* A hardcoded list of Chicago-area theaters and showtimes.
* A ranked-choice voting UI for theater + showtime combinations.
* A simple friend voting summary.
* A confirm movie night action.
* An admin flow where a movie can be selected.

The new PRD should evolve this into a persisted, authenticated, multi-club-capable application.

## 4. Target Users

### Admin / Host

The person responsible for creating and managing a movie night.

Admin responsibilities:

* Create a movie night.
* Select a movie or allow the group to vote on movie options.
* Add, import, or approve candidate showtimes.
* Invite friends or guests.
* Monitor votes.
* Confirm the winning showtime.
* Track RSVP and ticket purchase status.
* Manage recurring movie nights in a later phase.

### Friend / Club Member

A signed-in member of a club who can participate in planning.

Friend responsibilities:

* View the active movie night.
* Review movie metadata and candidate showtimes.
* Vote using ranked-choice preferences.
* Edit their vote before voting closes.
* RSVP after the event is confirmed.
* Mark whether they purchased a ticket.
* Participate in chat or comments when available.

### Guest

A signed-in invited user who may not be a permanent club member.

Guest responsibilities:

* Join through an invite flow.
* Vote and RSVP if permitted.
* Participate in the specific movie night they were invited to.

## 5. MVP Scope

The MVP should support one active movie night per club.

### Included in MVP

* Cognito-based authentication.
* Club/group-ready data model.
* Admin-created movie night.
* Admin-selected movie from movie API search results.
* Movie metadata display.
* Chicago-area showtime collection through API or scraping pipeline.
* Candidate showtime list with theater, date, time, and screen format.
* Ranked-choice showtime voting.
* Editable votes before voting closes.
* Voting closes at least one day before the first available showtime.
* Ranked-choice point-based winner calculation.
* Admin confirmation of final showtime.
* Confirmed movie night view.
* RSVP tracking.
* Ticket purchase status tracking.
* Historical movie night list.

### Not Required for MVP

* Direct ticket purchase links.
* Automated reminders or notifications.
* Full chat experience, unless implemented as a lightweight comments feature.
* Complex multi-movie group voting flow, though the data model should support it.
* Nationwide theater coverage.
* Mobile app.

## 6. Functional Requirements

## 6.1 Authentication and Authorization

### Requirements

* Users must sign in to vote.
* AWS Cognito should be used for authentication.
* User roles should include Admin, Friend, and Guest.
* Admins can manage clubs and movie nights.
* Friends can vote, RSVP, and view club history.
* Guests can participate only in events they are invited to.

### Acceptance Criteria

* A signed-out user cannot submit a vote.
* A signed-in user can view clubs/events they belong to or were invited to.
* Only admins can confirm the final showtime.
* Guests cannot access unrelated club events.

## 6.2 Clubs / Groups

### Requirements

* The app should be designed for multiple clubs/groups.
* Each club can have members and admins.
* Each club can have one active movie night in MVP.
* Historical movie nights should be associated with a club.

### Acceptance Criteria

* A user can belong to multiple clubs.
* A club admin can create a movie night for their club.
* Movie nights are scoped to a specific club.

## 6.3 Movie Night Creation

### Requirements

* Admin can create a new movie night.
* MVP focuses on one selected movie.
* Admin can search an external movie API and select a movie.
* Movie metadata should be saved with the movie night to avoid repeated API dependency for basic display.

### Movie Metadata

* External movie ID.
* Title.
* Poster path or image URL.
* Overview.
* Runtime.
* Release year/date.
* Genres.
* Rating or popularity metadata, if available.

### Acceptance Criteria

* Admin can search for a movie.
* Admin can select a movie from API results.
* The selected movie appears on the movie night homepage.
* Movie metadata is visible to members.

## 6.4 Optional Group Movie Selection

### Requirements

* The architecture should support admin-selected movie as MVP default.
* Admin should eventually be able to allow group voting on movie options.
* In MVP, this can be deferred but should influence the data model.

### Future Acceptance Criteria

* Admin can add multiple movie candidates.
* Friends can vote on movie options.
* Admin can confirm winning movie before showtime voting begins.

## 6.5 Showtime Collection

### Requirements

* Showtime data should be gathered from an API or scraping process.
* MVP should focus on the Chicago area.
* Showtimes should include theater, time, date, and screen format.
* Admin should be able to review and choose which showtimes are available for voting.

### Showtime Fields

* Theater name.
* Theater location.
* Showtime date.
* Showtime start time.
* Screen format, such as IMAX, Dolby, 70mm, standard, subtitles, etc.
* Source provider.
* External showtime ID if available.

### Acceptance Criteria

* Candidate showtimes are attached to a movie night.
* Members can compare theater + showtime combinations.
* Screen formats are visible in the voting UI.
* Ticket purchase links are not required in MVP.

## 6.6 Ranked-Choice Voting

### Requirements

* Users vote on theater + showtime combinations.
* Ranked-choice voting is preferred.
* Users should be able to select top choices in ranked order.
* Users can edit their vote before voting closes.
* Voting closes at least one day before the first available showtime.
* Winner is calculated using ranked-choice points.

### Proposed Scoring

For MVP, use a simple point system:

* 1st choice: 3 points.
* 2nd choice: 2 points.
* 3rd choice: 1 point.

The showtime with the most total points wins.

### Tie-Breakers

Recommended initial tie-break order:

1. Most first-place votes.
2. Most second-place votes.
3. Earliest showtime that still meets the group criteria.
4. Admin final decision.

### Acceptance Criteria

* A signed-in user can submit a ranked vote.
* A user cannot select the same showtime multiple times in one ballot.
* A user can update their ballot before voting closes.
* Votes are locked after voting closes.
* Admin can view ranked-choice totals.
* App can identify a suggested winning showtime.

## 6.7 Confirmation Flow

### Requirements

* Admin can confirm the final movie night.
* Once confirmed, the homepage should switch from voting mode to confirmed mode.
* Confirmed view should clearly show final movie, theater, date, time, and format.

### Acceptance Criteria

* Admin can confirm one showtime.
* Confirmed showtime is visible to members.
* Voting UI is hidden or read-only after confirmation.
* Members can RSVP and mark ticket status after confirmation.

## 6.8 RSVP and Ticket Tracking

### Requirements

* Users can RSVP after the movie night is confirmed.
* Users can track whether they purchased tickets.

### RSVP States

* Going.
* Maybe.
* Not going.
* No response.

### Ticket Status States

* Not purchased.
* Purchased.
* Need help / pending.

### Acceptance Criteria

* A user can update RSVP status.
* A user can update ticket status.
* Admin can view attendance and ticket summary.

## 6.9 Chat / Comments

### Requirements

* A lightweight chat or comment feature is desirable.
* This is not required for MVP unless it is simple to include.

### MVP Option

Implement event comments instead of real-time chat.

### Future Option

Implement real-time chat using AppSync subscriptions, WebSockets, or another real-time service.

## 6.10 History

### Requirements

* Completed movie nights should be saved.
* Users should be able to view historical movie nights for each club.

### Acceptance Criteria

* Completed movie nights remain associated with the club.
* History includes movie, date, theater, showtime, and attendees.

## 7. Non-Functional Requirements

## 7.1 Performance

* Home page should load the active movie night quickly.
* Movie metadata should be denormalized onto the movie night record where useful.
* Voting and RSVP actions should complete quickly and provide clear feedback.

## 7.2 Security

* All voting and RSVP actions require authentication.
* Authorization must enforce club/event membership.
* Admin-only operations must be protected server-side.
* Cognito user identity should be mapped to app-level user and membership records.

## 7.3 Scalability

* Data model should support multiple clubs and multiple users.
* MVP should avoid over-optimizing for large-scale public usage.
* Architecture should not block later migration to more relational storage if needed.

## 7.4 Reliability

* Voting should be persisted durably.
* Admin confirmation should be idempotent and protected against accidental duplicate confirmation.
* Showtime collection failures should not break existing movie night display.

## 8. Storage Recommendation

The app has a mix of relational-style data and event/activity-style data.

### Recommended MVP Storage

Use DynamoDB for MVP with careful single-table or limited-table design.

This fits well because:

* Access patterns are club/event scoped.
* Most reads are key-based: active movie night by club, showtimes by movie night, votes by movie night, RSVP by movie night.
* The app is serverless-friendly.
* It integrates naturally with AWS Amplify, Lambda, and Cognito.
* MVP does not require complex ad hoc querying.

### DynamoDB Is a Good Fit For

* Clubs.
* Memberships.
* Movie nights.
* Candidate showtimes.
* Votes.
* RSVPs.
* Ticket status.
* Event comments.
* Historical event records.

### DynamoDB Risks

DynamoDB requires designing around access patterns up front. Queries like “show me all users who attended movies of a certain genre in the last year” are less natural unless modeled intentionally.

### When PostgreSQL Would Be Better

PostgreSQL would be better if the app quickly grows into:

* Complex reporting.
* Rich filtering/search across many entities.
* Complex relationships between users, clubs, votes, events, and attendance.
* Admin analytics.
* Heavy relational constraints.

### Recommended Decision

Start with DynamoDB for MVP, but keep domain boundaries clean through a service/repository layer. Avoid spreading DynamoDB-specific key logic throughout UI components. This keeps the door open for a future PostgreSQL migration if the app becomes more analytics-heavy.

## 9. Proposed Data Model

## 9.1 Core Entities

### User

Represents an authenticated app user.

Fields:

* userId.
* cognitoSub.
* displayName.
* email.
* createdAt.
* updatedAt.

### Club

Represents a movie club or friend group.

Fields:

* clubId.
* name.
* description.
* createdByUserId.
* createdAt.
* updatedAt.

### ClubMembership

Represents a user's role in a club.

Fields:

* clubId.
* userId.
* role: admin, friend, guest.
* status: active, invited, removed.
* createdAt.
* updatedAt.

### MovieNight

Represents a planned outing.

Fields:

* movieNightId.
* clubId.
* status: draft, voting, voting_closed, confirmed, completed, cancelled.
* selectedMovieId.
* movieSelectionMode: admin_selected or group_vote.
* title.
* votingClosesAt.
* confirmedShowtimeId.
* createdByUserId.
* createdAt.
* updatedAt.

### Movie

Represents selected or candidate movie metadata.

Fields:

* movieId.
* externalProvider: tmdb.
* externalMovieId.
* title.
* overview.
* posterUrl.
* runtimeMinutes.
* releaseDate.
* genres.
* rating.
* metadataSnapshot.

### Showtime

Represents a theater + date/time + format candidate.

Fields:

* showtimeId.
* movieNightId.
* theaterName.
* theaterLocation.
* startsAt.
* screenFormat.
* sourceProvider.
* externalShowtimeId.
* createdAt.
* updatedAt.

### Vote

Represents a user ballot for a movie night.

Fields:

* voteId.
* movieNightId.
* userId.
* rankings: ordered list of showtimeIds.
* submittedAt.
* updatedAt.

### RSVP

Represents attendance and ticket purchase status.

Fields:

* movieNightId.
* userId.
* rsvpStatus.
* ticketStatus.
* updatedAt.

### Comment

Represents lightweight discussion on a movie night.

Fields:

* commentId.
* movieNightId.
* userId.
* body.
* createdAt.
* updatedAt.

## 10. Suggested DynamoDB Access Patterns

### Required Access Patterns

* Get club by ID.
* List clubs for a user.
* Get active movie night for a club.
* Get movie night details.
* List showtimes for a movie night.
* Get current user's vote for a movie night.
* List all votes for a movie night.
* Submit/update vote.
* Confirm winning showtime.
* Get RSVP for current user.
* List RSVPs for a movie night.
* List historical movie nights for a club.
* List comments for a movie night.

### Table Design Option

Use one main DynamoDB application table plus optional secondary indexes.

Example partition/sort key patterns:

* Club metadata: `PK=CLUB#{clubId}`, `SK=METADATA`
* Club membership: `PK=CLUB#{clubId}`, `SK=MEMBER#{userId}`
* User clubs: `PK=USER#{userId}`, `SK=CLUB#{clubId}`
* Movie night: `PK=CLUB#{clubId}`, `SK=MOVIE_NIGHT#{movieNightId}`
* Active movie night pointer: `PK=CLUB#{clubId}`, `SK=ACTIVE_MOVIE_NIGHT`
* Showtime: `PK=MOVIE_NIGHT#{movieNightId}`, `SK=SHOWTIME#{showtimeId}`
* Vote: `PK=MOVIE_NIGHT#{movieNightId}`, `SK=VOTE#{userId}`
* RSVP: `PK=MOVIE_NIGHT#{movieNightId}`, `SK=RSVP#{userId}`
* Comment: `PK=MOVIE_NIGHT#{movieNightId}`, `SK=COMMENT#{createdAt}#{commentId}`

Recommended GSIs:

* `GSI1PK=USER#{userId}`, `GSI1SK=CLUB#{clubId}` for listing user clubs.
* `GSI2PK=CLUB#{clubId}`, `GSI2SK=STATUS#{status}#DATE#{createdAt}` for history and event listing.

## 11. API Requirements

## 11.1 Movie Search

### Endpoint

`GET /api/movies/search?query={query}`

### Description

Search external movie provider and return movie candidates.

### Auth

Admin only for MVP.

## 11.2 Create Movie Night

### Endpoint

`POST /api/clubs/{clubId}/movie-nights`

### Description

Create a new movie night for a club.

### Auth

Admin only.

## 11.3 Get Active Movie Night

### Endpoint

`GET /api/clubs/{clubId}/movie-nights/active`

### Description

Return active movie night, selected movie, showtimes, current user's vote, voting status, RSVP status, and confirmation status.

### Auth

Club member or invited guest.

## 11.4 Add or Import Showtimes

### Endpoint

`POST /api/movie-nights/{movieNightId}/showtimes`

### Description

Add showtime candidates manually or from imported provider data.

### Auth

Admin only.

## 11.5 Submit Vote

### Endpoint

`PUT /api/movie-nights/{movieNightId}/vote`

### Description

Create or update current user's ranked-choice vote.

### Auth

Signed-in club member or guest.

## 11.6 Get Vote Results

### Endpoint

`GET /api/movie-nights/{movieNightId}/vote-results`

### Description

Return ranked-choice point totals and suggested winner.

### Auth

Admin initially. Later may be visible to all members.

## 11.7 Confirm Showtime

### Endpoint

`POST /api/movie-nights/{movieNightId}/confirm`

### Description

Confirm final showtime.

### Auth

Admin only.

## 11.8 Update RSVP

### Endpoint

`PUT /api/movie-nights/{movieNightId}/rsvp`

### Description

Update current user's RSVP and ticket purchase status.

### Auth

Signed-in club member or guest.

## 11.9 List History

### Endpoint

`GET /api/clubs/{clubId}/movie-nights/history`

### Description

List completed or past movie nights for the club.

### Auth

Club member.

## 12. Frontend Requirements

## 12.1 Home / Active Movie Night Page

### Planning/Voting State

Show:

* Movie title and poster.
* Movie metadata.
* Voting close time.
* Candidate showtimes.
* Ranked-choice selector.
* Current user's submitted vote.
* Ability to edit vote before close.

### Confirmed State

Show:

* Movie title and poster.
* Final theater.
* Final date/time.
* Screen format.
* RSVP controls.
* Ticket status controls.
* Attendance summary.

### Completed State

Show:

* Final movie night summary.
* Attendance list.
* Historical context.

## 12.2 Admin Page

Admin page should support:

* Create movie night.
* Search/select movie.
* Select movie selection mode.
* Import or add showtimes.
* Open/close voting.
* View vote results.
* Confirm final showtime.
* View RSVP/ticket purchase status.
* Manage recurring movie night settings in a later phase.

## 12.3 Club Pages

MVP can keep club navigation simple but should support:

* Current club context.
* Active movie night.
* Historical movie nights.
* Members list in later phase.

## 13. User Flows

## 13.1 Admin Creates Movie Night

1. Admin signs in.
2. Admin selects a club.
3. Admin creates a movie night.
4. Admin searches for a movie.
5. Admin selects a movie.
6. App saves movie metadata.
7. Admin imports or adds showtimes.
8. Admin opens voting.
9. Members are able to vote.

## 13.2 Friend Votes on Showtime

1. Friend signs in.
2. Friend opens active movie night.
3. Friend reviews movie details and showtime options.
4. Friend ranks top 3 showtimes.
5. Friend submits vote.
6. Friend can edit vote before voting closes.

## 13.3 Admin Confirms Showtime

1. Voting closes automatically at least one day before the first available showtime.
2. Admin views ranked-choice point results.
3. Admin confirms suggested winner or manually selects final showtime.
4. Movie night status changes to confirmed.
5. Home page switches to confirmed view.

## 13.4 Friend RSVPs

1. Friend opens confirmed movie night.
2. Friend selects RSVP status.
3. Friend marks whether ticket is purchased.
4. Admin can view attendance and ticket summary.

## 14. Open Questions

1. Should the first MVP support only one club per user interface, or should users be able to switch between multiple clubs immediately?
2. Should club invites be email-based, invite-code-based, or admin-created accounts?
3. Which showtime source should be used first: official API provider, scraping, or manual admin entry plus future automation?
4. Should vote results be visible to all users or admin-only until confirmation?
5. Should ticket status be private to each user and admin, or visible to the full group?
6. Should comments/chat be included in MVP as simple comments, or deferred entirely?
7. Should recurring movie nights be part of MVP or a post-MVP enhancement?
8. Should the app support multiple candidate movies in MVP as an admin-controlled optional flow, or should that wait until after showtime voting is stable?

## 15. Suggested Implementation Phases

## Phase 1: Foundation

* Add Cognito authentication.
* Create app-level user records.
* Create club and membership model.
* Create active movie night model.
* Replace localStorage selected movie with persisted backend state.

## Phase 2: Movie Selection

* Add admin movie search using external movie API.
* Persist selected movie metadata.
* Display active movie night on homepage.

## Phase 3: Showtime Candidates

* Create showtime storage model.
* Add admin showtime management.
* Start with manual showtime entry if API/scraping is not ready.
* Add showtime source abstraction for later API/scraper integration.

## Phase 4: Ranked-Choice Voting

* Add vote submission and update endpoint.
* Add ranked-choice validation.
* Add scoring service.
* Add admin vote results page.

## Phase 5: Confirmation and RSVP

* Add confirm showtime endpoint.
* Switch homepage to confirmed state.
* Add RSVP and ticket tracking.

## Phase 6: History and Polish

* Add completed movie night history.
* Improve UI states.
* Add lightweight comments if still desired.
* Prepare recurring event support.

## 16. Success Metrics

### MVP Success

* Admin can create a movie night without code changes.
* Friends can sign in and vote.
* Votes persist across sessions.
* Admin can confirm a final showtime.
* Members can RSVP and mark ticket status.
* Completed movie nights are saved in history.

### User Experience Success

* A group can coordinate a movie outing without a separate text-message voting process.
* The current movie night status is obvious when opening the app.
* Users understand what action they need to take: vote, RSVP, buy ticket, or view details.

## 17. Risks and Considerations

### Showtime Data Risk

Movie showtime APIs can be limited, paid, or inconsistent. Scraping may be brittle and may require careful legal and technical review.

Mitigation:

* Start with manual admin showtime entry or semi-automated import.
* Abstract showtime providers behind a service interface.
* Persist showtime snapshots once imported.

### Voting Complexity Risk

Ranked-choice logic can confuse users if the UI is not clear.

Mitigation:

* Use simple top-3 ranking.
* Prevent duplicate selections.
* Explain voting clearly in the UI.
* Show current submitted choices after saving.

### Multi-Club Complexity Risk

Supporting multiple clubs adds authorization and navigation complexity.

Mitigation:

* Model clubs from the start.
* Keep initial UI focused on one selected/default club.
* Add club switching after core planning flow is stable.

## 18. Recommended MVP Definition

The first production-ready MVP should allow an authenticated admin to create a movie night for a club, select one movie from API search results, add or import Chicago-area showtimes with screen formats, allow signed-in friends and guests to rank their top 3 theater/showtime options, calculate ranked-choice point totals, let the admin confirm the final showtime, and allow attendees to RSVP and mark ticket purchase status. Completed events should be saved to club history.
