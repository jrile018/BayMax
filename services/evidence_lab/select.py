"""Synthetic-only offline selector CLI; source preparation, not a run grant."""
from __future__ import annotations
import argparse
from hashlib import sha256
import os
from pathlib import Path
from services.evidence_lab.datasets import canonical_bytes, fictional_rows, select_humset

PRIVATE_PARENT = Path("/workspace/knight26/artifacts/hf")
MAX_OUTPUT_BYTES = 16_777_216


def pack_bytes(selection):
    excerpts = b"".join(canonical_bytes(row) + b"\n" for row in selection.private_excerpts)
    selected = canonical_bytes(selection.to_dict()) + b"\n"
    files = {"selection.json": selected, "private_excerpts.jsonl": excerpts}
    manifest = {"schema": "hf.synthetic-selection-pack.v1", "data_label": "synthetic_exercise",
                "benchmark_result": "UNRUN", "scoring_allowed": False,
                "files": {name: {"bytes": len(data), "sha256": sha256(data).hexdigest()}
                          for name, data in files.items()}}
    files["manifest.json"] = canonical_bytes(manifest) + b"\n"
    if sum(map(len, files.values())) > MAX_OUTPUT_BYTES:
        raise ValueError("private output byte cap")
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.private_root.resolve(strict=True)
    root.relative_to(PRIVATE_PARENT.resolve(strict=True))
    if root.stat().st_mode & 0o077:
        raise ValueError("assigned private root must have owner-only access")
    output = args.output
    parent = output.parent.resolve(strict=True)
    parent.relative_to(root)
    if output.name in {"", ".", ".."} or output.exists() or output.is_symlink():
        raise ValueError("unique new private output directory required")
    selection = select_humset(fictional_rows())
    files = pack_bytes(selection)
    # New directory and exclusive files only; preserve partial output on failure.
    output = parent / output.name
    output.mkdir(mode=0o700)
    for name, data in files.items():
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    # manifest.json was written last; no transport/publication/model operation.
    return 0 if selection.metadata["selection_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
