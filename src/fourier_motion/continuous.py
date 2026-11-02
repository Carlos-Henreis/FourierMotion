"""Continuous pen route through multiple closed contours.

The FFT sees a single periodic polyline. Distinct contour loops are joined
with explicit travel edges, labeled by negative path IDs for dotted rendering.
"""
from dataclasses import replace
import numpy as np
from .contours import ContourSignal


def make_continuous(signal: ContourSignal) -> ContourSignal:
    """Greedy nearest-contour route, arclength-resampled to the original M points.

    One continuous periodic signal includes all paths and travel connectors.
    No artificial pen lifts are introduced into the Fourier input. Original
    contour loops are explicitly closed before moving to the next one.

    Positive/zero path_ids identify contour strokes; negative IDs identify
    individual travel connections. These are *rendering* labels only.
    """
    if signal.count <= 1:
        return signal
    points = np.asarray(signal.points, dtype=np.float64)
    labels = np.asarray(signal.path_ids)
    if len(points) != len(labels) or len(points) < 4:
        raise ValueError("Sinal de contornos incompatível")
    paths = [points[labels == i] for i in range(signal.count)]
    if any(len(path) < 3 for path in paths):
        raise ValueError("Contorno com menos de três amostras")

    first = paths[0]
    remaining = set(range(1, len(paths)))
    ordered = [(0, first)]
    current = first[0]
    while remaining:
        choice = min(
            ((float(np.linalg.norm(path - current, axis=1).min()), idx)
             for idx, path in enumerate(paths) if idx in remaining),
            key=lambda item: (item[0], item[1]),
        )[1]
        path = paths[choice]
        start = int(np.argmin(np.linalg.norm(path - current, axis=1)))
        path = np.roll(path, -start, axis=0)
        ordered.append((choice, path))
        current = path[0]
        remaining.remove(choice)

    # Build a list of directed edges. The last connector leads to the first
    # contour's start, so the signal is periodic without a teleport at t=1.
    a_points = []
    b_points = []
    edge_labels = []
    for rank, (_source_id, path) in enumerate(ordered):
        closed = np.vstack((path, path[0]))
        a_points.extend(closed[:-1])
        b_points.extend(closed[1:])
        edge_labels.extend([rank] * len(path))
        successor = ordered[(rank + 1) % len(ordered)][1][0]
        a_points.append(path[0])
        b_points.append(successor)
        edge_labels.append(-(rank + 1))

    starts = np.asarray(a_points, dtype=np.float64)
    ends = np.asarray(b_points, dtype=np.float64)
    kinds = np.asarray(edge_labels, dtype=np.int32)
    lengths = np.linalg.norm(ends - starts, axis=1)
    valid = lengths > 1e-12
    starts, ends, kinds, lengths = (a[valid] for a in (starts, ends, kinds, lengths))
    if not len(lengths):
        raise ValueError("Trajeto contínuo degenerado")
    cumulative = np.r_[0.0, np.cumsum(lengths)]
    locations = np.linspace(0.0, cumulative[-1], len(points), endpoint=False)
    indexes = np.searchsorted(cumulative[1:], locations, side="right")
    indexes = np.minimum(indexes, len(lengths) - 1)
    fractions = (locations - cumulative[indexes]) / lengths[indexes]
    sampled = starts[indexes] + (ends[indexes] - starts[indexes]) * fractions[:, None]
    sampled -= sampled.mean(axis=0)
    return replace(signal, points=sampled, path_ids=kinds[indexes])
