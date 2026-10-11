"""Correction paths preserve durable confirmation evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from services.arrival_intake.contracts import Conflict, SessionSeed
from services.arrival_intake.store import IntakeStore


class StoreInvariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = IntakeStore(Path(self.temp.name) / 'intake.sqlite')
        self.addCleanup(self.store.close)
        self.sid = self.store.create_session(SessionSeed(
            'case', 'run', 'trip', 'bus', 'destination', 2,
            'boarded', 'arrived', 'a' * 64, 'departed'))['session_id']

    def test_draft_cannot_be_counted_by_correction(self):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO arrivals(arrival_id,session_id,display_number,state) VALUES ('draft',?,1,'draft')",
                (self.sid,))
        with self.assertRaises(Conflict):
            self.store.correct(self.sid, 0, 'coordinator', 'attempt to count a draft',
                               {'arrival_id': 'draft', 'counted': True})
        self.assertEqual(self.store.summary(self.sid)['confirmed_count'], 0)
        self.assertEqual(self.store.summary(self.sid)['revision'], 0)
        self.assertEqual(self.store.detail('draft')['state'], 'draft')
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_restore_keeps_original_confirmation(self):
        first = self.store.confirm_arrival(self.sid, 'operation', 'volunteer')
        original = self.store.detail(first['arrival_id'])
        self.store.correct(self.sid, 1, 'coordinator', 'duplicate',
                           {'arrival_id': first['arrival_id'], 'counted': False})
        self.store.correct(self.sid, 2, 'coordinator', 'restore verified presence',
                           {'arrival_id': first['arrival_id'], 'counted': True})
        restored = self.store.detail(first['arrival_id'])
        self.assertEqual(restored['confirmed_by'], original['confirmed_by'])
        self.assertEqual(restored['confirmed_at'], original['confirmed_at'])
        self.assertEqual(self.store.summary(self.sid)['confirmed_count'], 1)

    def test_list_arrivals_returns_dictionary(self):
        first = self.store.confirm_arrival(self.sid, 'operation', 'volunteer')
        self.assertEqual(self.store.list_arrivals(self.sid),
                         {'arrivals': [self.store.detail(first['arrival_id'])]})
