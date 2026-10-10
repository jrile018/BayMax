"""Trust-bound CPU reader for root accepted-situation publications."""
import json
import hashlib
import os
import subprocess
import sys

import pytest

from contracts.incident import EvidenceLog
from integration.incident_artifacts import SnapshotPublisher

from viewer3d.publication_reader import load_accepted_publication


T0 = "2026-10-10T09:00:00Z"


def _fixture(tmp_path):
    directory = tmp_path / "accepted"
    log = EvidenceLog("incident-test", [-121, 39, -120, 40])
    source_health = {"nws": {"status": "stale", "source_time": T0,
                             "reason": "refresh exceeded 300 seconds"}}
    publication = SnapshotPublisher(directory).publish(
        log, T0, source_health=source_health)
    pointer = json.loads((directory / "current.json").read_bytes())
    return directory, publication, pointer


def test_loads_trusted_current_publication_and_preserves_unknowns(tmp_path):
    directory, publication, pointer = _fixture(tmp_path)
    result = load_accepted_publication(
        directory, expected_publication_sha256=pointer["publication_sha256"])
    assert result.publication_sha256 == pointer["publication_sha256"]
    assert result.view_hash == publication["view_hash"]
    assert result.mission_hash == publication["mission_hash"]
    assert result.snapshot_hash == publication["snapshot"]["snapshot_hash"]
    assert result.view.branches == ()
    assert result.view.metadata["source_snapshot"] == publication["snapshot"]
    assert result.view.metadata["source_health"]["nws"]["status"] == "stale"
    assert all(value is None for key, value in
               result.view.metadata["accepted_categories"].items()
               if key != "hazard")
    assert result.view.metadata["operational_outcomes"] == "unavailable"
    assert result.view.metadata["geographic_projection"] == "none"


def test_rejects_untrusted_or_replaced_current_publication(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    with pytest.raises(ValueError, match="trusted publication"):
        load_accepted_publication(directory, expected_publication_sha256="0" * 64)
    log = EvidenceLog("incident-test", [-121, 39, -120, 40])
    SnapshotPublisher(directory).publish(log, T0, source_health={"nws": {
        "status": "failure", "source_time": T0, "reason": "later revision"}})
    with pytest.raises(ValueError, match="trusted publication"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])


def test_rejects_changed_file_bytes_and_filename_traversal(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    publication_file = directory / pointer["publication_file"]
    publication_file.write_bytes(publication_file.read_bytes() + b" ")
    with pytest.raises(ValueError, match="publication digest"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])
    pointer["publication_file"] = "../elsewhere.json"
    (directory / "current.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="publication filename"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])


def test_rejects_symlinked_pointer_publication_and_directory(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    pointer_file = directory / "current.json"
    copy = tmp_path / "pointer-copy.json"
    copy.write_bytes(pointer_file.read_bytes())
    pointer_file.unlink()
    pointer_file.symlink_to(copy)
    with pytest.raises(ValueError, match="regular file"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])
    pointer_file.unlink()
    pointer_file.write_bytes(copy.read_bytes())
    publication_file = directory / pointer["publication_file"]
    publication_copy = tmp_path / "publication-copy.json"
    publication_copy.write_bytes(publication_file.read_bytes())
    publication_file.unlink()
    publication_file.symlink_to(publication_copy)
    with pytest.raises(ValueError, match="regular file"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="directory"):
        load_accepted_publication(
            alias, expected_publication_sha256=pointer["publication_sha256"])


def test_rejects_oversized_or_malformed_pointer(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    (directory / "current.json").write_bytes(b" " * 4097)
    with pytest.raises(ValueError, match="byte limit"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])
    (directory / "current.json").write_bytes(b'{"bad":NaN}')
    with pytest.raises(ValueError, match="JSON"):
        load_accepted_publication(
            directory, expected_publication_sha256=pointer["publication_sha256"])


def _repin_publication(directory, pointer, change):
    path = directory / pointer["publication_file"]
    publication = json.loads(path.read_bytes())
    change(publication)
    data = json.dumps(publication, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode() + b"\n"
    path.write_bytes(data)
    pointer["publication_sha256"] = hashlib.sha256(data).hexdigest()
    (directory / "current.json").write_text(
        json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n")
    return pointer["publication_sha256"]


def test_rejects_self_consistent_but_wrong_mission_hash(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    trusted = _repin_publication(
        directory, pointer,
        lambda publication: publication.__setitem__("mission_hash", "a" * 64))
    with pytest.raises(ValueError, match="mission hash"):
        load_accepted_publication(
            directory, expected_publication_sha256=trusted)


def test_rejects_numeric_false_capability_even_when_rehashed(tmp_path):
    directory, _, pointer = _fixture(tmp_path)
    trusted = _repin_publication(
        directory, pointer,
        lambda publication: publication["capabilities"].__setitem__(
            "can_dispatch", 0))
    with pytest.raises(ValueError, match="capability"):
        load_accepted_publication(
            directory, expected_publication_sha256=trusted)


@pytest.mark.parametrize("target", ["pointer", "publication"])
def test_rejects_fifo_without_blocking(tmp_path, target):
    directory, _, pointer = _fixture(tmp_path)
    path = (directory / "current.json" if target == "pointer"
            else directory / pointer["publication_file"])
    path.unlink()
    os.mkfifo(path)
    code = (
        "from viewer3d.publication_reader import load_accepted_publication\n"
        "try:\n"
        " load_accepted_publication(__import__('sys').argv[1], "
        "expected_publication_sha256=__import__('sys').argv[2])\n"
        "except ValueError as exc:\n"
        " print(str(exc))\n"
        "else:\n"
        " raise AssertionError('FIFO accepted')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(directory),
         pointer["publication_sha256"]],
        capture_output=True, text=True, timeout=2)
    assert result.returncode == 0, result.stderr
    assert "regular file" in result.stdout
