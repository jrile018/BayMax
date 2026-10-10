# Optional completed-run artifact archive (schema v2)

This package builds a local, checksummed pack of explicitly selected, typed structured replay/evaluation files. The local finalized run remains authoritative. Upload is an optional call by a separate artifact client process after completion; no simulator state, model work, or replay compute moves to the Bucket.

## Accepted data contract

The caller must review the completed run and attest that selected data is sanitized. This adapter enforces a narrow shape and rejects freeform text. Numeric aggregates, repository labels, and opaque hexadecimal IDs are not proof of de-identification; the privacy claim remains a caller attestation. Review upstream source handling before any remote upload.

The required config.json has exactly schema=knight26.config.v1, integer seed, and a nonempty parameters map. Parameter keys are limited to time_horizon_s, vehicle_count, max_routes, risk_weight, and distance_weight; values are finite numbers. The required snapshots.jsonl has one or more rows with exactly tick, kind=snapshot, entity_id (16–64 lowercase hex characters), and a nonempty numeric values map. Optional replay.jsonl and events.jsonl use the same row shape; kind is one of route, closure, allocation, observation, progress, eta, snapshot. Values keys are limited to progress, eta_seconds, distance_km, risk_score, allocation_count. Optional metrics.json and evaluation.json have exactly schema=knight26.aggregate.v1 and a nonempty metrics map. Metric keys are limited to score, route_count, total_distance_km, mean_eta_minutes, completed_count, failed_count, mean_latency_ms; values are finite numbers. Text notes, reports, media, coordinates, arbitrary fields, top-level arrays/scalars, and nonopaque entity IDs are rejected.

Each file must be UTF-8 JSON/JSONL, no larger than 10 MB, and a regular nonsymlink file. A pack must include config.json and snapshots.jsonl; no folder upload or arbitrary paths are supported.

Completed-run metadata contains exactly run_id, run_nonce, status=completed, completed_at (UTC ISO 8601), privacy={sanitized:true,contains_personal_data:false}, and provenance. Provenance has source, solver, and policy as full lowercase 40-hex revisions; model and datasets as bounded lists of repo_id plus full lowercase 40-hex revision (model may be an explicit empty list for offline runs); config and snapshot as lowercase SHA-256 values of the included files; seed as an exact nonnegative integer matching config.json. The caller supplies a random 16-hex run_nonce. Use make_run_id(completed_at, provenance, run_nonce) to derive a run ID bound to timestamp, seed, all provenance, and nonce. The local pack includes lengths and SHA-256 for every selected file. The revision fields are caller-supplied full-hash references: this adapter validates their syntax but does not verify that source, solver, policy, model, or dataset revisions exist or resolve to the intended upstream content. It does verify that the config and snapshot hashes match the bytes included in this pack.

## Offline CLI

    PYTHONDONTWRITEBYTECODE=1 python3 -m services.artifact_store pack --source /path/to/finalized-run --output /path/to/pack --metadata /path/to/metadata.json --file config.json --file snapshots.jsonl --file metrics.json
    PYTHONDONTWRITEBYTECODE=1 python3 -m services.artifact_store verify --pack /path/to/pack
    PYTHONDONTWRITEBYTECODE=1 python3 -m services.artifact_store plan --pack /path/to/pack

The plan command is offline and makes no remote calls. verify_pack validates the schema, exact file set, hashes, and config seed for verified retrieval and later input-adapter review. The narrow v2 snapshot/event rows do not establish full simulator replay or state restoration; the root simulator's full snapshot adapter is a separate integration gate.

## Optional transfer API

upload_pack(pack_dir, backend, dry_run=False) uses an injected backend with list_files(prefix), upload_files([(local_path, remote_path), ...]), and download_files([(remote_path, local_path), ...]). For a partial prefix with no manifest, it downloads and checks every existing object against the local manifest, uploads only missing objects, and publishes manifest.json last. Mismatched bytes, foreign objects, or a published manifest with missing objects are rejected without deletion or overwrite. An identical completed pack is downloaded and verified before returning already_verified. A fresh or resumed upload is downloaded and verified before returning verified. Bucket batches are nontransactional; a failure may leave partial remote files. The local finalized run remains untouched.

fetch_pack(backend, run_id, destination) downloads the manifest into a temporary directory, rejects manifests over 64 KiB or more than six file entries, validates every path/schema/length/hash, and publishes the destination only after success.

hf_backend.HfBucketBackend is lazy and requires a separately provisioned huggingface_hub>=1.5 artifact environment, existing Hub authentication, an existing PRIVATE Bucket, and caller-confirmed remaining FREE private quota in bytes. Its preflight atomically reserves missing upload bytes against a conservative budget held within this process; direct upload calls require an unused reservation. Each reservation reduces the local remaining amount, including after an ambiguous partial failure, and no automatic refund occurs. This does not verify the account's actual quota or coordinate other processes/external writers; obtain fresh actual remaining-free-quota evidence before creating a new backend after failure. It never creates a Bucket, changes visibility, manages credentials, deletes files, or upgrades the model environment. The model-serving wheelhouse has Hub 0.36.2 and lacks Bucket APIs. A separate artifact-only client target is under validation; no compatible live client or successful Bucket transfer is claimed yet. There is no CLI live-upload command. If capability, auth, or quota proof is unavailable, report SetupNeeded and keep the completed local run.

The transport methods map to the official Bucket Python guide at https://huggingface.co/docs/huggingface_hub/guides/buckets: bucket_info, list_bucket_tree(prefix=..., recursive=True), batch_bucket_files(add=...), and download_bucket_files(files=...). Buckets are mutable and have no storage-level version guarantee. Matching checks and unique run IDs protect ordinary retries but cannot make concurrent writers or external Bucket mutation atomic. Coordinate writers to one prefix; remote verification is point-in-time.

## Tests

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest evals.artifact_store.test_store evals.artifact_store.test_review evals.artifact_store.test_backend -v

The transfer backend in tests is an in-memory mock. Its evidence does NOT demonstrate a real Hugging Face Bucket operation.
