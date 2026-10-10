"""Standard score-ordered one-to-one box matching; caller labels real vs control data."""
from dataclasses import dataclass
from services.casualty.contracts import FaceBox, number


def iou(a: FaceBox, b: FaceBox) -> float:
    if not isinstance(a, FaceBox) or not isinstance(b, FaceBox):
        raise ValueError("typed FaceBox inputs required")
    intersection = max(0, min(a.x2,b.x2)-max(a.x1,b.x1)) * max(0,min(a.y2,b.y2)-max(a.y1,b.y1))
    union = (a.x2-a.x1)*(a.y2-a.y1) + (b.x2-b.x1)*(b.y2-b.y1) - intersection
    return intersection / union


@dataclass(frozen=True)
class LocalizationCounts:
    true_positive: int
    false_positive: int
    false_negative: int
    matched_iou_sum: float

    def __post_init__(self) -> None:
        for name in ("true_positive", "false_positive", "false_negative"):
            value=getattr(self,name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        number(self.matched_iou_sum,"matched_iou_sum",0,self.true_positive)

    @property
    def precision(self) -> float | None:
        n=self.true_positive+self.false_positive
        return self.true_positive/n if n else None

    @property
    def recall(self) -> float | None:
        n=self.true_positive+self.false_negative
        return self.true_positive/n if n else None

    @property
    def mean_matched_iou(self) -> float | None:
        return self.matched_iou_sum/self.true_positive if self.true_positive else None


def localization_counts(predictions: tuple[FaceBox,...], truth: tuple[FaceBox,...], *, iou_threshold: float=.5) -> LocalizationCounts:
    number(iou_threshold,"iou_threshold",0,1)
    if iou_threshold == 0:
        raise ValueError("iou_threshold must be positive")
    for boxes in (predictions,truth):
        if not isinstance(boxes,tuple) or len(boxes)>100 or not all(isinstance(b,FaceBox) for b in boxes):
            raise ValueError("bounded immutable FaceBox tuples required")
    unmatched = set(range(len(truth)))
    matches=[]
    for p in sorted(predictions,key=lambda b:-b.score):
        if not unmatched:
            break
        index=max(sorted(unmatched),key=lambda i:iou(p,truth[i]))
        overlap=iou(p,truth[index])
        if overlap >= iou_threshold:
            matches.append(overlap)
            unmatched.remove(index)
    return LocalizationCounts(len(matches),len(predictions)-len(matches),len(unmatched),sum(matches))


def aggregate(counts: tuple[LocalizationCounts,...]) -> LocalizationCounts:
    if not isinstance(counts,tuple) or not all(isinstance(c,LocalizationCounts) for c in counts):
        raise ValueError("immutable localization counts required")
    return LocalizationCounts(sum(c.true_positive for c in counts),sum(c.false_positive for c in counts),
                              sum(c.false_negative for c in counts),sum(c.matched_iou_sum for c in counts))
