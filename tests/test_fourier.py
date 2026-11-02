import numpy as np
import pytest
from fourier_motion.fourier import analyze, reconstruct, relative_error


def test_circle_one_harmonic():
    t = np.arange(256) / 256
    xy = np.column_stack((80*np.cos(2*np.pi*t), 80*np.sin(2*np.pi*t)))
    result = analyze(xy)
    assert result.n_terms == 1
    assert result.error_percent < 1e-9


def test_high_frequency():
    t = np.arange(256) / 256
    xy = np.column_stack((100*np.cos(2*np.pi*t)+25*np.cos(2*np.pi*14*t),
                          100*np.sin(2*np.pi*t)+25*np.sin(2*np.pi*14*t)))
    result = analyze(xy)
    assert result.n_terms == 14
    assert result.error_percent < .05
    assert np.all(np.diff(result.error_history) <= 1e-9)


def test_insufficient_limit_fails():
    t = np.arange(128) / 128
    xy = np.column_stack((np.cos(2*np.pi*20*t), np.sin(2*np.pi*20*t)))
    with pytest.raises(ValueError, match="não alcançado"):
        analyze(xy, max_terms=10)


def test_direct_error():
    points = np.column_stack((np.arange(64), np.sin(np.arange(64))))
    result = analyze(points)
    rebuilt = reconstruct(result.coefficients_x, result.coefficients_y, result.n_terms, 64)
    assert relative_error(points, rebuilt, result.scale) == pytest.approx(result.error_percent)


def test_reject_degenerate():
    with pytest.raises(ValueError, match="degenerado"):
        analyze(np.zeros((64, 2)))
