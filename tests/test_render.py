import numpy as np
import pytest
from PIL import Image, ImageDraw
from fourier_motion.config import Settings
from fourier_motion.fourier import analyze
from fourier_motion.render import (
    visual_stages, stage_timing, axis_value, _epicycles,
    _visual_scale, render_frame,
)


def _shape():
    t = np.arange(128) / 128
    return np.column_stack((
        40 * np.cos(2 * np.pi * t) + 7 * np.cos(2 * np.pi * 9 * t),
        50 * np.sin(2 * np.pi * t) + 8 * np.sin(2 * np.pi * 7 * t),
    ))


def test_fixed_stages_do_not_exceed_visual_limit():
    result = analyze(_shape())
    cfg = Settings(samples=128, visual_max_terms=8)
    assert visual_stages(result, cfg) == (1, 2, 5, 8)


def test_timeline_has_flash_and_complete_cycles():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=60, fps=30)
    stages = visual_stages(result, cfg)
    total = round(cfg.duration * cfg.fps)
    assert stage_timing(0, total, cfg, stages)[0] == "flash"
    assert stage_timing(round(cfg.flash_seconds * cfg.fps), total, cfg, stages)[1] == 1
    assert stage_timing(total - 1, total, cfg, stages)[0] == "final"
    seen = set()
    for frame in range(total):
        mode, n, phase, index = stage_timing(frame, total, cfg, stages)
        if mode == "stage":
            if index not in seen:
                assert phase == 0.0
                seen.add(index)
    assert seen == set(range(len(stages)))


@pytest.mark.parametrize("n,t", [(1, 0.0), (1, .31), (7, .55), (9, .75)])
def test_synchronized_epicycles(n, t):
    result = analyze(_shape())
    n = min(n, result.n_terms)
    draw = ImageDraw.Draw(Image.new("RGB", (640, 640)))
    scale, cx, cy = 1.5, 410.0, 320.0
    ex = _epicycles(draw, result.coefficients_x, n, t,
                    (cx + scale * result.coefficients_x[0].real, 100.0),
                    scale, "x", "#00ffff")
    ey = _epicycles(draw, result.coefficients_y, n, t,
                    (100.0, cy - scale * result.coefficients_y[0].real),
                    scale, "y", "#00ff00")
    assert ex.real == pytest.approx(cx + scale * axis_value(
        result.coefficients_x, n, t), abs=1e-7)
    assert ey.imag == pytest.approx(cy - scale * axis_value(
        result.coefficients_y, n, t), abs=1e-7)


def test_frame_uses_configured_resolution_and_hook():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=30, final_seconds=3,
                   fps=12, width=540, height=960, visual_max_terms=8,
                   hook_text="Transformando um desenho em uma equação")
    labels = np.zeros(128, dtype=np.int32)
    frame = render_frame(result, labels, cfg, 0, 360)
    assert frame.size == (540, 960)
    assert _visual_scale(result, 540, 960, cfg) > 0


def test_insufficient_duration_rejected():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=8, final_seconds=2,
                   fps=30, visual_max_terms=9)
    stages = visual_stages(result, cfg)
    with pytest.raises(ValueError, match="Duração insuficiente"):
        stage_timing(30, 240, cfg, stages)
