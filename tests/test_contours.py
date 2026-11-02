import cv2
import numpy as np
from fourier_motion.contours import extract_contours, resample_closed


def test_resampling_count():
    points = np.array([[0, 0], [10, 0], [10, 10], [0, 10]])
    result = resample_closed(points, 40)
    assert result.shape == (40, 2)
    assert np.isfinite(result).all()


def test_hole_and_external_contour(tmp_path):
    img = np.full((160, 160), 255, dtype=np.uint8)
    cv2.circle(img, (80, 80), 55, 0, -1)
    cv2.circle(img, (80, 80), 25, 255, -1)
    path = tmp_path / "test.png"
    cv2.imwrite(str(path), img)
    signal = extract_contours(path, samples=256)
    assert signal.count >= 2
    assert signal.points.shape == (256, 2)
    assert len(np.unique(signal.path_ids)) >= 2
