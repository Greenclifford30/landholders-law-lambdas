from cmc_shared import ApiError, claims, handle, parse_body, path_param, require_membership, response
import cmc_proposals as proposals


@handle
def handler(event, context):
    user = claims(event)
    club_id = path_param(event, "clubId")
    membership = require_membership(club_id, user["userId"], proposals.ROLES)
    method = event.get("httpMethod", "GET").upper()
    path = (event.get("path") or event.get("resource") or "").rstrip("/")
    identifier = (event.get("pathParameters") or {}).get("proposalId")
    if not identifier:
        if method == "GET":
            return response(200, proposals.list_proposals(club_id, user["userId"], event))
        if method == "POST":
            return response(201, {"proposal": proposals.create(club_id, user, membership, parse_body(event))})
    elif path.endswith("/endorsement") and method in {"PUT", "DELETE"}:
        return response(200, {"proposal": proposals.endorse(club_id, identifier, user, membership, method == "PUT")})
    elif path.endswith("/schedule") and method == "POST":
        if membership["role"] != "admin":
            raise ApiError(403, "Only club admins may schedule proposals.")
        return response(200, proposals.schedule(proposals.load(club_id, identifier), user, membership, parse_body(event)))
    elif method == "PATCH":
        return response(200, {"proposal": proposals.update(proposals.load(club_id, identifier), user, membership, parse_body(event))})
    raise ApiError(405, "Method not allowed.")
