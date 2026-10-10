"""Exploratory positive control for one pinned synthetic 4-by-2 montage.

This is a cell-coverage check, not a real-photo accuracy or casualty-case eval.
"""
from __future__ import annotations

from services.casualty.contracts import FaceBox

IMAGE_SHA256 = "971bb6b36e1f03329fdc684fafff23309217294b656b09af1b4cc532282da3ef"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
SOURCE_URL = "https://commons.wikimedia.org/wiki/File:Artbreeder_example_portraits.jpg"
SCORE_THRESHOLD = 0.9
NMS_THRESHOLD = 0.3
TOP_K = 50


def validate_montage_boxes(boxes: tuple[FaceBox, ...]) -> tuple[int, ...]:
    """Require eight high-score boxes wholly within eight distinct fixed cells."""
    if not isinstance(boxes, tuple) or len(boxes) != 8 or not all(isinstance(b, FaceBox) for b in boxes):
        raise ValueError("exactly eight typed boxes required")
    seen: set[int] = set()
    for box in boxes:
        if box.score < SCORE_THRESHOLD:
            raise ValueError("box score below fixed threshold")
        col = min(3, int(((box.x1 + box.x2) / 2) * 4))
        row = min(1, int(((box.y1 + box.y2) / 2) * 2))
        if not (col / 4 <= box.x1 < box.x2 <= (col + 1) / 4 and
                row / 2 <= box.y1 < box.y2 <= (row + 1) / 2):
            raise ValueError("box spills beyond portrait cell")
        cell = row * 4 + col
        if cell in seen:
            raise ValueError("expected one per cell")
        seen.add(cell)
    if seen != set(range(8)):
        raise ValueError("expected one per cell")
    return tuple(sorted(seen))
