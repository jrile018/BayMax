"""Assigned, role-bound authority at the intake API boundary."""

import hashlib
import secrets
import unittest

from services.arrival_intake.auth import Unauthorized, authenticate
from services.arrival_intake.contracts import Forbidden, Principal
from services.arrival_intake.policy import authorize


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_hex(32)
        self.registry = {
            hashlib.sha256(self.token.encode("ascii")).hexdigest(): {
                "actor_id": "volunteer-a",
                "role": "volunteer",
                "session_ids": ["session-a"],
            }
        }

    def test_bearer_token_resolves_only_registry_identity(self):
        principal = authenticate("Bearer " + self.token, self.registry)
        self.assertEqual(principal, Principal("volunteer-a", "volunteer", frozenset({"session-a"})))

    def test_missing_malformed_and_unregistered_tokens_are_unauthorized(self):
        for header in (None, "", "Basic " + self.token, "Bearer", "Bearer ",
                       "Bearer " + secrets.token_hex(32), "Bearer " + self.token + " extra"):
            with self.subTest(header=header), self.assertRaises(Unauthorized):
                authenticate(header, self.registry)

    def test_raw_token_is_not_a_registry_key(self):
        with self.assertRaises(Unauthorized):
            authenticate("Bearer " + self.token, {self.token: self.registry[next(iter(self.registry))]})


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.sid = "session-a"
        self.volunteer = Principal("volunteer-a", "volunteer", frozenset({self.sid}))
        self.coordinator = Principal("coordinator-a", "coordinator", frozenset({self.sid}))
        self.reviewer = Principal("reviewer-a", "care_reviewer", frozenset({self.sid}))

    def test_all_roles_are_bound_to_assigned_session(self):
        actions = ("read_intake", "read_detail", "read_photo", "read_aggregate",
                   "confirm_arrival", "attach_photo", "report_concern",
                   "request_assessment", "finish_intake", "correct_attendance",
                   "read_reviews", "complete_review")
        for principal in (self.volunteer, self.coordinator, self.reviewer):
            for action in actions:
                with self.subTest(role=principal.role, action=action), self.assertRaises(Forbidden):
                    authorize(principal, action, "session-b")

    def test_volunteer_can_intake_but_not_correct_or_complete_review(self):
        for action in ("read_intake", "read_detail", "read_photo", "confirm_arrival",
                       "attach_photo", "report_concern", "request_assessment", "finish_intake"):
            with self.subTest(action=action):
                self.assertIsNone(authorize(self.volunteer, action, self.sid))
        for action in ("correct_attendance", "complete_review", "read_reviews"):
            with self.subTest(action=action), self.assertRaises(Forbidden):
                authorize(self.volunteer, action, self.sid)

    def test_coordinator_can_correct_but_not_perform_volunteer_or_reviewer_writes(self):
        for action in ("read_intake", "read_detail", "read_photo", "read_aggregate",
                       "correct_attendance"):
            with self.subTest(action=action):
                self.assertIsNone(authorize(self.coordinator, action, self.sid))
        for action in ("confirm_arrival", "attach_photo", "report_concern",
                       "request_assessment", "finish_intake", "complete_review"):
            with self.subTest(action=action), self.assertRaises(Forbidden):
                authorize(self.coordinator, action, self.sid)

    def test_reviewer_can_close_review_but_not_change_attendance_or_assessment(self):
        for action in ("read_intake", "read_detail", "read_photo", "read_reviews",
                       "complete_review"):
            with self.subTest(action=action):
                self.assertIsNone(authorize(self.reviewer, action, self.sid))
        for action in ("confirm_arrival", "attach_photo", "report_concern",
                       "request_assessment", "finish_intake", "correct_attendance"):
            with self.subTest(action=action), self.assertRaises(Forbidden):
                authorize(self.reviewer, action, self.sid)

    def test_volunteer_cannot_finish_care_review(self):
        with self.assertRaises(Forbidden):
            authorize(self.volunteer, "complete_review", self.sid)

    def test_unknown_action_is_denied(self):
        with self.assertRaises(Forbidden):
            authorize(self.coordinator, "new_privilege", self.sid)


if __name__ == "__main__":
    unittest.main()
