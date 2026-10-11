# Bus arrival intake exercise

This service records anonymous arrivals for one simulated bus. Its expected count comes from a completed fictional `TripExecutor` trip and the ledger's `dispatch_committed`, `departure`, and `arrival` events. The adapter stores the source hash and event references with the session. It does not create a named passenger manifest or match faces. A confirmed arrival is counted once; retries with the same operation key return the same receipt.

## Private setup and loopback service

Run this from the cloud checkout after choosing **new**, owner-controlled paths outside the Git checkout and static web directory. The parent directories must exist. Do not reuse an existing database or credential file. `prepare` creates one exercise session, an illustration hash grant, fixed scripted exercise labels, and fresh role tokens in a mode `0600` JSON credential file. It prints only non-secret session/source metadata. The credential file contains bearer tokens and must never be copied to web assets, a receipt, a commit, or a browser screenshot.

```sh
/opt/venv/bin/python -m services.arrival_intake.demo prepare \
  --database /private/owned/arrival-demo.sqlite \
  --credentials /private/owned/arrival-demo-credentials.json
```

The generated `SOURCE_REFERENCE` is `task7-operator-illustration-v1`. The `illustration_sha256` in the private config is computed from `illustration_bytes()` at preparation time. A server grant accepts only those exact operator-created illustration bytes and the source reference. Photo requests must include the authenticated volunteer's matching permission metadata, including `verified_at` with a timezone. Client metadata alone cannot grant capture, display, or processing. The same in-memory image can be reproduced by calling `illustration_bytes()` in this source on the cloud runtime; this exercise includes no real-person image.

Before serving, the operator checks active ports and selects an unused allocated port outside shared services `8765`–`8768`. The CLI binds the existing `make_server` constructor to `127.0.0.1` only; it does not start a public route or authenticated reverse proxy. Stop it before cleanup.

```sh
/opt/venv/bin/python -m services.arrival_intake.demo serve \
  --database /private/owned/arrival-demo.sqlite \
  --credentials /private/owned/arrival-demo-credentials.json \
  --port PORT
```

The standalone page is served at `/` or `/index.html` on that loopback service, with `/app.js` and `/style.css`. Its browser route is usable only through a separately verified, authenticated gateway to this loopback service. The currently tested private HTTPS proxy path returns Jupyter `404`; signed-in phone and dashboard acceptance remains blocked until an owner-supported route is verified. The separate legacy dashboard can import `web/arrival-summary.js` only when configured with a same-origin intake aggregate URL and entry URL. Static files carry no credentials.

## HTTP contract

All `/api/*` requests require `Authorization: Bearer <token>`. The token registry stores SHA-256 digests and maps each principal to an actor ID, role, and assigned session IDs. Missing authentication yields `401`; session-scoped unassigned or disallowed actions yield `403`; arrival-scoped foreign and unknown IDs both yield `404`; stale revisions yield `409`. The private photo endpoint returns raw PNG/JPEG bytes when permitted, or `404` when unavailable or cleaned. Request handlers use fresh database connections. No endpoint accepts a model result from the client.

| Route | Role | Request or response |
| --- | --- | --- |
| `GET /api/me` | authenticated | Actor, role, assigned session IDs. |
| `GET /api/intakes` | assigned | Assigned intake summaries. |
| `GET /api/intakes/{sid}` | volunteer, coordinator, care reviewer | Session summary and anonymous arrival details. |
| `GET /api/intakes/{sid}/aggregate` | coordinator | Bus-level `session_id`, `case_id`, `vehicle_id`, `destination_node`, `mode`, `expected_count`, `confirmed_count`, `difference`, `intake_state`, `awaiting_reviews`, `completed_reviews`. It excludes arrival IDs. |
| `POST /api/intakes/{sid}/arrivals` | volunteer | `{operation_key}`; stable receipt with `arrival_id`, display number and summary. Reuse the key after a lost response; a new key confirms another anonymous arrival. |
| `POST /api/arrivals/{aid}/photo` | volunteer | `{expected_revision,image_base64,media_type,permission}`; permission includes `source_kind`, `source_reference`, exact true capture/display/processing flags, `verified_by`, and timezone-aware `verified_at`. Only root-granted illustration digest is accepted. |
| `GET /api/arrivals/{aid}/photo` | assigned volunteer, coordinator, care reviewer | Private bytes for the current capture. |
| `POST /api/arrivals/{aid}/assessment` | volunteer | `{expected_revision,mode}` where mode is `scripted`, `real`, or `skipped`. The response includes the arrival's persisted suggestion and origin. |
| `POST /api/arrivals/{aid}/observation` | volunteer | `{expected_revision,concern,text}`. A true concern requires text; a false concern requires empty text. Human concern stays pending even if a later suggestion is `No`. |
| `POST /api/intakes/{sid}/finish` | volunteer | `{expected_revision}` closes attendance independently of care review. Missing/undecided assessments receive `Unsure/unavailable`. |
| `GET /api/intakes/{sid}/reviews` | care reviewer | Assigned pending anonymous reviews with their `review_revision`. |
| `POST /api/arrivals/{aid}/review-complete` | care reviewer | `{expected_revision}` must equal the current `review_revision`; completion records actor/time and cannot imply medical clearance. |
| `POST /api/intakes/{sid}/corrections` | coordinator | `{expected_revision,reason,change}` where change is `{expected_count: N}`, `{arrival_id, counted: bool}`, or `{intake_state: "open"}`. A correction is attributed and revision checked. |
| `GET /api/intakes/{sid}/history` | coordinator | Narrow correction history with actor, time, reason, before and after values. |

