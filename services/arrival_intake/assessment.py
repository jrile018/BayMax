"""Pure, labeled assessment of one exact arrival revision and image digest.

The caller supplies a runner and its verified evaluation receipt from trusted
service configuration. Neither value is accepted from an HTTP request.
"""

from .contracts import Assessment, bounded_text, nonnegative_int, sha256_text


_REAL_TASK = "visible_marks"
_RECEIPT_KEYS = frozenset({"task", "model_revision", "evaluation_artifact_sha256", "verified"})
_RUNNER_KEYS = frozenset({"result", "model_revision", "arrival_revision", "image_sha256"})


def _unavailable(arrival_id, revision, image_sha256, reason):
    return Assessment(arrival_id, image_sha256, revision, "Unsure", "unavailable", reason, None)


def _verified_receipt(receipt):
    if type(receipt) is not dict or set(receipt) != _RECEIPT_KEYS:
        return False
    if receipt["task"] != _REAL_TASK or receipt["verified"] is not True:
        return False
    try:
        bounded_text(receipt["model_revision"], "model_revision")
        sha256_text(receipt["evaluation_artifact_sha256"], "evaluation_artifact_sha256")
    except ValueError:
        return False
    return True


def assess(arrival_id, arrival_revision, image_sha256, mode, scripted_result=None,
           evaluated_runner=None, evaluation_receipt=None):
    """Return a result whose origin states how it was obtained.

    A real runner must return a mapping bound to this exact image and revision.
    A stale or malformed result is unavailable, so it cannot become a current
    negative suggestion. Persistence must recheck these same inputs under the
    intake writer transaction before writing the result.
    """
    bounded_text(arrival_id, "arrival_id")
    nonnegative_int(arrival_revision, "arrival_revision")
    if image_sha256 is not None:
        sha256_text(image_sha256, "image_sha256")
    if mode not in ("scripted", "real", "skipped"):
        raise ValueError("unknown assessment mode")
    if image_sha256 is None:
        return _unavailable(arrival_id, arrival_revision, None,
                            "No permitted photo available; get checked")
    if mode == "skipped":
        return _unavailable(arrival_id, arrival_revision, image_sha256,
                            "Image analysis skipped; get checked")
    if mode == "scripted":
        if type(scripted_result) is not str or scripted_result not in ("Yes", "No", "Unsure"):
            raise ValueError("scripted result must be a configured exercise label")
        return Assessment(arrival_id, image_sha256, arrival_revision, scripted_result,
                          "scripted_training", "Scripted exercise input", None)
    if evaluated_runner is None or not _verified_receipt(evaluation_receipt):
        return _unavailable(arrival_id, arrival_revision, image_sha256,
                            "Visible-mark analysis unavailable; get checked")
    try:
        result = evaluated_runner(arrival_id, arrival_revision, image_sha256)
    except Exception:
        return _unavailable(arrival_id, arrival_revision, image_sha256,
                            "Visible-mark analysis failed; get checked")
    if (type(result) is not dict or set(result) != _RUNNER_KEYS or
            type(result["result"]) is not str or result["result"] not in ("Yes", "No", "Unsure") or
            result["model_revision"] != evaluation_receipt["model_revision"] or
            type(result["arrival_revision"]) is not int or
            result["arrival_revision"] != arrival_revision or
            result["image_sha256"] != image_sha256):
        return _unavailable(arrival_id, arrival_revision, image_sha256,
                            "Visible-mark analysis result unavailable; get checked")
    return Assessment(arrival_id, image_sha256, arrival_revision, result["result"],
                      "evaluated_model", "Evaluated visible-mark model suggestion", 
                      evaluation_receipt["model_revision"])
