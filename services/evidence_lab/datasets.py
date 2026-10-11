"""Offline synthetic selection preparation; no HumSet loader or acquisition.

Only author-created fictional inputs are authorized for the prepared controls.
Real source/rights/loader adoption remains a separate root decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import sys
import unicodedata

SECTORS = ("Agriculture", "Cross", "Education", "Food Security", "Health",
           "Livelihoods", "Logistics", "Nutrition", "Protection", "Shelter", "WASH")
SEED = 20261010
DATA_LABEL = "synthetic_exercise"


def canonical_bytes(value):
    """Dataset diagnostic JSON, NOT a Faces RFC8785 codec."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class Bounds:
    max_scan_per_split: int = 5000
    max_candidate_bytes: int = 16_777_216
    max_excerpt_utf8_bytes: int = 8192
    max_private_selected_text_bytes: int = 655360
    max_transport_bytes: int = 33_554_432

    def validate(self):
        if type(self.max_candidate_bytes) is not int or self.max_candidate_bytes < 4096:
            raise SelectionError("candidate budget below fixed accounting overhead")
        ceilings = (5000, 16_777_216, 8192, 655360, 33_554_432)
        for value, ceiling in zip(self.__dict__.values(), ceilings):
            if type(value) is not int or not 0 < value <= ceiling:
                raise SelectionError("bounds may only tighten frozen limits")


@dataclass(frozen=True)
class Candidate:
    split: str
    entry_id: str | int
    entry_key: str
    document_key: str
    lead_key: str
    project_key: str
    language: str
    sectors: tuple[str, ...]
    excerpt_sha256: str
    normalized_text_sha256: str
    priority: str

    def metadata(self):
        return {"split": self.split, "entry_id": self.entry_id,
                "language": self.language, "sectors": list(self.sectors),
                "excerpt_sha256": self.excerpt_sha256}


@dataclass(frozen=True)
class SelectionManifest:
    metadata: dict
    private_excerpts: tuple[dict, ...]

    def to_dict(self):
        # No excerpt text enters the manifest.
        return json.loads(canonical_bytes(self.metadata))


def identity(value):
    if type(value) is int and abs(value) <= 2**53 - 1:
        return canonical_bytes(["integer", value]).decode("utf-8")
    if type(value) is str and value and len(value.encode("utf-8")) <= 512:
        return canonical_bytes(["string", value]).decode("utf-8")
    raise SelectionError("missing or invalid group/entry identity")


def _candidate(row, split, seed, bounds):
    if type(row) is not dict:
        raise SelectionError("row must be a builtin dictionary")
    keys = ("entry_id", "document", "lead_id", "project_id", "lang", "sectors", "excerpt")
    if any(key not in row for key in keys):
        raise SelectionError("required source fields missing")
    entry = identity(row["entry_id"])
    document, lead, project = (identity(row[key]) for key in ("document", "lead_id", "project_id"))
    language = row["lang"]
    sectors = row["sectors"]
    text = row["excerpt"]
    if type(language) is not str or language not in {"en", "es", "fr"}:
        raise SelectionError("unsupported language")
    if (type(sectors) is not list or not sectors or len(sectors) > len(SECTORS)
            or any(type(item) is not str or item not in SECTORS for item in sectors)
            or len(set(sectors)) != len(sectors)):
        raise SelectionError("invalid frozen taxonomy")
    if type(text) is not str or not text or len(text) > bounds.max_excerpt_utf8_bytes:
        raise SelectionError("excerpt size/type")
    encoded = text.encode("utf-8")
    if len(encoded) > bounds.max_excerpt_utf8_bytes:
        raise SelectionError("excerpt UTF8 byte limit")
    normalized = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))
    # Exact seed|split|entry_id algorithm, using an unambiguous typed ID encoding.
    priority = sha256(f"{seed}|{split}|{entry}".encode("utf-8")).hexdigest()
    candidate = Candidate(split, row["entry_id"], entry, document, lead, project,
                          language, tuple(sectors), sha256(encoded).hexdigest(),
                          sha256(normalized.encode("utf-8")).hexdigest(), priority)
    wire = {key: row[key] for key in keys}
    return candidate, text, len(canonical_bytes(wire))


