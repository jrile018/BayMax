"""Explicit role and session authorization for private intake actions."""

from .contracts import Forbidden, Principal


_ALLOWED = {
    "read_intake": frozenset({"volunteer", "coordinator", "care_reviewer"}),
    "read_detail": frozenset({"volunteer", "coordinator", "care_reviewer"}),
    "read_photo": frozenset({"volunteer", "coordinator", "care_reviewer"}),
    "read_aggregate": frozenset({"coordinator"}),
    "read_history": frozenset({"coordinator"}),
    "confirm_arrival": frozenset({"volunteer"}),
    "attach_photo": frozenset({"volunteer"}),
    "capture_session": frozenset({"volunteer"}),
    "report_concern": frozenset({"volunteer"}),
    "request_assessment": frozenset({"volunteer"}),
    "finish_intake": frozenset({"volunteer"}),
    "correct_attendance": frozenset({"coordinator"}),
    "read_reviews": frozenset({"care_reviewer"}),
    "complete_review": frozenset({"care_reviewer"}),
}


def authorize(principal, action, session_id):
    if (not isinstance(principal, Principal) or session_id not in principal.session_ids
            or principal.role not in _ALLOWED.get(action, ())):
        raise Forbidden("access denied")
