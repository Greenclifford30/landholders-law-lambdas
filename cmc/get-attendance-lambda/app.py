from cmc_lifecycle import revision
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
        "needsReconfirmation": 0,
        "ticketsNeedReview": 0,
    }
    for membership in memberships:
        if membership.get("status", "active") != "active":
            continue
        user_id = membership["userId"]
        rsvp = rsvps.get(user_id) or {}
        rsvp_status = rsvp.get("status", "pending")
        ticket_status = rsvp.get("ticketStatus", "not_purchased")
        needs_reconfirmation = bool(rsvp) and int(rsvp.get("rsvpPlanRevision", 1)) < revision(movie_night)
        tickets_need_review = bool(rsvp) and int(rsvp.get("ticketPlanRevision", 1)) < revision(movie_night)
        prior_status, prior_ticket = rsvp_status, ticket_status
        if needs_reconfirmation:
            summary["needsReconfirmation"] += 1
            rsvp_status = "pending"
        if tickets_need_review:
            summary["ticketsNeedReview"] += 1
            ticket_status = "not_purchased"
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
                "needsReconfirmation": needs_reconfirmation,
                "ticketsNeedReview": tickets_need_review,
                "priorRsvpStatus": prior_status if needs_reconfirmation else None,
                "priorTicketStatus": prior_ticket if tickets_need_review else None,
            }
        )
    members.sort(key=lambda item: ((item["name"] or item["email"]).lower(), item["userId"]))
    return response(200, {"summary": summary, "members": members})
