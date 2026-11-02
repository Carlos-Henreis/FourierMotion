"""Segmentação de imagem e reamostragem de múltiplos contornos."""
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass(frozen=True)
class ContourSignal:
    points: np.ndarray
    path_ids: np.ndarray
    original_size: tuple[int, int]
    count: int


def resample_closed(points: np.ndarray, count: int) -> np.ndarray:
    """Pontos equidistantes ao longo de uma curva fechada."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 3 or count < 3:
        raise ValueError("Contorno degenerado ou amostragem insuficiente")
    pts = np.vstack((pts, pts[0]))
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    keep = np.r_[True, seg > 1e-10]
    pts = pts[keep]
    if len(pts) < 2:
        raise ValueError("Contorno de comprimento zero")
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    if distance[-1] <= 0:
        raise ValueError("Contorno de comprimento zero")
    targets = np.linspace(0, distance[-1], count, endpoint=False)
    return np.column_stack((np.interp(targets, distance, pts[:, 0]),
                            np.interp(targets, distance, pts[:, 1])))


def _allocate_counts(lengths: np.ndarray, total: int, minimum: int = 8) -> np.ndarray:
    if len(lengths) * minimum > total:
        raise ValueError("Contornos demais para a quantidade de amostras")
    remainder = total - minimum * len(lengths)
    extra_f = remainder * lengths / lengths.sum()
    extra = np.floor(extra_f).astype(int)
    order = np.argsort(-(extra_f - extra))
    extra[order[:int(remainder - extra.sum())]] += 1
    return extra + minimum


def extract_contours(path: str | Path, samples: int = 2048,
                     min_length: float = 25.0, max_contours: int = 128) -> ContourSignal:
    """PNG transparente usa alpha; imagem opaca usa binarização Otsu.

    Inclui contornos internos e externos, preservando ids para não traçar
    linhas artificiais entre ilhas separadas na visualização.
    """
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Imagem não encontrada ou inválida: {path}")
    if image.ndim == 2:
        gray, mask = image, None
    else:
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
        mask = image[:, :, 3] if image.shape[2] == 4 and np.any(image[:, :, 3] < 250) else None
    if mask is None:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.count_nonzero(mask) > mask.size // 2:
            mask = cv2.bitwise_not(mask)
    else:
        mask = np.where(mask > 127, 255, 0).astype(np.uint8)
    found, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    paths = [c[:, 0, :].astype(float) for c in found
             if len(c) >= 3 and cv2.arcLength(c, True) >= min_length]
    paths.sort(key=lambda p: cv2.arcLength(p.astype(np.float32).reshape(-1, 1, 2), True),
               reverse=True)
    if not paths:
        raise ValueError("Nenhum contorno válido encontrado")
    if len(paths) > max_contours:
        raise ValueError(f"{len(paths)} contornos excedem o limite de {max_contours}")
    lengths = np.array([np.linalg.norm(np.diff(np.vstack((p, p[0])), axis=0), axis=1).sum()
                        for p in paths])
    counts = _allocate_counts(lengths, samples)
    pts = np.concatenate([resample_closed(p, int(n)) for p, n in zip(paths, counts)])
    labels = np.concatenate([np.full(int(n), i, dtype=np.int32) for i, n in enumerate(counts)])
    pts[:, 1] *= -1
    pts -= pts.mean(axis=0)
    return ContourSignal(pts, labels, (gray.shape[1], gray.shape[0]), len(paths))
