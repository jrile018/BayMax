# CPU adapter independent review

Source-only review by the independent casualty reviewer. No reviewer SSH execution or actual model run. Initial diff SHA256 `5bde587b4edf09df9b168cb3900574474f0e8bae125cd1884b537d06348dabef`; fixed diff SHA256 `54407e73c6f82e79e6ffbe51a4f5407b96aa9849ab2cca5f6aa0bbe2f2dabd07` independently matched.

Two Important findings were reproduced and fixed:

1. A valid float32 score at the configured threshold was rejected against the Python float boundary. The effective C++ float32 score/NMS thresholds are retained; score validation uses the effective boundary. Regression covers valid boundary and immediately lower invalid score.
2. Malformed empty array shapes were accepted as no-face; the detect return was ignored. Empty arrays must have N x 15 shape, and successful output requires nonboolean integral return 1. Current official OpenCV4.x source returns1 after inference even for zero rows, and0 for empty input.

One Minor finding was reproduced and fixed: runtime directory creation could leak an untyped storage error. It now uses the model-call failure wrapper; injected PermissionError is covered.

Review reproductions:8 failed,1 passed before fixes. After fixes:98 cloud tests pass. Reviewer confirmed all findings fixed, with no new actionable source findings. The first adapter red log records42 failing controls before the module existed; the89-test intermediate green result preceded reviewer regressions.

Permissions/image gates, model byte binding via private read-only temporary copy, orientation/dimensions, explicit CPU backend/target/thread cap, immutable run metadata and cleanup were reviewed. Tests use fabricated policy records, generated rasters, mock model bytes and a fake OpenCV API. Neither the review nor these tests establishes actual photo permission, detector execution, compatibility, latency, accuracy or clinical performance. No findings were deferred.
