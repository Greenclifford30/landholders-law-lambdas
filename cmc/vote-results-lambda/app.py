from cmc_shared import (
    claims,
    handle,
    list_showtimes,
    list_votes,
    path_param,
    public_movie_night,
    require_movie_night_membership,
    response,
)


POINTS_BY_RANK = {0: 3, 1: 2, 2: 1}


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    require_movie_night_membership(movie_night_id, user["userId"])
    showtimes = {item["showtimeId"]: item for item in list_showtimes(movie_night_id)}
    totals = {
        showtime_id: {
            "showtimeId": showtime_id,
            "points": 0,
            "firstChoiceVotes": 0,
            "rankedVotes": 0,
            "showtime": public_movie_night(showtime),
        }
        for showtime_id, showtime in showtimes.items()
    }
    votes = list_votes(movie_night_id)
    for vote in votes:
        for index, showtime_id in enumerate(vote.get("rankings") or []):
            if showtime_id not in totals:
                continue
            totals[showtime_id]["points"] += POINTS_BY_RANK.get(index, 0)
            totals[showtime_id]["rankedVotes"] += 1
            if index == 0:
                totals[showtime_id]["firstChoiceVotes"] += 1
    standings = sorted(
        totals.values(),
        key=lambda row: (row["points"], row["firstChoiceVotes"], row["rankedVotes"]),
        reverse=True,
    )
    return response(200, {"voteCount": len(votes), "standings": standings})
