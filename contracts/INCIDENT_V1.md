# Incident evidence contract v1

Module: `contracts.incident`. Version: `knight26-incident-v1`. This is an in-memory, standard-library contract for one incident. It does not fetch sources, authenticate people or networks, persist records, interpret claims, route vehicles, run a forecast, or dispatch anything.

## Trusted boundary and callables

`EvidenceLog(incident_id, bbox_lonlat, *, official_policies=())` owns an append-only history. `bbox_lonlat` is explicit WGS84 `[min_lon,min_lat,max_lon,max_lat]` and cannot wrap the antimeridian. Each point and polygon vertex must lie inside it. Null geometry remains either an area label or unknown; no geocoding or point precision is inferred.

`EvidenceLog.append(record, *, verification: VerifiedSource, review: HumanReview | None = None) -> dict` validates and stores one revision. It returns a defensive JSON copy. The caller must construct `VerifiedSource(source_id, source_url, raw_sha256, transport_verified)` only after checking the acquired bytes, URL/host, and transport. The record's URL and SHA-256 must match that context. A caller may construct `HumanReview(identity, raw_sha256, reviewer_id, reviewed_fields, reviewed_at, authenticated, record_sha256)` only after authenticating the reviewer and presenting the exact record fields. After authenticated presentation of the complete record, the trusted caller computes `record_fingerprint(record)` and passes that digest as `record_sha256`. The review binds the canonical values of every field, including payload values, category, source kind, geometry, source reference, and time. Reusing the review after any record change fails atomically. Neither a source's `acceptance` claim nor an arbitrary `reviewed` flag is allowed in `record`.

`OfficialPolicy(source_id, provider, host, allowed_api_fields, allowed_payload_fields, rule_id)` is trusted application configuration. Without a human review, only an `official_api` `hazard` record with source kind `observed` or `official_forecast` and exact allowlisted field and payload keys may enter. This policy never admits needs, closures, vehicles, stock, or facility capacity. News hazard records reviewed by a human remain separate `unconfirmed_leads`, outside accepted hazard constraints. Human-reviewed independent operational claims can populate their category. Review is an authorization and provenance check, not a guarantee that a source claim is true.

`EvidenceLog.snapshot(cutoff_utc, *, ledger_watermark=None, in_flight_commitments=None, source_health=None) -> dict` returns a deep JSON copy with `snapshot_hash`. It contains incident ID, bbox, cutoff, current category records, `revision_history` including derived `superseded_at`, source references, unconfirmed leads, ledger watermark, commitments, and separate source health. A category with no accepted current evidence is `null`, meaning unknown. Retractions hide the current item while remaining in history. Distinct sources remain distinct claims. `source_health` may mark alive, stale, or failure; stale needs last-good source time and refresh-failure reason. Health never changes source-stated `valid_from` or `valid_through`. Issuing a snapshot seals its cutoff, so later appends cannot backdate into it.

`projection_input(snapshot, *, horizon_minutes, model_version, assumptions, training_assumptions=None) -> dict` verifies the snapshot hash and pins its accepted source refs, cutoff, horizon, source health, ledger, commitments, and authored assumptions. Its `calibrated` flag is false and its label is `uncalibrated_scenario_frequencies`. V1 has no typed operational completeness or capability validator. Therefore `can_calculate_operational_outcomes` is always false: neither a present `status: unknown` record nor free-form authored training labels can authorize a calculation. `missing_operational_categories` names absent categories; `unknown_operational_categories` and `unverified_operational_categories` list all operational categories whose completeness is not validated. A later contract must define and verify typed usable records or a complete labeled training dataset before changing this gate. This wrapper performs no physical or operational calculation and makes no risk, route-safety, optimization, or outcome claim.

## Record schema

