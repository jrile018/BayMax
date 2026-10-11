"""Controlled, simulator-backed bus intake exercise and private CLI.

The illustration is generated in memory. Its exact digest is granted by the
trusted server process; a client-supplied source reference cannot grant access.
No face matching or real bruise analysis is configured.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import stat
from uuid import uuid4

from PIL import Image, ImageDraw

from services.planner.ledger import Destination, Ledger, Request, Vehicle
from services.routing import Edge, Graph, SafetySnapshot, candidate_routes
from services.routing.trip import TripExecutor

from .photos import PhotoStore
from .server import make_server
from .store import IntakeStore
from .trip_adapter import session_seed
from .workflow import ExerciseAssessor, Workflow


SOURCE_REFERENCE = "task7-operator-illustration-v1"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def illustration_bytes():
    """Return reproducible, non-person exercise art as a PNG byte sequence."""
    image = Image.new("RGB", (320, 180), (246, 247, 241))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 303, 163), outline=(28, 76, 94), width=4)
    draw.rectangle((35, 49, 285, 130), fill=(223, 233, 228))
    draw.ellipse((93, 59, 156, 122), fill=(177, 86, 95), outline=(95, 43, 62), width=3)
    draw.line((179, 71, 256, 111), fill=(42, 89, 105), width=8)
    draw.text((34, 25), "EXERCISE ILLUSTRATION", fill=(28, 76, 94))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def build_demo_seed(case_id="arrival-demo"):
    """Advance a real fictional TripExecutor and adapt its ledger event evidence."""
    graph = Graph({"A": (0, 0), "B": (100, 0), "C": (100, 100), "D": (200, 0)}, [
        Edge("ab", "A", "B", 100, 10), Edge("bd", "B", "D", 100, 10),
        Edge("ac", "A", "C", 141.421356, 15),
        Edge("bc", "B", "C", 100, 10), Edge("cd", "C", "D", 141.421356, 15),
    ], version="tiny-v1")
    safety = SafetySnapshot("k0", 0, 0, 1000, provenance="fictional exercise",
                            safe_nodes=frozenset(graph.nodes))
    passengers = tuple(f"exercise-person-{number:02d}" for number in range(1, 31))
    ledger = Ledger([Vehicle("bus1", "bus", "A", len(passengers), 0)],
                    [Request("evac1", "evacuation", "A", "D", passengers)],
                    [Destination("shelter1", "D", "shelter", len(passengers))], {})
    executor = TripExecutor(graph, ledger)
    route = candidate_routes(graph, "A", "D", "bus", 0, safety).routes[0]
    executor.dispatch("dispatch1", "bus1", "evac1", route, safety,
                      loading_s=0, service_s=0)
    executor.advance(25, safety)
    snapshot = executor.snapshot()
    if len(snapshot["trips"]) != 1 or snapshot["trips"][0]["phase"] != "completed":
        raise RuntimeError("fictional trip did not complete before intake")
    seed = session_seed(case_id, snapshot, "dispatch1")
    if seed.expected_count != len(passengers):
        raise RuntimeError("adapted boarding differs from simulator passengers")
    return seed


def _private_path(value, *, must_exist):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("private paths must be absolute")
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("private path must not cross a symlink")
    path = path.resolve()
    if path == _PROJECT_ROOT or path.is_relative_to(_PROJECT_ROOT):
        raise ValueError("database, credentials and receipts must stay outside the tracked checkout")
    if not path.parent.is_dir():
        raise ValueError("private parent directory must already exist")
    if must_exist and not path.is_file():
        raise ValueError("private file does not exist")
    if not must_exist and path.exists():
        raise FileExistsError("private file already exists; refusing overwrite")
    return path


def _exclusive_json(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _check_owner_only(path):
    info = path.stat()
    if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise PermissionError("private credentials must be owned by this user with mode 0600")


def prepare_demo(database, credentials, case_id="arrival-demo"):
    """Create a fresh private database and separate owner-only role credentials."""
    database = _private_path(database, must_exist=False)
    credentials = _private_path(credentials, must_exist=False)
    if database == credentials:
        raise ValueError("database and credentials must be distinct paths")
    image_digest = sha256(illustration_bytes()).hexdigest()
    # These labels live in trusted server configuration, never in a client body.
    labels = {str(number): "No" for number in range(1, 31)}
    labels["1"], labels["2"] = "Yes", "Unsure"
    seed = build_demo_seed(case_id)
    previous_umask = os.umask(0o077)
    try:
        with IntakeStore(database) as store:
            session = store.create_session(seed)
        sid = session["session_id"]
        raw_tokens = {role: secrets.token_hex(32) for role in
                      ("volunteer", "care_reviewer", "coordinator")}
        registry = {sha256(token.encode("ascii")).hexdigest(): {
            "actor_id": f"demo-{role}", "role": role, "session_ids": [sid],
        } for role, token in raw_tokens.items()}
        config = {
            "format": "arrival-intake-private-v1", "database": str(database),
            "session_id": sid, "case_id": seed.case_id,
            "source_reference": SOURCE_REFERENCE,
            "illustration_sha256": image_digest, "scripted_labels": labels,
            "tokens": raw_tokens, "token_registry": registry,
        }
        _exclusive_json(credentials, config)
        _check_owner_only(credentials)
    finally:
        os.umask(previous_umask)
    return {"session_id": sid, "case_id": seed.case_id,
            "expected_count": seed.expected_count, "source_sha256": seed.source_sha256,
            "source_reference": SOURCE_REFERENCE, "illustration_sha256": image_digest,
            "database": str(database), "credentials": str(credentials)}


def _load_config(database, credentials):
    database = _private_path(database, must_exist=True)
    credentials = _private_path(credentials, must_exist=True)
    _check_owner_only(credentials)
    with credentials.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if config.get("format") != "arrival-intake-private-v1" or config.get("database") != str(database):
        raise ValueError("credentials do not belong to this demonstration database")
    if (config.get("source_reference") != SOURCE_REFERENCE or
            config.get("illustration_sha256") != sha256(illustration_bytes()).hexdigest()):
        raise ValueError("trusted illustration grant differs from this source")
    return database, config


def serve_demo(database, credentials, port):
    """Serve only on loopback, at a caller-selected free allocated port."""
    if type(port) is not int or not 1 <= port <= 65535 or port in range(8765, 8769):
        raise ValueError("choose an unused allocated port outside shared services 8765-8768")
    database, config = _load_config(database, credentials)
    labels = {int(key): value for key, value in config["scripted_labels"].items()}
    web_root = _PROJECT_ROOT / "web" / "intake"
    with IntakeStore(database) as store:
        if (store.summary(config["session_id"])["case_id"] !=
                config.get("case_id", "arrival-demo")):
            raise ValueError("private config session is not the prepared demo")
        photos = PhotoStore(store, {SOURCE_REFERENCE: {
            "source_kind": "operator_created_illustration",
            "image_sha256s": frozenset({config["illustration_sha256"]}),
            "capture_allowed": True, "display_allowed": True,
            "processing_allowed": True,
        }})
        workflow = Workflow(store, photos, ExerciseAssessor(labels))
        server = make_server(store, workflow, photos, config["token_registry"], web_root,
                             host="127.0.0.1", port=port)
        try:
            server.serve_forever()
        finally:
            server.server_close()


def cleanup_demo(database, session_id=None, actor_id="demo-coordinator"):
    """Remove private media after service shutdown and write a non-image receipt."""
    database = _private_path(database, must_exist=True)
    with IntakeStore(database) as store:
        if session_id is None:
            sessions = [row[0] for row in store.connection.execute(
                "SELECT session_id FROM sessions WHERE mode='exercise'")]
            if len(sessions) != 1:
                raise ValueError("cleanup needs exactly one exercise session")
            session_id = sessions[0]
        summary = store.summary(session_id)
        if summary["mode"] != "exercise":
            raise ValueError("cleanup requires an exercise session")
        result = PhotoStore(store).cleanup(session_id, actor_id)
        retained = store.summary(session_id)
        remaining = store.connection.execute(
            "SELECT count(*) FROM images i JOIN arrivals a USING(arrival_id) WHERE a.session_id=?",
            (session_id,)).fetchone()[0]
        captures = store.connection.execute(
            "SELECT count(*) FROM photo_captures c JOIN arrivals a USING(arrival_id) WHERE a.session_id=?",
            (session_id,)).fetchone()[0]
        if remaining or captures:
            raise RuntimeError("image cleanup verification failed")
    receipt = {
        "kind": "arrival-intake-media-cleanup", "session_id": session_id,
        "case_id": retained["case_id"], "actor_id": actor_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "removed_images": result["removed_images"],
        "remaining_images": remaining, "remaining_captures": captures,
        "expected_count": retained["expected_count"],
        "confirmed_count": retained["confirmed_count"],
        "difference": retained["difference"],
        "awaiting_reviews": retained["awaiting_reviews"],
        "completed_reviews": retained["completed_reviews"],
    }
    receipt_path = database.parent / f"arrival-intake-cleanup-{uuid4().hex}.json"
    _exclusive_json(receipt_path, receipt)
    return dict(receipt, receipt_path=str(receipt_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--database", required=True)
    prepare.add_argument("--credentials", required=True)
    cleanup = actions.add_parser("cleanup")
    cleanup.add_argument("--database", required=True)
    serve = actions.add_parser("serve")
    serve.add_argument("--database", required=True)
    serve.add_argument("--credentials", required=True)
    serve.add_argument("--port", required=True, type=int)
    arguments = parser.parse_args(argv)
    if arguments.action == "prepare":
        print(json.dumps(prepare_demo(arguments.database, arguments.credentials), sort_keys=True))
    elif arguments.action == "cleanup":
        print(json.dumps(cleanup_demo(arguments.database), sort_keys=True))
    else:
        serve_demo(arguments.database, arguments.credentials, arguments.port)


if __name__ == "__main__":
    main()
