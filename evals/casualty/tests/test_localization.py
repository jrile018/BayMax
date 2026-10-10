"""Hand-computed geometric controls, not a detector benchmark."""
import pytest
from services.casualty.contracts import FaceBox


def box(x1=0,y1=0,x2=1,y2=1,score=.9):
    return FaceBox(x1,y1,x2,y2,score)


def test_iou_is_hand_computed_area_ratio():
    from evals.casualty.localization import iou
    assert iou(box(),box(0,0,.5,.5))==.25
    assert iou(box(0,0,.25,.25),box(.5,.5,.75,.75))==0


def test_duplicate_predictions_count_as_false_positive():
    from evals.casualty.localization import localization_counts
    result=localization_counts((box(),box(score=.8)),(box(),),iou_threshold=.5)
    assert (result.true_positive,result.false_positive,result.false_negative)==(1,1,0)
    assert result.precision==.5
    assert result.recall==1
    assert result.mean_matched_iou==1


def test_empty_scene_false_positive_and_missing_face_are_retained():
    from evals.casualty.localization import localization_counts, aggregate
    fp=localization_counts((box(),),())
    miss=localization_counts((),(box(),))
    assert (fp.false_positive,fp.recall)==(1,None)
    assert (miss.false_negative,miss.precision)==(1,None)
    total=aggregate((fp,miss))
    assert (total.true_positive,total.false_positive,total.false_negative)==(0,1,1)
    assert total.precision==0 and total.recall==0
    assert total.mean_matched_iou is None


def test_score_ordered_one_to_one_matching_is_deterministic():
    from evals.casualty.localization import localization_counts
    result=localization_counts((box(0,0,.5,1,.95),box(0,0,.5,1,.8),box(.5,0,1,1,.7)),
                               (box(0,0,.5,1),box(.5,0,1,1)))
    assert (result.true_positive,result.false_positive,result.false_negative)==(2,1,0)


@pytest.mark.parametrize("threshold",[0,-.1,1.1,float("nan"),True])
def test_invalid_threshold_is_rejected(threshold):
    from evals.casualty.localization import localization_counts
    with pytest.raises(ValueError):localization_counts((box(),),(box(),),iou_threshold=threshold)


def test_malformed_predictions_are_not_silently_counted_as_success():
    from evals.casualty.localization import localization_counts
    with pytest.raises(ValueError):localization_counts(("not-a-box",),(box(),))