Suggestions are about a visible mark in a training exercise. `scripted` uses root-configured labels (`Yes`, `No`, `Unsure`) and origin `scripted_training`; it is not model inference. A requested `real` analysis has no configured runner in this demonstration and records `Unsure` with origin `unavailable`. `No` is never medical clearance. A referral records a handoff request; the review completion field records a human workflow step, not proof that care was delivered. Attendance counts and care counts remain separate.

Anonymous operation-key deduplication prevents repeat submissions with the same key, including reload or response loss. It cannot establish that two different operation keys refer to the same person. A coordinator can correct an over-count with a reason while the original simulator-backed expected count remains recorded as `original_expected_count` and the source event references stay intact.

## Cleanup and evidence

After stopping the server and closing all other connections to this owned database, run:

```sh
/opt/venv/bin/python -m services.arrival_intake.demo cleanup \
  --database /private/owned/arrival-demo.sqlite
```

Cleanup clears image bytes and capture associations, checkpoints/truncates the WAL, compacts SQLite, removes registered private image artifacts, and writes a new owner-only non-image receipt beside the database. It retains anonymous attendance totals, assessment origin/result labels, review history, correction history, and simulator source references. The receipt contains counts and no token, person ID, image digest, or image bytes. Reopen the store/service and verify every captured photo route returns `404`, image/capture rows are zero, and no nonempty image journal remains. The service must be quiescent during cleanup.

The controlled end-to-end unittest uses temporary tokens, a temporary database, actual HTTP requests, and the simulator trip. It checks 30 expected, 29 confirmed, two pending reviews at finish, zero pending and two completed after human review, the unchanged one-person attendance discrepancy, role denial, retry, an over-count correction, and photo deletion after reopen. An optional controller receipt runner may serialize its `acceptance_trace` only after all assertions pass. That trace is not browser acceptance or model validation. Actual cloud command, HEAD, exit code, test totals, and blocked browser steps belong in `artifacts/arrival_intake/acceptance.json` on the canonical cloud checkout.

## Reviewed webcam source and remaining integration

The standalone volunteer view now includes explicit Start camera, Capture and assess, Retake, and Stop camera controls, alongside the separate file fallback. Attendance is confirmed independently; capture, assessment, retries, and retakes never add another passenger. A human concern remains actionable after a negative suggestion, and care completion remains separate from attendance closure.

The root-configured capture authority is absent by default. The illustrated `demo prepare` setup above does not grant live webcam use. An operator must independently obtain participant/image-use permission and configure exact arrival/actor/purpose authority before the live path can succeed. Browser camera permission alone is not image-use consent. Capture handles are bound to the assigned arrival and expire; client requests cannot create grants.

| Capture route | Request or behavior |
| --- | --- |
| `POST /api/arrivals/{aid}/capture-session` | Creates a root-authorized acquisition session before browser device permission. |
| `POST /api/capture-sessions/{cid}/preview` | Exact frame ID, encoded image and media type; framing is unavailable while no reviewed adapter is configured. |
| `POST /api/capture-sessions/{cid}/capture` | Exact expected revision, selected encoded image and media type; returns the saved photo/current arrival and explicit currentness. |
| `GET /api/capture-sessions/{cid}` | Recovers the original possibly committed handle; retired media is not adopted as current. |
| `POST /api/capture-sessions/{cid}/close` | Stops acquisition without changing attendance or independently permitted saved-photo display. |

Camera lifecycle guards stop late tracks after Stop/Dispose, end acquisition on terminal authorization/currentness failures, and enforce expiry while permission or playback is pending. Preview requests are at most one per second, with one active request, a 1280-pixel long-edge bound and a two-second sampled-preview lifetime. Boxes belong only to their matching sampled raster and never authorize selected-image injury evidence. Selected saves use the existing exact assessment body `{expected_revision, mode: 'real'}` after a current receipt.

Saved live photos use separate server-issued display leases of at most five seconds, measured from monotonic request start. Expiry, denied renewal and late responses clear visible images and object URLs. This bounds display revocation; it cannot retract external copies. Static illustration display remains a separate no-live-lease path.

Reviewed source milestones are the anonymous attendance/care foundation, capture authorization backend, and camera lifecycle/UI. Actual controlled tests passed: 124 intake Python tests at the capture-backend source milestone; then 29 camera/app Node tests and 26 affected Python HTTP/static/config/capture checks at the webcam source milestone. Test-first failures were reproduced and five independent camera review findings were repaired and accepted. Public publication removes internal receipt metadata and adds this documentation; it does not add a performed browser or model result.

Remaining work is the reviewed face-localization bridge, separately evaluated selected-photo concern runner, image-bound regions/reasons and human-review authority, linked-derived retention/cleanup, and the actual laptop demonstration. Exact external schemas/codecs, trusted rights/time/issuer/evaluation bridges and resource/cancellation admission remain prerequisites. A supported authenticated secure application route, actual consenting adult and evaluated vision runtime are still missing. Narrow and desktop layout rules exist in source; actual viewport and webcam acceptance remain unperformed. No bruise classifier, clinical clearance, face identity matching or operational deployment is claimed.
