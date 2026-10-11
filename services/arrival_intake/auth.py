"""Opaque bearer-token authentication for the controlled intake demo."""

import hashlib
import hmac
import re

from .contracts import Principal


class Unauthorized(PermissionError):
    """No valid demo role credential was supplied."""


_BEARER = re.compile(r"Bearer ([A-Za-z0-9_~+./=-]{32,128})\Z")


def authenticate(authorization_header, token_registry):
    """Resolve a bearer token through a root-provided SHA-256 digest registry.

    The registry contains digest -> Principal or digest -> principal field mapping.
    Raw tokens are never accepted as registry keys or placed in exceptions.
    """
    if not isinstance(authorization_header, str):
        raise Unauthorized("authentication required")
    match = _BEARER.fullmatch(authorization_header)
    if match is None:
        raise Unauthorized("authentication required")
    digest = hashlib.sha256(match.group(1).encode("ascii")).hexdigest()
    matched = None
    for registered_digest, entry in token_registry.items():
        if (isinstance(registered_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", registered_digest)
                and hmac.compare_digest(digest, registered_digest)):
            matched = entry
    if matched is None:
        raise Unauthorized("authentication required")
    try:
        if isinstance(matched, Principal):
            return matched
        return Principal(matched["actor_id"], matched["role"],
                         frozenset(matched["session_ids"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise Unauthorized("authentication required") from exc
