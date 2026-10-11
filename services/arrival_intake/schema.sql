CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL, run_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL, destination_node TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'exercise' CHECK (mode = 'exercise'),
    expected_count INTEGER NOT NULL CHECK (expected_count >= 0),
    original_expected_count INTEGER NOT NULL CHECK (original_expected_count >= 0),
    boarding_event_id TEXT NOT NULL, departure_event_id TEXT, arrival_event_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    intake_state TEXT NOT NULL DEFAULT 'open' CHECK (intake_state IN ('open','finished')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    next_display_number INTEGER NOT NULL DEFAULT 1 CHECK (next_display_number > 0),
    created_at TEXT NOT NULL, finished_at TEXT,
    UNIQUE (case_id, run_id, dispatch_id)
);
CREATE TABLE IF NOT EXISTS arrivals (
    arrival_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    display_number INTEGER NOT NULL CHECK (display_number > 0),
    state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','confirmed','voided')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    confirmed_by TEXT, confirmed_at TEXT,
    reported_symptoms TEXT NOT NULL DEFAULT '', observed_concern TEXT NOT NULL DEFAULT '',
    UNIQUE (session_id, display_number)
);
CREATE TABLE IF NOT EXISTS operations (
    session_id TEXT NOT NULL REFERENCES sessions(session_id), operation_key TEXT NOT NULL,
    request_hash TEXT NOT NULL, response TEXT NOT NULL CHECK (json_valid(response)),
    PRIMARY KEY (session_id, operation_key)
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    arrival_id TEXT REFERENCES arrivals(arrival_id), actor_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL, event_type TEXT NOT NULL,
    before_json TEXT NOT NULL CHECK (json_valid(before_json)),
    after_json TEXT NOT NULL CHECK (json_valid(after_json)), reason TEXT NOT NULL,
    correction_kind TEXT
);
CREATE TABLE IF NOT EXISTS images (
    image_id TEXT PRIMARY KEY, arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    image_sha256 TEXT NOT NULL, private_bytes BLOB,
    permitted_use_json TEXT NOT NULL CHECK (json_valid(permitted_use_json)),
    created_at TEXT NOT NULL, deleted_at TEXT,
    UNIQUE (arrival_id, image_sha256),
    CHECK ((deleted_at IS NULL AND private_bytes IS NOT NULL) OR (deleted_at IS NOT NULL AND private_bytes IS NULL))
);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY, arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    image_sha256 TEXT, capture_id TEXT, capture_revision INTEGER,
    arrival_revision INTEGER NOT NULL CHECK (arrival_revision >= 0),
    origin TEXT NOT NULL CHECK (origin IN ('scripted_training','evaluated_model','unavailable')),
    result TEXT NOT NULL CHECK (result IN ('Yes','No','Unsure')),
    reason TEXT NOT NULL, model_revision TEXT, created_at TEXT NOT NULL,
    FOREIGN KEY (arrival_id, image_sha256) REFERENCES images(arrival_id, image_sha256)
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY, arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    required_revision INTEGER NOT NULL CHECK (required_revision >= 0),
    state TEXT NOT NULL CHECK (state IN ('awaiting','completed')),
    reason TEXT NOT NULL, created_at TEXT NOT NULL, completed_by TEXT, completed_at TEXT,
    CHECK ((state='awaiting' AND completed_by IS NULL AND completed_at IS NULL)
        OR (state='completed' AND completed_by IS NOT NULL AND completed_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_review_per_arrival ON reviews(arrival_id) WHERE state='awaiting';
CREATE TABLE IF NOT EXISTS human_concerns (
    concern_id TEXT PRIMARY KEY, arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    actor_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
    arrival_revision INTEGER NOT NULL CHECK (arrival_revision >= 0)
);
CREATE INDEX IF NOT EXISTS human_concerns_by_arrival ON human_concerns(arrival_id);
CREATE TABLE IF NOT EXISTS volunteer_observations (
    observation_id TEXT PRIMARY KEY, arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    actor_id TEXT NOT NULL, concern INTEGER NOT NULL CHECK (concern IN (0,1)),
    text TEXT NOT NULL, created_at TEXT NOT NULL,
    arrival_revision INTEGER NOT NULL CHECK (arrival_revision >= 0)
);
CREATE INDEX IF NOT EXISTS volunteer_observations_by_arrival ON volunteer_observations(arrival_id);
CREATE INDEX IF NOT EXISTS arrivals_by_session ON arrivals(session_id);
-- A capture is a revision-specific permission record. The legacy images table
-- keeps one private byte payload per arrival/hash; this separate identity lets
-- an identical-byte retake still have a new current pointer.
CREATE TABLE IF NOT EXISTS photo_captures (
    capture_id TEXT PRIMARY KEY,
    arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    image_id TEXT NOT NULL REFERENCES images(image_id),
    arrival_revision INTEGER NOT NULL CHECK (arrival_revision >= 0),
    media_type TEXT NOT NULL CHECK (media_type IN ('image/jpeg','image/png')),
    permission_json TEXT NOT NULL CHECK (json_valid(permission_json)),
    actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (arrival_id, arrival_revision)
);
CREATE INDEX IF NOT EXISTS photo_captures_by_arrival ON photo_captures(arrival_id);
CREATE TABLE IF NOT EXISTS photo_artifacts (
    artifact_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
    absolute_path TEXT NOT NULL UNIQUE, recorded_at TEXT NOT NULL, deleted_at TEXT
);
-- Root-controlled grant state is durable and shared by every request connection.
-- Revoked IDs remain as tombstones after media cleanup and cannot be provisioned again.
CREATE TABLE IF NOT EXISTS capture_grants (
    grant_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('active','revoked')),
    version INTEGER NOT NULL CHECK (version > 0),
    facts_sha256 TEXT,
    exercise_session_id TEXT
);
CREATE TABLE IF NOT EXISTS capture_sessions (
    capture_session_id TEXT PRIMARY KEY,
    exercise_session_id TEXT NOT NULL REFERENCES sessions(session_id),
    arrival_id TEXT NOT NULL REFERENCES arrivals(arrival_id),
    actor_id TEXT NOT NULL,
    grant_id TEXT NOT NULL REFERENCES capture_grants(grant_id),
    grant_version INTEGER NOT NULL,
    arrival_revision INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active','consumed','closed')),
    last_frame_id INTEGER NOT NULL DEFAULT 0,
    preview_count INTEGER NOT NULL DEFAULT 0,
    committed_digest TEXT,
    committed_input_digest TEXT,
    receipt_json TEXT,
    CHECK ((state='consumed' AND committed_digest IS NOT NULL AND committed_input_digest IS NOT NULL
            AND receipt_json IS NOT NULL)
           OR (state!='consumed' AND committed_digest IS NULL AND committed_input_digest IS NULL
               AND receipt_json IS NULL))
);
CREATE INDEX IF NOT EXISTS capture_sessions_by_arrival ON capture_sessions(arrival_id);
