import numpy as np
import pytest
from fourier_motion.fourier import analyze
from fourier_motion.render import (
    sample_harmonics, stage_state, axis_value, _epicycles, _visual_scale, render_frame
)
from fourier_motion.config import Settings
from PIL import Image, ImageDraw


def _shape():
    t = np.arange(128) / 128
    return np.column_stack((
        40 * np.cos(2*np.pi*t) + 7 * np.cos(2*np.pi*9*t),
        50 * np.sin(2*np.pi*t) + 8 * np.sin(2*np.pi*7*t)
    ))


def test_sampled_n_contains_endpoints_and_is_increasing():
    ns = sample_harmonics(973, 1620)
    assert ns[0] == 1 and ns[-1] == 973
    assert all(a < b for a, b in zip(ns, ns[1:]))
    assert len(ns) <= 48


def test_each_stage_completes_a_cycle_before_increment():
    frames = 1620
    ns = sample_harmonics(973, frames)
    for idx, n in enumerate(ns):
        first = idx * frames // len(ns)
        last = (idx + 1) * frames // len(ns) - 1
        assert stage_state(first, frames, ns) == (n, 0.0, idx)
        n_last, phase, stage = stage_state(last, frames, ns)
        assert (n_last, stage) == (n, idx)
        assert phase == pytest.approx(1.0)


@pytest.mark.parametrize("n,t", [(1,0.0), (1,.31), (7,.55), (9,.75)])
def test_epicycle_endpoints_match_same_xy_phase(n, t):
    result = analyze(_shape())
    n = min(n, result.n_terms)
    img = Image.new("RGB", (600, 600))
    draw = ImageDraw.Draw(img)
    scale = 1.6
    cx, cy = 410.0, 320.0
    top = (cx + scale * result.coefficients_x[0].real, 100.0)
    left = (100.0, cy - scale * result.coefficients_y[0].real)
    ex = _epicycles(draw, result.coefficients_x, n, t, top, scale, "x", "#00ffff")
    ey = _epicycles(draw, result.coefficients_y, n, t, left, scale, "y", "#00ff00")
    x = axis_value(result.coefficients_x, n, t)
    y = axis_value(result.coefficients_y, n, t)
    assert ex.real == pytest.approx(cx + scale * x, abs=1e-8)
    assert ey.imag == pytest.approx(cy - scale * y, abs=1e-8)


def test_rendered_frame_has_expected_dimensions():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=4, final_seconds=1,
                   fps=12, width=540, height=960)
    labels = np.zeros(128, dtype=np.int32)
    frame = render_frame(result, labels, cfg, 4, 48)
    assert frame.size == (540, 960)
    assert _visual_scale(result, 540, 960) > 0
