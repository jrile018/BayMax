"""Bounded RFC 8785 codec. No model, permission or execution claim is made."""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from hashlib import sha256
import json
import math

SAFE_INTEGER = 2**53 - 1
MAX_JSON_BYTES = 1024 * 1024


class InvalidEvidence(ValueError):
    """Malformed, altered or inconsistent evidence."""


def _string(value):
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise InvalidEvidence("lone Unicode surrogate")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number(value):
    if type(value) is int:
        if abs(value) > SAFE_INTEGER:
            raise InvalidEvidence("integer outside Faces safe range")
        return str(value)
    if not math.isfinite(value):
        raise InvalidEvidence("nonfinite number")
    if value == 0:
        return "0"
    # Search shortest round-tripping decimal; choose closest, then even.
    # This avoids Python repr's different tie selection and exponent spelling.
    negative = value < 0
    magnitude = abs(value)
    with localcontext() as ctx:
        ctx.prec = 1100
        exact = Decimal.from_float(magnitude)
        for precision in range(1, 18):
            unit = Decimal(1).scaleb(exact.adjusted() - precision + 1)
            nearest = exact.quantize(unit, rounding=ROUND_HALF_EVEN)
            candidates = [nearest - unit, nearest, nearest + unit]
            candidates = [d for d in candidates if d > 0 and float(d) == magnitude]
            if candidates:
                shortest = min(candidates, key=lambda d: (
                    abs(d - exact), int(d / unit) % 2))
                break
        else:
            raise InvalidEvidence("number has no binary64 serialization")
        digits = format(shortest, "f").rstrip("0") if shortest < 1 else format(shortest, "f")
        if "." in digits:
            digits = digits.rstrip("0").rstrip(".")
        exponent = shortest.adjusted()
        if -6 <= exponent < 21:
            result = digits
        else:
            coefficient = shortest.scaleb(-exponent)
            result = format(coefficient, "f").rstrip("0").rstrip(".")
            result += "e" + ("+" if exponent >= 0 else "-") + str(abs(exponent))
    return ("-" if negative else "") + result


def canonical_bytes(value):
    """Serialize bounded JSON content; keys sort by UTF-16, without NFC."""
    nodes = 0

    def encode(item, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 48 or nodes > 25000:
            raise InvalidEvidence("JSON complexity budget exceeded")
        if item is None:
            return "null"
        if type(item) is bool:
            return "true" if item else "false"
        if type(item) in (int, float):
            return _number(item)
        if type(item) is str:
            return _string(item)
        if isinstance(item, Mapping):
            if any(type(k) is not str for k in item):
                raise InvalidEvidence("JSON keys must be strings")
            for key in item:
                _string(key)
            keys = sorted(item, key=lambda k: k.encode("utf-16-be"))
            return "{" + ",".join(_string(k) + ":" + encode(item[k], depth + 1) for k in keys) + "}"
        if type(item) in (list, tuple):
            return "[" + ",".join(encode(v, depth + 1) for v in item) + "]"
        raise InvalidEvidence("unsupported JSON value")

    data = encode(value).encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise InvalidEvidence("JSON byte budget exceeded")
    return data


def parse_json(data):
    if type(data) not in (bytes, str):
        raise InvalidEvidence("JSON bytes or text required")
    try:
        raw = data.decode("utf-8") if type(data) is bytes else data
        if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
            raise InvalidEvidence("JSON byte budget exceeded")

        def pairs(entries):
            result = {}
            for key, value in entries:
                if key in result:
                    raise InvalidEvidence("duplicate JSON key")
                result[key] = value
            return result

        def bad_constant(_):
            raise InvalidEvidence("nonfinite JSON number")

        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
        canonical_bytes(result)
        return result
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        if isinstance(exc, InvalidEvidence):
            raise
        raise InvalidEvidence("invalid JSON") from exc


def content_fingerprint(value):
    return sha256(canonical_bytes(value)).hexdigest()
