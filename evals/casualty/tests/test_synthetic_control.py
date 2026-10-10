"""Fixed exploratory synthetic montage control; no real-photo accuracy claim."""
import pytest
from services.casualty.contracts import FaceBox
from evals.casualty.synthetic_control import validate_montage_boxes


def cells():
    return tuple(FaceBox((x + .2) / 4, (y + .1) / 2,
                         (x + .8) / 4, (y + .9) / 2, .95)
                 for y in range(2) for x in range(4))


def test_one_box_wholly_inside_each_fixed_cell_passes():
    assert validate_montage_boxes(cells()) == tuple(range(8))


def test_missing_or_duplicate_box_fails():
    with pytest.raises(ValueError, match="exactly eight"):
        validate_montage_boxes(cells()[:-1])
    with pytest.raises(ValueError, match="one per cell"):
        validate_montage_boxes(cells()[:-1] + (cells()[0],))


def test_low_score_or_cell_spill_fails():
    bad = list(cells())
    bad[0] = FaceBox(.05, .05, .20, .45, .89)
    with pytest.raises(ValueError, match="score"):
        validate_montage_boxes(tuple(bad))
    bad[0] = FaceBox(.05, .05, .26, .45, .95)
    with pytest.raises(ValueError, match="cell"):
        validate_montage_boxes(tuple(bad))


def test_verified_bytes_survive_image_path_replacement(tmp_path):
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image
    from evals.casualty.run_synthetic_control import checked_bytes, decode_verified_image

    path = tmp_path / "montage.jpg"
    def jpeg(rgb):
        out = BytesIO()
        Image.new("RGB", (1024, 512), rgb).save(out, format="JPEG")
        return out.getvalue()

    original = jpeg((240, 10, 10))
    path.write_bytes(original)
    verified = checked_bytes(path, sha256(original).hexdigest(), 2_000_000)
    path.write_bytes(jpeg((10, 10, 240)))
    bgr = decode_verified_image(verified)
    assert bgr.shape == (512, 1024, 3)
    assert int(bgr[0, 0, 2]) > 200
    assert int(bgr[0, 0, 0]) < 50
