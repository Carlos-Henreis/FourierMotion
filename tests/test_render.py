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


def test_timeline_final_payoff_only_in_last_seven_seconds():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=60, fps=30)
    stages = visual_stages(result, cfg)
    total = round(cfg.duration * cfg.fps)
    opening = round(cfg.flash_seconds * cfg.fps)
    transition = round(cfg.transition_seconds * cfg.fps)
    final_frames = round(cfg.final_seconds * cfg.fps)

    assert cfg.final_seconds == 7.0
    assert stage_timing(0, total, cfg, stages)[0] == "flash"
    assert stage_timing(opening-1, total, cfg, stages)[0] == "flash"
    assert stage_timing(opening, total, cfg, stages)[0] == "transition_in"
    assert stage_timing(opening + transition, total, cfg, stages)[0] == "stage"
    assert stage_timing(total - final_frames - 1, total, cfg, stages)[0] == "transition_out"
    assert stage_timing(total - final_frames, total, cfg, stages)[0] == "final"
    assert stage_timing(total - 1, total, cfg, stages)[0] == "final"

    # No idle interval: every frame from start to end has a meaningful scene.
    modes = [stage_timing(f, total, cfg, stages)[0] for f in range(total)]
    assert modes.count("final") == final_frames
    assert modes.count("transition_in") == transition
    assert modes.count("transition_out") == transition
    assert modes.count("stage") == total - opening - 2*transition - final_frames
    assert set(modes) == {"flash", "transition_in", "stage", "transition_out", "final"}
    assert all(modes[i] == modes[i+1] or
               (modes[i], modes[i+1]) in {
                   ("flash","transition_in"), ("transition_in","stage"),
                   ("stage","transition_out"), ("transition_out","final")}
               for i in range(total-1))


def test_dynamic_milestones_depend_on_actual_n():
    from dataclasses import replace
    result = analyze(_shape())
    cfg = Settings(samples=2048, visual_max_terms=200)
    large = replace(result, n_terms=997)
    stages = visual_stages(large, cfg)
    assert stages[:8] == (1, 2, 5, 15, 40, 100, 150, 200)
    assert stages[-1] == 997
    middle = [n for n in stages if 200 < n < 997]
    assert len(middle) == 2
    assert middle[0] < middle[1]
    assert visual_stages(replace(result, n_terms=400), cfg)[-1] == 400


def test_stages_have_complete_revolutions_and_no_static_holds():
    result = analyze(_shape())
    cfg = Settings(samples=128, duration=60, fps=30)
    stages = visual_stages(result, cfg)
    total = cfg.duration * cfg.fps
    stage_frames = [(f, stage_timing(f, int(total), cfg, stages))
                    for f in range(int(total))]
    for index, n in enumerate(stages):
        frames = [(f, state[2]) for f, state in stage_frames
                  if state[0] == "stage" and state[3] == index]
        assert len(frames) >= 2
        assert frames[0][1] == 0.0
        assert frames[-1][1] == 1.0
        assert all(0 <= phase <= 1 for _, phase in frames)
        # Any reset from phase=1 to 0 is intentional: another whole loop.
        for (f1, p1), (f2, p2) in zip(frames, frames[1:]):
            assert f2 == f1 + 1
            assert p2 >= p1 or (p1 == 1.0 and p2 == 0.0)


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


def test_viral_preset_has_twenty_second_payoff_and_few_cycles():
    result = analyze(_shape())
    cfg = Settings(preset="viral", samples=128, duration=20, fps=30,
                   flash_seconds=0.5, transition_seconds=0.2,
                   final_seconds=4.0, visual_max_terms=64,
                   stage_terms=(1, 2, 5, 15, 40, 100, 150, 200))
    cfg.validate()
    stages = visual_stages(result, cfg)
    assert stages[0] == 1
    assert stages[-1] == result.n_terms
    assert len(stages) <= 6
    total = 600
    assert stage_timing(0, total, cfg, stages)[0] == "flash"
    assert stage_timing(15, total, cfg, stages)[0] == "transition_in"
    assert stage_timing(30, total, cfg, stages)[0] == "stage"
    assert stage_timing(480, total, cfg, stages)[0] == "final"
    assert stage_timing(599, total, cfg, stages)[0] == "final"
    labels = np.zeros(len(result.original), dtype=int)
    image = render_frame(result, labels, cfg, 30, total)
    assert image.size == (cfg.width, cfg.height)


def test_viral_has_larger_rendering_area_than_classic():
    from dataclasses import replace
    result = analyze(_shape())
    classic = Settings()
    viral = replace(classic, preset="viral")
    assert _visual_scale(result, 1080, 1920, viral, "stage") > (
        _visual_scale(result, 1080, 1920, classic, "stage")
    )
