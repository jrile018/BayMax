"""Private service configuration cannot turn the database into a public asset."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from services.arrival_intake.server import make_server
from services.arrival_intake.store import IntakeStore


class ServerConfigurationTests(unittest.TestCase):
    def test_database_inside_static_root_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with IntakeStore(root / 'index.html') as store:
                with self.assertRaises(ValueError):
                    server = make_server(store, None, None, {}, root)
                    self.addCleanup(server.server_close)

    def test_undeclared_workflow_is_rejected_during_setup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / 'web'
            web.mkdir()
            with IntakeStore(root / 'intake.sqlite') as store:
                with self.assertRaises(ValueError):
                    server = make_server(store, object(), None, {}, web)
                    self.addCleanup(server.server_close)
