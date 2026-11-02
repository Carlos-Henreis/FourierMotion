"""Regressões do modo de lápis contínuo e conectores pontilhados."""
import numpy as np
import cv2
from PIL import Image, ImageDraw

from fourier_motion.contours import extract_contours
from fourier_motion.continuous import make_continuous
from fourier_motion.fourier import analyze
from fourier_motion.render import _dotted_connectors, render_frame
from fourier_motion.config import Settings


def _two_squares(tmp_path):
    image = np.full((120, 240), 255, np.uint8)
    cv2.rectangle(image, (20, 30), (75, 90), 0, -1)
    cv2.rectangle(image, (160, 30), (215, 90), 0, -1)
    filename = tmp_path / "two.png"
    cv2.imwrite(str(filename), image)
    return extract_contours(filename, samples=512)


def test_continuous_preserves_sample_count_and_marks_bridges(tmp_path):
    signal = _two_squares(tmp_path)
    assert signal.count == 2
    route = make_continuous(signal)
    assert route.count == signal.count
    assert route.points.shape == signal.points.shape == (512, 2)
    assert np.any(route.path_ids < 0)
    assert len(set(route.path_ids[route.path_ids < 0])) == 2
    assert np.allclose(route.points.mean(axis=0), 0, atol=1e-12)
    # Uniform arclength sampling makes the periodic route continuous at t=1.
    steps = np.linalg.norm(np.roll(route.points, -1, axis=0) - route.points, axis=1)
    assert steps.max() < 5 * np.median(steps)


def test_mode_is_opt_in_and_fourier_sees_connector_samples(tmp_path):
    signal = _two_squares(tmp_path)
    assert np.all(signal.path_ids >= 0)
    route = make_continuous(signal)
    assert not np.allclose(signal.points, route.points)
    a = analyze(route.points, 0.005)
    assert a.error_percent < 0.005
    assert a.n_terms <= len(route.points) // 2


def test_one_contour_needs_no_artificial_travel(tmp_path):
    image = np.full((100, 100), 255, np.uint8)
    cv2.circle(image, (50, 50), 30, 0, -1)
    path = tmp_path / "one.png"
    cv2.imwrite(str(path), image)
    signal = extract_contours(path, samples=256)
    route = make_continuous(signal)
    assert route is signal
    assert not np.any(route.path_ids < 0)


def test_connector_rendered_as_dashes_not_solid():
    canvas = Image.new("RGB", (100, 50), "#08090d")
    points = np.asarray([[5, 20], [15, 20], [30, 20], [70, 20], [85, 20], [95, 20]])
    labels = np.asarray([0, 0, -1, -1, 1, 1])
    _dotted_connectors(ImageDraw.Draw(canvas), points, labels,
                       lambda x, y: (int(x), int(y)), "#00ffff")
    line = [canvas.getpixel((x, 20)) for x in range(16, 85)]
    assert any(pixel == (0, 255, 255) for pixel in line)
    assert any(pixel == (8, 9, 13) for pixel in line)


def test_continuous_video_frame_renders(tmp_path):
    route = make_continuous(_two_squares(tmp_path))
    analysis = analyze(route.points)
    cfg = Settings(samples=512, duration=60.0, width=540, height=960,
                   fps=12, hook_text="Dois quadrados")
    image = render_frame(analysis, route.path_ids, cfg, 0, 720)
    assert image.size == (540, 960)


def test_opening_has_no_bridges_and_other_scenes_use_gray(tmp_path, monkeypatch):
    import fourier_motion.render as renderer

    signal = make_continuous(_two_squares(tmp_path))
    analysis = analyze(signal.points)
    cfg = Settings(samples=512, duration=60, fps=12, width=540, height=960,
                   hook_text="A imagem original")
    calls = []
    actual = renderer._dotted_connectors

    def spy(*args, **kwargs):
        calls.append((kwargs.get("color", args[4] if len(args) > 4 else None),
                      kwargs.get("stop")))
        return actual(*args, **kwargs)

    monkeypatch.setattr(renderer, "_dotted_connectors", spy)
    total = round(cfg.duration * cfg.fps)

    renderer.render_frame(analysis, signal.path_ids, cfg, 0, total)
    assert calls == []  # Abertura só mostra o contorno original.

    renderer.render_frame(analysis, signal.path_ids, cfg, total - 1, total)
    assert calls == [("#8b9098", None)]

    calls.clear()
    frame = round((cfg.flash_seconds + cfg.transition_seconds + 1) * cfg.fps)
    renderer.render_frame(analysis, signal.path_ids, cfg, frame, total)
    assert all(color in {"#555960", "#8b9098"} for color, _ in calls)
    assert len(calls) == 2
