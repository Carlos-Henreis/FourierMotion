import numpy as np
import pytest
from PIL import Image, ImageDraw
from fourier_motion.config import Settings
from fourier_motion.fourier import analyze
from fourier_motion.render import (
    visual_stages, stage_timing, axis_value, _epicycles,
    _visual_scale, render_frame, _vibrant_transition,
)


def _shape():
    t = np.arange(128) / 128
    return np.column_stack((
        40 * np.cos(2 * np.pi * t) + 7 * np.cos(2 * np.pi * 9 * t),
        50 * np.sin(2 * np.pi * t) + 8 * np.sin(2 * np.pi * 7 * t),
    ))


def test_final_stage_always_uses_true_n():
    result = analyze(_shape())
    cfg = Settings(samples=128, visual_max_terms=5)
    stages = visual_stages(result, cfg)
    assert stages[0] == 1
    assert stages[-1] == result.n_terms
    assert 5 in stages
    assert stages == tuple(sorted(set(stages)))


def test_timeline_includes_both_transitions_and_complete_cycles():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=60, fps=30)
    stages = visual_stages(result, cfg)
    total = round(cfg.duration * cfg.fps)
    opening = round(cfg.flash_seconds * cfg.fps)
    transition = round(cfg.transition_seconds * cfg.fps)
    cycle = round(cfg.cycle_seconds * cfg.fps)
    assert stage_timing(0, total, cfg, stages)[0] == "flash"
    assert stage_timing(opening - 1, total, cfg, stages)[0] == "flash"
    assert stage_timing(opening, total, cfg, stages)[0] == "transition_in"
    assert stage_timing(opening + transition - 1, total, cfg, stages)[0] == "transition_in"
    first = opening + transition
    for index, n in enumerate(stages):
        assert stage_timing(first + index * cycle, total, cfg, stages) == (
            "stage", n, 0.0, index)
        assert stage_timing(first + (index + 1) * cycle - 1, total, cfg, stages) == (
            "stage", n, 1.0, index)
    end = first + len(stages) * cycle
    assert stage_timing(end, total, cfg, stages)[0] == "transition_out"
    assert stage_timing(end + transition, total, cfg, stages)[0] == "final"
    assert stage_timing(total - 1, total, cfg, stages)[0] == "final"


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


def test_original_opening_and_final_frame_have_expected_dimensions():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=30, final_seconds=3,
                   fps=12, width=540, height=960, visual_max_terms=8,
                   hook_text="Transformando um desenho em uma equação")
    labels = np.zeros(128, dtype=np.int32)
    first = render_frame(result, labels, cfg, 0, 360)
    last = render_frame(result, labels, cfg, 359, 360)
    assert first.size == last.size == (540, 960)
    assert _visual_scale(result, 540, 960, cfg, "flash") < _visual_scale(
        result, 540, 960, cfg, "final")
    # Original and reconstructed paths differ for nonzero approximation error.
    assert not np.array_equal(np.asarray(first), np.asarray(last))


def test_transition_preserves_endpoints():
    a = Image.new("RGB", (120, 240), "#08090d")
    b = Image.new("RGB", (120, 240), "#ffdc45")
    assert list(_vibrant_transition(a, b, 0.0).getdata()) == list(a.getdata())
    assert list(_vibrant_transition(a, b, 1.0).getdata()) == list(b.getdata())


def test_insufficient_duration_rejected():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=8, final_seconds=2,
                   fps=30, visual_max_terms=9)
    with pytest.raises(ValueError, match="Duração insuficiente"):
        stage_timing(30, 240, cfg, visual_stages(result, cfg))
