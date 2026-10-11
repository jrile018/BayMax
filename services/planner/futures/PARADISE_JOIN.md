# Paradise exercise join

join_current_paradise joins one independently pinned accepted situation
publication to the versioned Paradise geography fixture. The caller supplies
the accepted artifact SHA-256 from a trusted coordinator handoff, a UTC
instant, a bounded horizon, and explicit authored weather/fuel/ignition text.
The publication pointer alone is not a trust root. A caller must review and
pin the artifact digest separately before invoking the join.

The join validates canonical publication bytes, the pointer's artifact hash,
publication mission/view hashes, exact false capability booleans, the
Paradise fixture bytes, and that the exercise bbox lies within the broad
source bbox. It preserves the accepted statewide snapshot, source refs,
geometry, cutoff, source health as of cutoff, null operational categories,
and null ledger/commitments. The Paradise fixture has unavailable terrain,
fuels, and current-fire layers. No accepted statewide alert is promoted into
a Paradise-local hazard by the bbox check.

The pinned projection is a schema-valid, hash-pinned exercise input.
Scenario branches are empty until separately authored branches are supplied.
The join runs no physical model, OCR, weather model, map matching, routing,
or resource calculation. Its forecast, operational outcome, calibration and
dispatch flags remain false. The caller's as-of instant marks whether the
cutoff-based horizon has expired. Source health is never rebased to it.

On 2026-10-10 the trusted live source pin was
e11aaee47fe9d5b55bca9796cf79b06d588b88c83c6c8025afd3ae37d0824821
and the source cutoff was 2026-10-10T18:07:40.592920Z.
A 60-minute exercise horizon from that cutoff ended at
2026-10-10T19:07:40.592920Z. The immutable, dated join artifact is
paradise-join-f54a60cf5f5a.json (historical artifact; not included in this repository)
(SHA-256 a381eab8fa797e5a71e5e2af744a2f37e6bdc7147e1dadf8aaec38be21ae3826).
That specific artifact is expired as of its caller time and has zero scenario
branches. It is a provenance handoff, not a current local risk prediction.

Callers should supply expected_publication_sha256 (trusted digest),
caller_as_of_utc (UTC Z), horizon_minutes (1..1440), and authored_assumptions
with weather, fuel, and ignition keys. Obtain a fresh accepted publication
and new trusted digest when the source changes. Independently verify any
Paradise hazard location, current weather/fuels/ignition, physical spread,
calibration, graph binding, or operational outcome before exposing it as such.
