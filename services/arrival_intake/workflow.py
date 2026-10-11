"""Arrival-linked assessment, volunteer observation and human care handoff."""

from dataclasses import asdict
from types import MappingProxyType
from uuid import uuid4

from .assessment import assess
from .contracts import (Assessment, Conflict, bounded_text, canonical_json,
                        nonnegative_int)
from .store import IntakeStore


class ExerciseAssessor:
    """Pure root-configured labels indexed by display number, never request input."""

    def __init__(self, results):
        if not hasattr(results, "items"):
            raise ValueError("exercise labels must be a mapping")
        labels = {}
        for number, result in results.items():
            if type(number) is not int or number < 1 or result not in ("Yes", "No", "Unsure"):
                raise ValueError("invalid exercise label")
            labels[number] = result
        self.results = MappingProxyType(labels)

    def label(self, arrival_number):
        return self.results.get(arrival_number, "Unsure")


class Workflow:
    def __init__(self, store, photo_store, assessor):
        if not isinstance(store, IntakeStore):
            raise TypeError("Workflow requires an IntakeStore")
        if not isinstance(assessor, ExerciseAssessor):
            raise TypeError("Workflow requires a root-configured ExerciseAssessor")
        if photo_store is not None and photo_store.store is not store:
            raise ValueError("photo and workflow stores must share a connection")
        self.store = store
        self.photo_store = photo_store
        self.assessor = assessor

    def for_store(self, store, photo_store):
        """Only immutable exercise configuration crosses the request boundary."""
        return type(self)(store, photo_store, self.assessor)

    def _arrival_locked(self, arrival_id, expected_revision):
        row = self.store._arrival_row(arrival_id)
        if row["revision"] != expected_revision or row["state"] != "confirmed":
            raise Conflict("arrival changed; reload before care decision")
        return row

    def _latest_assessment(self, arrival):
        return self.store.connection.execute(
            "SELECT * FROM assessments WHERE arrival_id=? AND "
            "((capture_id=? AND ? IS NOT NULL) OR (capture_id IS NULL AND ? IS NULL)) "
            "ORDER BY rowid DESC LIMIT 1",
            (arrival["arrival_id"], arrival["current_image_id"], arrival["current_image_id"],
             arrival["current_image_id"])).fetchone()

    def _pending(self, arrival_id):
        return self.store.connection.execute(
            "SELECT * FROM reviews WHERE arrival_id=? AND state='awaiting'",
            (arrival_id,)).fetchone()

    def _refer_locked(self, arrival_id, revision, reason, *, new_evidence):
        pending = self._pending(arrival_id)
        if pending is None:
            self.store.connection.execute(
                "INSERT INTO reviews(review_id,arrival_id,required_revision,state,reason,created_at) "
                "VALUES (?,?,?,'awaiting',?,?)",
                (str(uuid4()), arrival_id, revision, reason, self.store._now()))
        elif new_evidence:
            self.store.connection.execute(
                "UPDATE reviews SET required_revision=?,reason=? WHERE review_id=?",
                (revision, reason, pending["review_id"]))

    def _persist_assessment_locked(self, arrival, assessment, actor_id,
                                   *, allow_equivalent_current=False):
        if (assessment.arrival_id != arrival["arrival_id"] or
                assessment.image_sha256 != arrival["current_image_sha256"]):
            raise Conflict("assessment does not match the current capture")
        if assessment.origin == "evaluated_model":
            raise ValueError("no evaluated model is configured for this demonstration")
        if assessment.origin == "scripted_training" and (
                arrival["current_image_id"] is None or
                assessment.result != self.assessor.label(arrival["display_number"])):
            raise Conflict("scripted assessment does not match root exercise labels")
        if assessment.origin == "unavailable" and assessment.result != "Unsure":
            raise ValueError("unavailable analysis must be Unsure")
        previous = self._latest_assessment(arrival)
        same = (previous is not None and
                all(previous[key] == getattr(assessment, key) for key in
                    ("image_sha256", "origin", "result", "reason", "model_revision")))
        if same:
            if not (assessment.arrival_revision == previous["arrival_revision"] or
                    allow_equivalent_current and assessment.arrival_revision == arrival["revision"]):
                raise Conflict("assessment revision is stale for current capture")
            return self.store.detail(arrival["arrival_id"])
        if assessment.arrival_revision != arrival["revision"]:
            raise Conflict("assessment is stale for current arrival revision")
        revision = arrival["revision"] + 1
        self.store.connection.execute(
            "INSERT INTO assessments(assessment_id,arrival_id,image_sha256,capture_id,"
            "capture_revision,arrival_revision,origin,result,reason,model_revision,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), arrival["arrival_id"], assessment.image_sha256,
             arrival["current_image_id"], arrival["current_image_revision"],
             assessment.arrival_revision, assessment.origin, assessment.result,
             assessment.reason, assessment.model_revision, self.store._now()))
        self.store.connection.execute("UPDATE arrivals SET revision=? WHERE arrival_id=?",
                                      (revision, arrival["arrival_id"]))
        if assessment.result in ("Yes", "Unsure"):
            self._refer_locked(arrival["arrival_id"], revision,
                               "Visible-mark suggestion: " + assessment.result,
                               new_evidence=True)
        self.store._event(arrival["session_id"], arrival["arrival_id"], actor_id,
                          "assessment_recorded", {}, asdict(assessment), assessment.reason)
        return self.store.detail(arrival["arrival_id"])

    def record_assessment(self, assessment, actor_id):
        if not isinstance(assessment, Assessment):
            raise ValueError("assessment must be a validated Assessment")
        bounded_text(actor_id, "actor_id")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            arrival = self.store._arrival_row(assessment.arrival_id)
            if arrival["state"] != "confirmed":
                raise Conflict("only confirmed arrivals can be assessed")
            return self._persist_assessment_locked(arrival, assessment, actor_id)

    def request_assessment(self, arrival_id, expected_revision, actor_id, mode):
        bounded_text(arrival_id, "arrival_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        arrival = self._arrival_locked(arrival_id, expected_revision)
        capture_id, capture_revision = arrival["current_image_id"], arrival["current_image_revision"]
        result = assess(arrival_id, expected_revision, arrival["current_image_sha256"], mode,
                        scripted_result=self.assessor.label(arrival["display_number"])
                        if mode == "scripted" else None)
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            current = self._arrival_locked(arrival_id, expected_revision)
            if (current["current_image_id"] != capture_id or
                    current["current_image_revision"] != capture_revision or
                    current["current_image_sha256"] != result.image_sha256):
                raise Conflict("capture changed while assessment was pending")
            return self._persist_assessment_locked(current, result, actor_id,
                                                   allow_equivalent_current=True)

    def _observation_locked(self, arrival, actor_id, concern, text):
        revision = arrival["revision"] + 1
        now = self.store._now()
        self.store.connection.execute(
            "INSERT INTO volunteer_observations(observation_id,arrival_id,actor_id,concern,"
            "text,created_at,arrival_revision) VALUES (?,?,?,?,?,?,?)",
            (str(uuid4()), arrival["arrival_id"], actor_id, int(concern), text, now, revision))
        if concern:
            self.store.connection.execute(
                "INSERT INTO human_concerns(concern_id,arrival_id,actor_id,text,created_at,"
                "arrival_revision) VALUES (?,?,?,?,?,?)",
                (str(uuid4()), arrival["arrival_id"], actor_id, text, now, revision))
        self.store.connection.execute("UPDATE arrivals SET revision=? WHERE arrival_id=?",
                                      (revision, arrival["arrival_id"]))
        if concern:
            self._refer_locked(arrival["arrival_id"], revision, "Human concern: " + text,
                               new_evidence=True)
        self.store._event(arrival["session_id"], arrival["arrival_id"], actor_id,
                          "volunteer_observation", {}, {"concern": concern, "text": text},
                          "volunteer observation")
        return self.store.detail(arrival["arrival_id"])

    def record_observation(self, arrival_id, expected_revision, actor_id, concern, text=""):
        bounded_text(arrival_id, "arrival_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        if type(concern) is not bool:
            raise ValueError("concern must be a boolean")
        if concern:
            bounded_text(text, "text", 4096)
        elif text != "":
            raise ValueError("no-concern observation cannot contain concern text")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            arrival = self._arrival_locked(arrival_id, expected_revision)
            return self._observation_locked(arrival, actor_id, concern, text)

    def record_concern(self, arrival_id, expected_revision, actor_id, text):
        return self.record_observation(arrival_id, expected_revision, actor_id, True, text)

    def complete_review(self, arrival_id, expected_revision, actor_id):
        bounded_text(arrival_id, "arrival_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            arrival = self.store._arrival_row(arrival_id)
            if (arrival["state"] not in ("confirmed", "voided") or
                    not arrival["confirmed_by"] or not arrival["confirmed_at"]):
                raise Conflict("only originally confirmed arrivals can be reviewed")
            pending = self._pending(arrival_id)
            if pending is None or pending["required_revision"] != expected_revision:
                raise Conflict("review revision changed; reload current queue")
            self.store.connection.execute(
                "UPDATE reviews SET state='completed',completed_by=?,completed_at=? "
                "WHERE review_id=?", (actor_id, self.store._now(), pending["review_id"]))
            self.store.connection.execute(
                "UPDATE arrivals SET revision=revision+1 WHERE arrival_id=?", (arrival_id,))
            self.store._event(arrival["session_id"], arrival_id, actor_id, "review_completed",
                              {"required_revision": expected_revision},
                              {"completed_by": actor_id}, "human review marked complete")
            return self.store.detail(arrival_id)

    def list_reviews(self, session_id):
        self.store._session_row(session_id)
        return [self.store.detail(row["arrival_id"]) for row in self.store.connection.execute(
            "SELECT a.arrival_id FROM arrivals a JOIN reviews r USING(arrival_id) "
            "WHERE a.session_id=? AND r.state='awaiting' ORDER BY a.display_number",
            (session_id,)).fetchall()]

    def finish_intake(self, session_id, expected_revision, actor_id):
        bounded_text(session_id, "session_id")
        bounded_text(actor_id, "actor_id")
        nonnegative_int(expected_revision, "expected_revision")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            session = self.store._session_row(session_id)
            if session["revision"] != expected_revision or session["intake_state"] != "open":
                raise Conflict("intake changed; reload before finishing")
            before = self.store.summary(session_id)
            arrivals = self.store.connection.execute(
                "SELECT * FROM arrivals WHERE session_id=? AND state='confirmed' ORDER BY display_number",
                (session_id,)).fetchall()
            for arrival in arrivals:
                current = self._latest_assessment(arrival)
                observation = self.store.connection.execute(
                    "SELECT concern,arrival_revision FROM volunteer_observations "
                    "WHERE arrival_id=? ORDER BY rowid DESC LIMIT 1",
                    (arrival["arrival_id"],)).fetchone()
                decision_missing = (observation is None or
                    (arrival["current_image_revision"] is not None and
                     observation["arrival_revision"] < arrival["current_image_revision"]))
                if current is None or (current["result"] == "No" and decision_missing):
                    fallback = assess(arrival["arrival_id"], arrival["revision"],
                                      arrival["current_image_sha256"], "skipped")
                    self._persist_assessment_locked(arrival, fallback, actor_id)
            self.store.connection.execute(
                "UPDATE sessions SET intake_state='finished',finished_at=?,revision=revision+1 "
                "WHERE session_id=?", (self.store._now(), session_id))
            after = self.store.summary(session_id)
            self.store._event(session_id, None, actor_id, "intake_finished", before, after,
                              "volunteer finished intake")
            return after
