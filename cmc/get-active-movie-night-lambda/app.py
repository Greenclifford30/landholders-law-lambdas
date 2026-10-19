from cmc_shared import ApiError, active_pointer, claims, handle, path_param, require_membership, response
from cmc_events import event_detail


@handle
def handler(event, context):
    club_id = path_param(event, "clubId")
    user = claims(event)
    membership = require_membership(club_id, user["userId"])
    night = active_pointer(club_id)
    if not night:
        raise ApiError(404, "No active movie night exists for this club.")
    return response(200, event_detail(night, membership, user["userId"]))