def _cost(candidate):
    # Conservative owned-candidate accounting includes instance/dict/field
    # objects plus 512 bytes for list/set/receipt/audit indexes per candidate.
    # This is not a measurement of total-process RSS; root also bounds process memory.
    values = vars(candidate).values()
    return (sys.getsizeof(candidate) + sys.getsizeof(vars(candidate)) + 512
            + sum(sys.getsizeof(value) for value in values)
            + sum(sys.getsizeof(label) for label in candidate.sectors))


def _kept_cost(kept):
    return sum(sys.getsizeof(item) + sys.getsizeof(text)
               for item, text in kept)


def select_humset(rows_by_split, *, seed=SEED, dev_count=16, test_count=64,
                  target_languages=None, max_scan_per_split=5000,
                  max_candidate_bytes=16_777_216, bounds=None):
    """Pure preparation interface; results ALWAYS retain synthetic provenance.

    Iterator EOF is an endpoint of these supplied fixtures, not evidence of a
    verified upstream file. Interrupted prefix diagnostics never permit scoring.
    """
    bounds = bounds or Bounds(max_scan_per_split=max_scan_per_split,
                              max_candidate_bytes=max_candidate_bytes)
    bounds.validate()
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise SelectionError("invalid seed")
    if type(dev_count) is not int or not 0 <= dev_count <= 16:
        raise SelectionError("development count outside frozen bounds")
    if type(test_count) is not int or not 0 <= test_count <= 64:
        raise SelectionError("test count outside frozen bounds")
    targets = dict(target_languages if target_languages is not None
                   else {"en": 32, "es": 16, "fr": 16})
    if (not targets or any(key not in {"en", "es", "fr"} for key in targets)
            or any(type(value) is not int or value < 0 for value in targets.values())
            or sum(targets.values()) != test_count):
        raise SelectionError("language quotas must sum to test count")
    if type(rows_by_split) is not dict or set(rows_by_split) != {"validation", "test"}:
        raise SelectionError("exact validation/test split inputs required")

    scanned = {"validation": 0, "test": 0}
    ordered = {"validation": [], "test": []}
    endpoints = {"validation": "not_started", "test": "not_started"}
    candidates = {"validation": [], "test": []}
    kept = {"validation": [], "test": []}
    identities = {"validation": set(), "test": set()}
    exclusions = {"development_group_overlap": 0, "language_quota_zero": 0}
    memory = 4096
    transport = 0
    error_stage = None
    frozen = (set(), set(), set())
    for split in ("validation", "test"):
        try:
            stream = iter(rows_by_split[split])
            for _ in range(bounds.max_scan_per_split):
                try:
                    row = next(stream)
                except StopIteration:
                    endpoints[split] = "natural_fixture_eof"
                    break
                scanned[split] += 1
                error_stage = "row_validation"
                item, text, row_bytes = _candidate(row, split, seed, bounds)
                if item.entry_key in identities[split]:
                    raise SelectionError("duplicate ID in split")
                ordered[split].append(item.entry_id)
                transport += row_bytes
                error_stage = "transport_budget"
                if transport > bounds.max_transport_bytes:
                    raise SelectionError("transport budget exceeded")
                prospective = list(kept[split])
                overlaps = split == "test" and any(key in group for key, group in zip(
                    (item.entry_key, item.document_key, item.lead_key), frozen))
                if overlaps:
                    exclusions["development_group_overlap"] += 1
                elif split == "validation":
                    prospective = sorted(prospective + [(item, text)],
                                         key=lambda pair: pair[0].priority)[:dev_count]
                else:
                    capacity = targets.get(item.language, 0)
                    if capacity == 0:
                        exclusions["language_quota_zero"] += 1
                    other = [pair for pair in prospective if pair[0].language != item.language]
                    same = sorted([pair for pair in prospective if pair[0].language == item.language]
                                  + [(item, text)], key=lambda pair: pair[0].priority)[:capacity]
                    prospective = other + same
                proposed_text = prospective + kept["test" if split == "validation" else "validation"]
                error_stage = "private_text_budget"
                if sum(len(value.encode("utf-8")) for _, value in proposed_text) > bounds.max_private_selected_text_bytes:
                    raise SelectionError("private selected-text budget exceeded")
                error_stage = "candidate_memory_budget"
                if memory + _cost(item) + _kept_cost(proposed_text) > bounds.max_candidate_bytes:
                    raise SelectionError("candidate memory budget exceeded")
                memory += _cost(item)
                candidates[split].append(item)
                identities[split].add(item.entry_key)
                kept[split] = prospective
                error_stage = None
            else:
                endpoints[split] = "fixed_prefix"
            if split == "validation":
                dev = [pair[0] for pair in kept[split]]
                frozen = ({item.entry_key for item in dev},
                          {item.document_key for item in dev}, {item.lead_key for item in dev})
        except Exception as error:
            # No raw exception text or excerpts enter diagnostic manifests.
            endpoints[split] = "interrupted"
            error_stage = error_stage or "source_stream"
            break

    dev = sorted(kept["validation"], key=lambda pair: pair[0].priority)
    test = sorted(kept["test"], key=lambda pair: pair[0].priority)
    prefix_complete = all(value in {"natural_fixture_eof", "fixed_prefix"} for value in endpoints.values())
    language_counts = {key: sum(item.language == key for item, _ in test) for key in targets}
    coverage = {label: sum(label in item.sectors for item, _ in dev + test) for label in SECTORS}
    dev_projects = {item.project_key for item, _ in dev}
    test_projects = {item.project_key for item, _ in test}
    dev_texts = {item.normalized_text_sha256 for item in candidates["validation"]}
    duplicate_test_ids = [item.entry_id for item in candidates["test"]
                          if item.normalized_text_sha256 in dev_texts]
    metadata = {
        "schema": "hf.synthetic-selection.v1", "data_label": DATA_LABEL,
        "source_status": "author_created_fictional_controls",
        "seed": seed, "status": "complete" if prefix_complete else "incomplete",
        "scoring_allowed": False, "benchmark_result": "UNRUN",
        "operational_field_gold": "not_annotated", "manifest_contains_excerpt_text": False,
        "actual_scanned_count": scanned, "ordered_candidate_ids": ordered,
        "canonical_split_id_prefix_sha256": sha256(canonical_bytes(ordered)).hexdigest(),
        "prefix_hash_is_upstream_full_file_verification": False,
        "prefix_endpoints": endpoints, "error_stage": error_stage,
        "candidate_bounds": vars(bounds).copy(), "candidate_memory_accounted_bytes": memory + _kept_cost(dev + test),
        "candidate_memory_kind": "conservative object/index accounting, not total process RSS",
        "transport_accounted_bytes": transport,
        "requested_dev": dev_count, "requested_test": test_count,
        "actual_dev": len(dev), "actual_test": len(test),
        "target_test_languages": targets, "actual_test_languages": language_counts,
        "language_shortfall": {key: targets[key] - language_counts[key] for key in targets},
        "selection_complete": prefix_complete and len(dev) == dev_count and len(test) == test_count,
        "dev": [item.metadata() for item, _ in dev], "test": [item.metadata() for item, _ in test],
        "sector_coverage": coverage, "exclusions": exclusions,
        "selected_project_overlap_count": len(dev_projects & test_projects),
        "bounded_near_duplicate_audit": {
            "method": "NFKC/casefold/word-token-sequence equality across collected prefix metadata",
            "limitation": "no semantic/fuzzy or whole-upstream duplicate proof",
            "candidate_envelope_complete": prefix_complete,
            "test_ids_matching_validation_normalized_text": duplicate_test_ids},
    }
    excerpts = tuple({"split": item.split, "entry_id": item.entry_id,
                      "language": item.language, "excerpt": text,
                      "data_label": DATA_LABEL} for item, text in dev + test)
    return SelectionManifest(metadata, excerpts)


def fictional_rows():
    """Visibly fictional authored rows; no external source or participant data."""
    rows = {"validation": [], "test": []}
    for split in rows:
        for language in ("en", "es", "fr"):
            for index in range(40):
                ident = f"fictional-{split}-{language}-{index}"
                rows[split].append({"entry_id": ident, "document": ident + "-document",
                                    "lead_id": ident + "-lead", "project_id": "fictional-shared-project",
                                    "lang": language, "sectors": [SECTORS[index % len(SECTORS)]],
                                    "excerpt": f"FICTIONAL EXERCISE ONLY: {split} {language} item {index}."})
    return rows
