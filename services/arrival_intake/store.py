"""Durable source-linked sessions. Workflow mutations are added separately."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json
from threading import RLock
from uuid import uuid4

from .contracts import (Conflict, Missing, SessionSeed, bounded_text,
                        canonical_hash, canonical_json, nonnegative_int)


class IntakeStore:
    _registry_lock = RLock()
    _open_stores = {}

    def __init__(self, database_path):
        self.database_path = Path(database_path).resolve()
        self._closed = False
        with self._registry_lock:
            self.connection = sqlite3.connect(database_path, timeout=5)
            try:
                self.connection.row_factory = sqlite3.Row
                self.connection.execute("PRAGMA foreign_keys=ON")
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA busy_timeout=5000")
                self.connection.execute("PRAGMA secure_delete=ON")
                self.connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
                self._migrate_photo_columns()
                self._migrate_workflow_columns()
                self._migrate_correction_columns()
            except BaseException:
                self.connection.close()
                raise
            self._open_stores.setdefault(self.database_path, set()).add(self)

    def _migrate_photo_columns(self):
        # ALTER is additive for a Task 1/2/3 database. Never replace the
        # legacy images table or its assessment foreign key.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(arrivals)")}
        for name, kind in (("current_image_id", "TEXT"),
                           ("current_image_sha256", "TEXT"),
                           ("current_image_revision", "INTEGER")):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE arrivals ADD COLUMN {name} {kind}")
        self.connection.commit()

    def _migrate_workflow_columns(self):
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(assessments)")}
        for name, kind in (("capture_id", "TEXT"), ("capture_revision", "INTEGER")):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE assessments ADD COLUMN {name} {kind}")
        self.connection.commit()

    def _migrate_correction_columns(self):
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
        if "correction_kind" not in columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN correction_kind TEXT")
        self.connection.commit()

    @classmethod
    def _sole_owned_connection(cls, store):
        with cls._registry_lock:
            peers = cls._open_stores.get(store.database_path, set())
            return not store._closed and peers == {store}

    def close(self):
        with self._registry_lock:
            if not self._closed:
                self.connection.close()
                self._closed = True
                peers = self._open_stores.get(self.database_path)
                if peers is not None:
                    peers.discard(self)
                    if not peers:
                        del self._open_stores[self.database_path]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def create_session(self, seed):
        if not isinstance(seed, SessionSeed): raise ValueError("seed must be a SessionSeed")
        # Revalidate at the persistence boundary; no caller can bypass frozen validation.
        seed = SessionSeed(**asdict(seed))
        values = asdict(seed)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT * FROM sessions WHERE case_id=? AND run_id=? AND dispatch_id=?",
                (seed.case_id, seed.run_id, seed.dispatch_id)).fetchone()
            if existing is not None:
                if any(existing["original_expected_count" if key == "expected_count" else key] != value
                       for key, value in values.items()):
                    raise Conflict("this trip already has a different intake source")
                session_id = existing["session_id"]
            else:
                session_id = str(uuid4())
                self.connection.execute(
                    "INSERT INTO sessions(session_id,case_id,run_id,dispatch_id,vehicle_id,destination_node,"
                    "expected_count,original_expected_count,boarding_event_id,departure_event_id,arrival_event_id,"
                    "source_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (session_id, seed.case_id, seed.run_id, seed.dispatch_id, seed.vehicle_id,
                     seed.destination_node, seed.expected_count, seed.expected_count,
                     seed.boarding_event_id, seed.departure_event_id, seed.arrival_event_id,
                     seed.source_sha256, datetime.now(timezone.utc).isoformat()))
            return self.summary(session_id)

    def summary(self, session_id):
        bounded_text(session_id, "session_id")
        # One SELECT provides a coherent view even while another intake connection writes.
        row = self.connection.execute(
            "SELECT s.*, (SELECT count(*) FROM arrivals a WHERE a.session_id=s.session_id AND a.state='confirmed') "
            "AS confirmed_count, (SELECT count(*) FROM arrivals a WHERE a.session_id=s.session_id "
            "AND EXISTS (SELECT 1 FROM reviews r WHERE r.arrival_id=a.arrival_id "
            "AND r.state='awaiting')) AS awaiting_reviews, "
            "(SELECT count(*) FROM arrivals a WHERE a.session_id=s.session_id AND NOT EXISTS "
            "(SELECT 1 FROM reviews p WHERE p.arrival_id=a.arrival_id AND p.state='awaiting') "
            "AND EXISTS (SELECT 1 FROM reviews c WHERE c.arrival_id=a.arrival_id "
            "AND c.state='completed')) AS completed_reviews "
            "FROM sessions s WHERE s.session_id=?", (session_id,)).fetchone()
        if row is None: raise Missing(session_id)
        keys = ("session_id", "case_id", "run_id", "dispatch_id", "vehicle_id", "destination_node",
                "mode", "expected_count", "original_expected_count", "confirmed_count", "intake_state",
                "awaiting_reviews", "completed_reviews", "revision")
        result = {key: row[key] for key in keys}
        result["difference"] = row["expected_count"] - row["confirmed_count"]
        return result

    def _session_row(self, session_id):
        bounded_text(session_id, "session_id")
        row = self.connection.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise Missing(session_id)
        return row

    def _arrival_row(self, arrival_id):
        bounded_text(arrival_id, "arrival_id")
        row = self.connection.execute("SELECT * FROM arrivals WHERE arrival_id=?", (arrival_id,)).fetchone()
        if row is None:
            raise Missing(arrival_id)
        return row

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _event(self, session_id, arrival_id, actor_id, kind, before, after, reason,
               correction_kind=None):
        self.connection.execute(
            "INSERT INTO events(event_id,session_id,arrival_id,actor_id,occurred_at,event_type,"
            "before_json,after_json,reason,correction_kind) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), session_id, arrival_id, actor_id, self._now(), kind,
             canonical_json(before), canonical_json(after), reason, correction_kind))

    def confirm_arrival(self, session_id, operation_key, actor_id):
        bounded_text(session_id, "session_id")
        bounded_text(operation_key, "operation_key")
        bounded_text(actor_id, "actor_id")
        request_hash = canonical_hash({"action": "confirm_arrival", "session_id": session_id,
                                       "actor_id": actor_id})
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            session = self._session_row(session_id)
            saved = self.connection.execute(
                "SELECT * FROM operations WHERE session_id=? AND operation_key=?",
                (session_id, operation_key)).fetchone()
            if saved is not None:
                if saved["request_hash"] != request_hash:
                    raise Conflict("operation key already belongs to another request")
                return json.loads(saved["response"])
            if session["intake_state"] != "open":
                raise Conflict("intake is finished; coordinator must reopen it")
            arrival_id, number = str(uuid4()), session["next_display_number"]
            self.connection.execute(
                "INSERT INTO arrivals(arrival_id,session_id,display_number,state,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,'confirmed',?,?)", (arrival_id, session_id, number, actor_id, self._now()))
            self.connection.execute(
                "UPDATE sessions SET next_display_number=next_display_number+1,revision=revision+1 WHERE session_id=?",
                (session_id,))
            self._event(session_id, arrival_id, actor_id, "arrival_confirmed", {},
                        {"arrival_id": arrival_id, "arrival_number": number, "state": "confirmed"},
                        "volunteer confirmed presence")
            result = {"arrival_id": arrival_id, "arrival_number": number, "state": "confirmed", "revision": 0,
                      "session_summary": self.summary(session_id)}
            self.connection.execute(
                "INSERT INTO operations(session_id,operation_key,request_hash,response) VALUES (?,?,?,?)",
                (session_id, operation_key, request_hash, canonical_json(result)))
            return result

    def finish_intake(self, session_id, expected_revision, actor_id):
        nonnegative_int(expected_revision, "expected_revision")
        bounded_text(actor_id, "actor_id")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            session = self._session_row(session_id)
            if session["revision"] != expected_revision or session["intake_state"] != "open":
                raise Conflict("intake changed; reload before finishing")
            before = self.summary(session_id)
            self.connection.execute(
                "UPDATE sessions SET intake_state='finished',finished_at=?,revision=revision+1 WHERE session_id=?",
                (self._now(), session_id))
            after = self.summary(session_id)
            self._event(session_id, None, actor_id, "intake_finished", before, after, "volunteer finished intake")
            return after

    def correct(self, session_id, expected_revision, actor_id, reason, change):
        nonnegative_int(expected_revision, "expected_revision")
        bounded_text(actor_id, "actor_id")
        bounded_text(reason, "reason", 4096)
        if type(change) is not dict:
            raise ValueError("change must be an object")
        keys = set(change)
        if keys == {"expected_count"}:
            nonnegative_int(change["expected_count"], "expected_count")
        elif keys == {"arrival_id", "counted"}:
            bounded_text(change["arrival_id"], "arrival_id")
            if type(change["counted"]) is not bool:
                raise ValueError("counted must be a boolean")
        elif keys == {"intake_state"} and change["intake_state"] == "open":
            pass
        else:
            raise ValueError("unsupported correction")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            session = self._session_row(session_id)
            if session["revision"] != expected_revision:
                raise Conflict("intake changed; reload before correcting")
            arrival_id = change.get("arrival_id")
            before = self.summary(session_id)
            if keys == {"expected_count"}:
                correction_kind = "expected_count"
                self.connection.execute("UPDATE sessions SET expected_count=? WHERE session_id=?",
                                        (change["expected_count"], session_id))
            elif arrival_id is not None:
                correction_kind = "attendance"
                arrival = self._arrival_row(arrival_id)
                if arrival["session_id"] != session_id:
                    raise Missing(arrival_id)
                if change["counted"] and (arrival["state"] == "draft" or
                                          not arrival["confirmed_by"] or not arrival["confirmed_at"]):
                    raise Conflict("only an originally confirmed arrival can be restored")
                before = dict(arrival)
                state = "confirmed" if change["counted"] else "voided"
                self.connection.execute("UPDATE arrivals SET state=?,revision=revision+1 WHERE arrival_id=?",
                                        (state, arrival_id))
            else:
                correction_kind = "reopen"
                self.connection.execute("UPDATE sessions SET intake_state='open',finished_at=NULL WHERE session_id=?",
                                        (session_id,))
            self.connection.execute("UPDATE sessions SET revision=revision+1 WHERE session_id=?", (session_id,))
            after = dict(self._arrival_row(arrival_id)) if arrival_id else self.summary(session_id)
            self._event(session_id, arrival_id, actor_id, "attendance_correction", before, after,
                        reason, correction_kind=correction_kind)
            return self.summary(session_id)

    def detail(self, arrival_id):
        row = dict(self._arrival_row(arrival_id))
        row["arrival_number"] = row.pop("display_number")
        capture = self.connection.execute(
            "SELECT capture_id,arrival_revision,media_type FROM photo_captures "
            "WHERE capture_id=? AND arrival_id=?", (row["current_image_id"], arrival_id)).fetchone()
        row["current_photo"] = (None if capture is None else {
            "image_id": capture["capture_id"], "image_sha256": row["current_image_sha256"],
            "arrival_revision": capture["arrival_revision"], "media_type": capture["media_type"],
        })
        assessment = self.connection.execute(
            "SELECT assessment_id,image_sha256,capture_id,capture_revision,arrival_revision,"
            "origin,result,reason,model_revision,created_at FROM assessments WHERE arrival_id=? "
            "AND ((capture_id=? AND ? IS NOT NULL) OR (capture_id IS NULL AND ? IS NULL)) "
            "ORDER BY rowid DESC LIMIT 1",
            (arrival_id, row["current_image_id"], row["current_image_id"],
             row["current_image_id"])).fetchone()
        row["assessment"] = None if assessment is None else dict(assessment)
        row["human_concerns"] = [dict(concern) for concern in self.connection.execute(
            "SELECT concern_id,actor_id,text,created_at,arrival_revision FROM human_concerns "
            "WHERE arrival_id=? ORDER BY rowid", (arrival_id,)).fetchall()]
        observation = self.connection.execute(
            "SELECT observation_id,actor_id,concern,text,created_at,arrival_revision "
            "FROM volunteer_observations WHERE arrival_id=? ORDER BY rowid DESC LIMIT 1",
            (arrival_id,)).fetchone()
        row["latest_volunteer_observation"] = (None if observation is None else {
            **dict(observation), "concern": bool(observation["concern"]),
        })
        review = self.connection.execute(
            "SELECT required_revision,state FROM reviews WHERE arrival_id=? "
            "ORDER BY rowid DESC LIMIT 1", (arrival_id,)).fetchone()
        row["care_state"] = ("not_referred" if review is None else
                             "awaiting_review" if review["state"] == "awaiting" else "review_complete")
        row["review_revision"] = None if review is None else review["required_revision"]
        return row

    def list_arrivals(self, session_id):
        self._session_row(session_id)
        return {"arrivals": [self.detail(row["arrival_id"]) for row in self.connection.execute(
            "SELECT arrival_id FROM arrivals WHERE session_id=? ORDER BY display_number", (session_id,)).fetchall()]}
