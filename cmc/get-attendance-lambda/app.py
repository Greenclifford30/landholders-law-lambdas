from cmc_shared import (
    ADMIN_ROLES,
    claims,
    club_pk,
    handle,
    list_rsvps,
    path_param,
    query_items,
    require_movie_night_membership,
    response,
)


@handle
def handler(event, context):
    movie_night_id = path_param(event, "movieNightId")
    user = claims(event)
    movie_night, _membership = require_movie_night_membership(movie_night_id, user["userId"], ADMIN_ROLES)
    memberships = query_items(club_pk(movie_night["clubId"]), "MEMBER#")
    rsvps = {item["userId"]: item for item in list_rsvps(movie_night_id)}
    members = []
    summary = {
        "totalMembers": 0,
        "going": 0,
        "maybe": 0,
        "notGoing": 0,
        "pending": 0,
        "purchased": 0,
        "notPurchased": 0,
    }
    for membership in memberships:
        if membership.get("status", "active") != "active":
            continue
        user_id = membership["userId"]
        rsvp = rsvps.get(user_id) or {}
        rsvp_status = rsvp.get("status", "pending")
        ticket_status = rsvp.get("ticketStatus", "not_purchased")
        summary["totalMembers"] += 1
        summary[{"not_going": "notGoing"}.get(rsvp_status, rsvp_status)] += 1
        if ticket_status == "purchased":
            summary["purchased"] += 1
        else:
            summary["notPurchased"] += 1
        members.append(
            {
                "userId": user_id,
                "name": membership.get("name") or "",
                "email": membership.get("email") or "",
                "role": membership.get("role") or "friend",
                "rsvpStatus": rsvp_status,
                "ticketStatus": ticket_status,
                "updatedAt": rsvp.get("updatedAt"),
            }
        )
    members.sort(key=lambda item: ((item["name"] or item["email"]).lower(), item["userId"]))
    return response(200, {"summary": summary, "members": members})
