"""Fourier real em X/Y, convergência estrita e geometria dos epiciclos."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Analysis:
    coefficients_x: np.ndarray
    coefficients_y: np.ndarray
    original: np.ndarray
    reconstructed: np.ndarray
    n_terms: int
    error_percent: float
    scale: float
    error_history: np.ndarray


def relative_error(original: np.ndarray, reconstructed: np.ndarray, scale: float) -> float:
    """RMSE euclidiano 2D dividido pela diagonal do bounding box original."""
    if scale <= 0:
        raise ValueError("Escala deve ser positiva")
    return float(100 * np.sqrt(np.mean(np.sum((original - reconstructed) ** 2, axis=1))) / scale)


def reconstruct(cx: np.ndarray, cy: np.ndarray, n_terms: int, samples: int) -> np.ndarray:
    """Reconstrói pelo termo DC e frequências positivas 1..N (pares conjugados implícitos)."""
    if not 0 <= n_terms < len(cx):
        raise ValueError("Número de harmônicos inválido")
    fx, fy = np.zeros_like(cx), np.zeros_like(cy)
    fx[:n_terms + 1] = cx[:n_terms + 1]
    fy[:n_terms + 1] = cy[:n_terms + 1]
    return np.column_stack((np.fft.irfft(fx * samples, n=samples),
                            np.fft.irfft(fy * samples, n=samples)))


def analyze(points: np.ndarray, threshold_percent: float = 0.05,
            max_terms: int | None = None) -> Analysis:
    """Menor corte N com erro < limiar; Parseval + verificação por iFFT."""
    original = np.asarray(points, dtype=np.float64)
    if original.ndim != 2 or original.shape[1] != 2 or len(original) < 4:
        raise ValueError("Esperado contorno Nx2 com no mínimo 4 pontos")
    if len(original) % 2:
        raise ValueError("Amostragem deve ter número par de pontos")
    if not np.isfinite(original).all() or threshold_percent <= 0:
        raise ValueError("Pontos ou limiar inválidos")
    count = len(original)
    scale = float(np.linalg.norm(np.ptp(original, axis=0)))
    if scale < 1e-12:
        raise ValueError("Contorno degenerado")
    cx = np.fft.rfft(original[:, 0]) / count
    cy = np.fft.rfft(original[:, 1]) / count
    limit = count // 2 if max_terms is None else min(max_terms, count // 2)
    if limit < 1:
        raise ValueError("max_terms deve ser >= 1")
    energy = np.abs(cx) ** 2 + np.abs(cy) ** 2
    weights = np.full(len(energy), 2.0)
    weights[0] = weights[-1] = 1.0
    weighted = weights * energy
    # Erro quadrático residual = energia de frequências não retidas (Parseval).
    residual = np.r_[np.cumsum(weighted[::-1])[::-1], 0.0]
    errors = np.array([100 * np.sqrt(max(0.0, residual[k + 1])) / scale
                       for k in range(limit + 1)])
    qualifying = np.flatnonzero(errors[1:] < threshold_percent)
    if len(qualifying) == 0:
        raise ValueError(f"Erro < {threshold_percent}% não alcançado até N={limit}. "
                         f"Erro final: {errors[-1]:.8f}%")
    n = int(qualifying[0] + 1)
    reconstructed = reconstruct(cx, cy, n, count)
    verified = relative_error(original, reconstructed, scale)
    if not verified < threshold_percent:
        raise RuntimeError("Verificação numérica da convergência falhou")
    return Analysis(cx, cy, original, reconstructed, n, verified, scale, errors)


def epicycle_chain(coefficients: np.ndarray, n_terms: int, t: float):
    """Segmentos 1D (início, fim, raio) dos termos reais da série no instante t."""
    if n_terms < 0 or n_terms >= len(coefficients):
        raise ValueError("Número de harmônicos inválido")
    k = np.arange(1, n_terms + 1)
    factors = np.full(n_terms, 2.0)
    if n_terms == len(coefficients) - 1 and n_terms:
        factors[-1] = 1.0  # Nyquist não tem par conjugado distinto
    terms = factors * np.real(coefficients[1:n_terms + 1] * np.exp(2j * np.pi * k * t))
    endpoints = np.cumsum(np.r_[coefficients[0].real, terms])
    radii = factors * np.abs(coefficients[1:n_terms + 1])
    return endpoints[:-1], endpoints[1:], radii