Every record has `source_id`, `item_id`, positive integer `revision`, canonical HTTPS `source_url`, lowercase `raw_sha256`, `provider`, `license`, `source_type` (`official_api`, `agency_notice`, `news`, `ocr`, `authored`), `category` (`hazard`, `needs`, `closures`, `vehicles`, `stock`, `capacity`), `source_kind` (`observed`, `reported`, `official_forecast`, `authored`), `published_at`, `observed_at`, `valid_from`, `valid_through`, `message_expires_at`, `first_seen_at`, `fetched_at`, `accepted_at`, `correction_available_at`, `superseded_at`, `supersedes`, `retracted`, `source_reference`, `geometry`, `precision`, `area_label`, `source_uncertainty`, and `payload`. Nullable times and uncertainty use JSON null; timestamps must be UTC `Z`. `observed_at` may not exceed `accepted_at`; an `observed` source kind requires a non-null observation time. When both validity endpoints are known, `valid_from` must be no later than `valid_through`. For NWS, map `onset` to `valid_from`, `ends` to `valid_through`, and alert `expires` to `message_expires_at`; alert expiration is message lifetime and may precede onset, while `ends` may remain null. An area-filtered NWS response can include neighboring states, so the adapter must retain the exact source geography and this AOI check may reject its geometry. Null NWS geometry keeps `areaDesc`, UGC, or affected-zone text as an area label rather than a point. `superseded_at` is null on input and derived for a known-at snapshot. A correction has `supersedes=[source_id,item_id,prior_revision]`, a later revision number, and `correction_available_at`; a retraction is a correction with `retracted=true`. Reusing an identity with identical content is idempotent; changing it fails atomically.

`source_reference={"api_fields":["properties.event"]}` binds official API fields. Textual sources use an exact quote and optional page. OCR additionally requires a page and normalized crop. Text and payload are data only; any display layer must escape/sanitize them. This module caps record bytes, history count, payload fields, and polygon vertices. It never follows a URL or executes source text.

## Minimal example

```python
from contracts.incident import EvidenceLog, OfficialPolicy, VerifiedSource, projection_input

sha = "a" * 64  # replace with the SHA-256 of verified raw source bytes
url = "https://api.weather.gov/alerts/example"
log = EvidenceLog("training-incident", [-121, 39, -120, 40], official_policies=[
    OfficialPolicy("nws", "NWS", "api.weather.gov",
                   ("properties.event",), ("event",), "nws-alert-v1")
])
record = {
    "source_id": "nws", "item_id": "example", "revision": 1,
    "source_url": url, "raw_sha256": sha, "provider": "NWS",
    "license": "public domain", "source_type": "official_api",
    "category": "hazard", "source_kind": "official_forecast",
    "published_at": "2026-10-10T08:00:00Z", "observed_at": None,
    "valid_from": None, "valid_through": None, "message_expires_at": None, "first_seen_at": "2026-10-10T08:30:00Z",
    "fetched_at": "2026-10-10T08:45:00Z",
    "accepted_at": "2026-10-10T09:00:00Z",
    "correction_available_at": None, "superseded_at": None,
    "supersedes": None, "retracted": False,
    "source_reference": {"api_fields": ["properties.event"]},
    "geometry": {"type": "Point", "coordinates": [-120.5, 39.5]},
    "precision": "point", "area_label": None, "source_uncertainty": None,
    "payload": {"event": "Flood Warning"},
}
log.append(record, verification=VerifiedSource("nws", url, sha, True))
snapshot = log.snapshot("2026-10-10T09:00:00Z", ledger_watermark={"seq": 7},
                        in_flight_commitments=[{"trip_id": "trip-1"}])
inputs = projection_input(snapshot, horizon_minutes=60, model_version="scenario-v1",
                          assumptions={"weather": "authored training branch"})
assert inputs["initial_snapshot_hash"] == snapshot["snapshot_hash"]
assert inputs["can_calculate_operational_outcomes"] is False
```

For a real adapter, trusted source verification, reviewer authentication, and review-record digest creation must occur outside the untrusted parser. A snapshot hash checks integrity, not authenticity; callers must obtain snapshots from a trusted `EvidenceLog` instance. Ledger and commitment metadata is copied exactly as trusted caller input, so its own temporal validation belongs to that caller. The example SHA is illustrative. Data and model versions require their own independent review before product acceptance.
