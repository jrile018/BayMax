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
    after_json TEXT NOT NULL CHECK (json_valid(after_json)), reason TEXT NOT NULL
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
    image_sha256 TEXT, arrival_revision INTEGER NOT NULL CHECK (arrival_revision >= 0),
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
CREATE INDEX IF NOT EXISTS arrivals_by_session ON arrivals(session_id);
