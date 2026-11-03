"""Renderização Pillow transmitida diretamente para FFmpeg, sem PNGs intermediários."""
from pathlib import Path
import shutil
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .config import Settings
from .fourier import Analysis, reconstruct
from .audio import ffmpeg_command, validate_audio


def _font(size: int, serif: bool = False):
    names = (["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"] if serif else
             ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    names.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def _paths(draw, points, labels, project, color, width):
    for label in np.unique(labels):
        if label < 0:
            continue  # travel bridges are rendered with dashed strokes
        segment = points[labels == label]
        if len(segment) >= 2:
            xy = [project(*point) for point in segment]
            draw.line(xy, fill=color, width=width, joint="curve")
            draw.line((xy[-1], xy[0]), fill=color, width=width)


def visual_stages(analysis: Analysis, cfg: Settings) -> tuple[int, ...]:
    """Return user milestones plus adaptive high-frequency bridges and true N*.

    The automatic values depend on the actual spectral cutoff, not on a
    specific input image. Geometric spacing helps avoid a final huge jump.
    """
    final_n = analysis.n_terms
    if cfg.preset == "viral":
        # Fewer stages, all bounded by the true Fourier cutoff.
        return tuple(sorted({min(final_n, n) for n in
                             (1, 5, 25, 100, 250, final_n)}))
    limit = min(final_n, cfg.visual_max_terms)
    stages = {1, final_n}
    stages.update(n for n in cfg.stage_terms if 1 <= n <= limit)
    if final_n > limit and final_n - limit >= 180:
        # Up to two dynamic milestones between the highest visible cutoff
        # and the mathematically converged solution.
        for fraction in (1 / 3, 2 / 3):
            value = round(limit * (final_n / limit) ** fraction)
            if limit < value < final_n:
                stages.add(value)
    return tuple(sorted(stages))


def _stage_boundaries(total: int, cfg: Settings, stages: tuple[int, ...]):
    """Integer-frame partition; final starts exactly at total-final_frames."""
    opening = round(cfg.flash_seconds * cfg.fps)
    transition = round(cfg.transition_seconds * cfg.fps)
    final_frames = round(cfg.final_seconds * cfg.fps)
    end_cycles = total - transition - final_frames
    start_cycles = opening + transition
    available = end_cycles - start_cycles
    count = len(stages)
    if count == 0 or available < count * 2:
        raise ValueError("Duração insuficiente para os ciclos de Fourier")
    lengths = [((i + 1) * available // count - i * available // count)
               for i in range(count)]
    boundaries = [start_cycles]
    for length in lengths:
        boundaries.append(boundaries[-1] + length)
    return opening, transition, boundaries, final_frames


def stage_timing(frame: int, total: int, cfg: Settings, stages: tuple[int, ...]):
    """Opening, transitions, paced cycles and an exact final payoff.

    Stages divide all the available time. Slow cycles or additional complete
    revolutions are chosen per stage to fit its allotted integer frame budget.
    """
    opening, transition, boundaries, final_frames = _stage_boundaries(
        total, cfg, stages)
    if frame < opening:
        return ("flash", stages[-1], 1.0, -1)
    if frame < opening + transition:
        return ("transition_in", stages[0],
                (frame - opening) / max(1, transition - 1), 0)
    if frame < boundaries[-1]:
        index = int(np.searchsorted(boundaries[1:], frame, side="right"))
        length = boundaries[index + 1] - boundaries[index]
        position = frame - boundaries[index]
        preferred = max(2, round(cfg.cycle_seconds * cfg.fps))
        # For short stage slots, one slower revolution; when slots are long,
        # show multiple full revolutions rather than leaving idle frames.
        revolutions = max(1, round(length / preferred))
        revolutions = min(revolutions, length // 2)
        revolution_index = min(revolutions - 1, position * revolutions // length)
        begin = revolution_index * length // revolutions
        end = (revolution_index + 1) * length // revolutions
        phase = (position - begin) / max(1, end - begin - 1)
        return ("stage", stages[index], min(1.0, phase), index)
    transition_start = boundaries[-1]
    if frame < transition_start + transition:
        return ("transition_out", stages[-1],
                (frame - transition_start) / max(1, transition - 1),
                len(stages) - 1)
    return ("final", stages[-1], 1.0, len(stages) - 1)


def _terms(coeff: np.ndarray, n: int, t: float) -> np.ndarray:
    k = np.arange(1, n + 1)
    factor = np.full(n, 2.0)
    if n == len(coeff) - 1:
        factor[-1] = 1.0
    return factor * coeff[1:n + 1] * np.exp(2j * np.pi * k * t)


def axis_value(coeff: np.ndarray, n: int, t: float) -> float:
    """Avalia a mesma série trigonométrica usada pela iFFT para o desenho."""
    return float(coeff[0].real + _terms(coeff, n, t).real.sum())


def _highlight_indices(coeff: np.ndarray, n: int, max_visible: int = 8) -> np.ndarray:
    """Seleciona apenas círculos visualmente dominantes sem alterar a reconstrução."""
    importance = 2 * np.abs(coeff[1:n + 1])
    return np.sort(np.argsort(-importance)[:max_visible] + 1)


def _epicycles(draw, coeff: np.ndarray, n: int, t: float, origin: tuple[float, float],
               scale: float, axis: str, color: str, visible: int = 8):
    """Desenha vetores complexos orientados por eixo e retorna projeção exata.

    Círculos exibidos = harmônicos mais relevantes; os demais compõem um
    vetor residual pontilhado. Nenhum termo é descartado do valor projetado.
    """
    selected = _highlight_indices(coeff, n, visible)
    pos = complex(*origin)
    for k in selected:
        factor = 1 if k == len(coeff) - 1 else 2
        v = factor * coeff[k] * np.exp(2j * np.pi * k * t)
        screen_delta = scale * (v if axis == "x" else -1j * v)
        new_pos = pos + screen_delta
        radius = scale * factor * abs(coeff[k])
        if radius > 1.0:
            draw.ellipse((pos.real-radius, pos.imag-radius,
                          pos.real+radius, pos.imag+radius), outline=color, width=2)
            draw.line((pos.real, pos.imag, new_pos.real, new_pos.imag),
                      fill=color, width=2)
        pos = new_pos

    full = _terms(coeff, n, t).sum()
    chosen = sum((factor * coeff[k] * np.exp(2j * np.pi * k * t)
                  for k in selected
                  for factor in [1 if k == len(coeff) - 1 else 2]), 0j)
    remaining = full - chosen
    target = pos + scale * (remaining if axis == "x" else -1j * remaining)
    if abs(target - pos) > 1:
        draw.line((pos.real, pos.imag, target.real, target.imag),
                  fill="#727781", width=2)
    draw.ellipse((target.real-4, target.imag-4,
                  target.real+4, target.imag+4), fill="#ffffff")
    return target


def _dashed(draw, start, end, color, width=2, dash=10, gap=8):
    a = np.array(start, dtype=float)
    b = np.array(end, dtype=float)
    delta = b - a
    length = float(np.linalg.norm(delta))
    if length == 0:
        return
    direction = delta / length
    for offset in np.arange(0, length, dash + gap):
        p = a + direction * offset
        q = a + direction * min(offset + dash, length)
        draw.line((tuple(p), tuple(q)), fill=color, width=width)


def _visual_scale(analysis: Analysis, w: int, h: int, cfg: Settings,
                  scene: str = "stage") -> float:
    """Escala APENAS o desenho, sem reduzi-lo pelos raios dos epiciclos.

    A figura ocupa a maior parte da região central do vídeo. Mantemos
    margens para os textos no topo e as fórmulas na parte inferior.
    """
    width, height = np.ptp(analysis.original, axis=0)
    if cfg.preset == "viral":
        if scene == "flash":
            region_width, region_height = w * .86, h * .55
        elif scene == "final":
            region_width, region_height = w * .90, h * .59
        else:
            region_width, region_height = w * .85, h * .55
    elif scene == "flash":
        region_width, region_height = w * .74, h * .40
    elif scene == "final":
        region_width, region_height = w * .82, h * .53
    else:
        region_width, region_height = w * .66, h * .47
    return min(region_width / max(width, 1e-9),
               region_height / max(height, 1e-9))


def _circle_scale(analysis: Analysis, w: int, h: int, cfg: Settings,
                  axis: str, n: int) -> float:
    """Epiciclos usam painel próprio; t é idêntico ao do desenho.

    A escala separada conserva a figura grande sem cortar os círculos.
    Projeções são conectadas ao mesmo cursor por linhas tracejadas.
    """
    coeff = analysis.coefficients_x if axis == "x" else analysis.coefficients_y
    indices = _highlight_indices(coeff, n)
    total = sum((1 if k == len(coeff) - 1 else 2) * abs(coeff[k])
                for k in indices)
    if total < 1e-9:
        return 1.0
    radius_budget = h * .11 if axis == "x" else w * .14
    return radius_budget / max(2 * total, 1e-9)


def _hook(draw, cfg: Settings, elapsed: float):
    if not cfg.hook_text or elapsed >= (2.5 if cfg.preset == "viral" else cfg.flash_seconds):
        return
    # Wrap to avoid clipping long dynamic captions.
    import textwrap
    lines = textwrap.wrap(cfg.hook_text, width=max(15, cfg.width // 30))
    lines = lines[:3]
    top = cfg.height * .085
    line_height = max(34, cfg.width // 22)
    draw.rounded_rectangle(
        (cfg.width * .06, top - 32,
         cfg.width * .94, top + line_height * len(lines) + 26),
        radius=24, fill="#161923"
    )
    for index, line in enumerate(lines):
        draw.text((cfg.width * .5, top + index * line_height),
                  line, anchor="mt", font=_font(max(18, cfg.width // 28), True),
                  fill="#f7f4ed")


def _draw_partial_paths(draw, points, labels, stop, project, color, width):
    """Rastro parcial sem unir caminhos independentes."""
    for label in np.unique(labels[:stop]):
        if label < 0:
            continue
        sub = points[:stop][labels[:stop] == label]
        if len(sub) > 1:
            draw.line([project(*p) for p in sub], fill=color, width=width, joint="curve")


def _dotted_connectors(draw, points, labels, project, color, width=2,
                       stop=None):
    """Draw each explicitly labeled travel segment as a dotted polyline.

    Travel labels are negative unique IDs. The end of each connector is
    joined to the next contour point, including the final cyclic return;
    it is *never* painted as an ordinary solid contour.
    """
    count = len(labels)
    visible = count if stop is None else min(count, max(0, stop))
    if visible == 0 or not np.any(labels < 0):
        return
    for marker in np.unique(labels[labels < 0]):
        indexes = np.flatnonzero(labels == marker)
        indexes = indexes[indexes < visible]
        if not len(indexes):
            continue
        first, last = int(indexes[0]), int(indexes[-1])
        indices = []
        if first > 0:
            indices.append(first - 1)
        indices.extend(indexes.tolist())
        next_index = (last + 1) % count
        if next_index < visible and (last + 1 < count or visible == count):
            indices.append(next_index)
        if len(indices) < 2:
            continue
        xy = [project(*points[index]) for index in indices]
        for a, b in zip(xy[:-1], xy[1:]):
            _dashed(draw, a, b, color, width=width, dash=4, gap=5)


def _stroke_style(labels: np.ndarray, width: int) -> dict:
    """Adaptive weights: intricate line art needs sharper, thinner strokes.

    Distinct non-negative path IDs count the actual contours; negative IDs
    are pen-travel connectors, not image detail.
    """
    contours = len(np.unique(labels[labels >= 0]))
    intricate = contours >= 12
    if intricate:
        return {"line": max(2, round(width / 540)),
                "glow": max(5, round(width / 200)),
                "blur": max(5, round(width / 180)),
                "glow_alpha": 0.40, "guide": 1}
    return {"line": max(4, width // 210),
            "glow": max(12, width // 75),
            "blur": max(9, width // 75),
            "glow_alpha": 0.75, "guide": 2}


def _faint_final_connectors(image: Image.Image, points: np.ndarray,
                            labels: np.ndarray, project, width: int) -> Image.Image:
    """Composite pen travel as a low-opacity gray dotted line *only* in payoff."""
    if not np.any(labels < 0):
        return image
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    _dotted_connectors(ImageDraw.Draw(overlay), points, labels, project,
                       (160, 165, 173, 46), width=max(1, round(width / 1080)))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _vibrant_transition(before: Image.Image, after: Image.Image,
                        progress: float) -> Image.Image:
    """Crossfade com zoom discreto e pulso dourado, sem tela branca agressiva."""
    p = float(np.clip(progress, 0.0, 1.0))
    smooth = p * p * (3.0 - 2.0 * p)
    blended = Image.blend(before, after, smooth)
    pulse = np.sin(np.pi * p)
    if pulse > 0:
        warm = Image.new("RGB", blended.size, "#ffce45")
        blended = Image.blend(blended, warm, float(0.20 * pulse))
        w, h = blended.size
        border = int(round(min(w, h) * 0.012 * pulse))
        if border > 0:
            blended = blended.crop((border, border, w-border, h-border)).resize(
                (w, h), Image.Resampling.BICUBIC)
    return blended


def _draw_formulas(draw, w: int, h: int) -> None:
    """The same correct X/Y Fourier formulas, reusable in both layouts."""
    draw.text((w*.5, h*.815), "x(t) = a0 + Σ Ak cos(2πkt + φk)",
              anchor="mm", font=_font(max(19, w // 37), True), fill="#16cde1")
    draw.text((w*.5, h*.855), "y(t) = b0 + Σ Bk cos(2πkt + ψk)",
              anchor="mm", font=_font(max(19, w // 37), True), fill="#8be25c")


def render_frame(analysis: Analysis, labels: np.ndarray, cfg: Settings,
                 frame: int, total: int, _override=None) -> Image.Image:
    """Render classic unchanged; viral shows active epicycles from frame zero."""
    w, h = cfg.width, cfg.height
    stages = visual_stages(analysis, cfg)
    mode, n, phase, stage = (stage_timing(frame, total, cfg, stages)
                             if _override is None else _override)
    if mode in ("transition_in", "transition_out"):
        if mode == "transition_in":
            before = render_frame(analysis, labels, cfg, frame, total,
                                  ("flash", analysis.n_terms, 1.0, -1))
            after = render_frame(analysis, labels, cfg, frame, total,
                                 ("stage", stages[0], 0.0, 0))
        else:
            before = render_frame(analysis, labels, cfg, frame, total,
                                  ("stage", stages[-1], 1.0, len(stages)-1))
            after = render_frame(analysis, labels, cfg, frame, total,
                                 ("final", analysis.n_terms, 1.0, len(stages)-1))
        return _vibrant_transition(before, after, phase)
    scale = _visual_scale(analysis, w, h, cfg, scene=mode)
    cx = w * (.50 if mode in ("flash", "final") else (.54 if cfg.preset == "viral" else .65))
    cy = h * (.44 if mode == "flash" else .405 if mode == "final" else (.39 if cfg.preset == "viral" else .415))
    # Mean subtraction is done before FFT. Visual bbox centering is a
    # separate translation: mean and bbox midpoint are not necessarily equal.
    bbox_min = np.min(analysis.original, axis=0)
    bbox_max = np.max(analysis.original, axis=0)
    bbox_mid_x, bbox_mid_y = (bbox_min + bbox_max) / 2.0

    def project(x, y):
        return (int(round(cx + (x - bbox_mid_x) * scale)),
                int(round(cy - (y - bbox_mid_y) * scale)))

    image = Image.new("RGB", (w, h), "#08090d")
    draw = ImageDraw.Draw(image)
    stroke = _stroke_style(labels, w)
    if cfg.preset == "viral":
        stroke["line"] = max(stroke["line"], round(w / 360))
        stroke["glow"] = max(stroke["glow"], round(w / 155))
        stroke["glow_alpha"] = max(stroke["glow_alpha"], 0.55)
        stroke["guide"] = max(stroke["guide"], 2)

    if mode in ("flash", "final"):
        glow = Image.new("RGB", (w, h), "#08090d")
        scene_points = analysis.original if mode == "flash" else analysis.reconstructed
        _paths(ImageDraw.Draw(glow), scene_points, labels, project,
               "#dca300", stroke["glow"])
        image = Image.blend(image, glow.filter(
            ImageFilter.GaussianBlur(stroke["blur"])), stroke["glow_alpha"])
        draw = ImageDraw.Draw(image)
        _paths(draw, scene_points, labels, project, "#ffdc45", stroke["line"])
        # The original intro and every pen cycle remain free of connectors.
        if mode == "final":
            image = _faint_final_connectors(image, scene_points, labels, project, w)
            draw = ImageDraw.Draw(image)
        if mode == "flash":
            _hook(draw, cfg, frame / cfg.fps)
            draw.text((w * .5, h * .73), "A matemática vai desenhar isso.",
                      anchor="mm", font=_font(max(19, w // 29), True),
                      fill="#fff1ae")
            return image
        error = analysis.error_percent
        n = analysis.n_terms
    else:
        current = reconstruct(analysis.coefficients_x,
                              analysis.coefficients_y, n, len(labels))
        error = float(analysis.error_history[n])
        guide_color = "#627487" if cfg.preset == "viral" else "#32343c"
        _paths(draw, analysis.original, labels, project, guide_color, stroke["guide"])
        stop = len(labels) if phase >= 1.0 else max(
            2, int(round(phase * (len(labels) - 1))) + 1)
        if stop == len(labels):
            _paths(draw, current, labels, project, "#ffd03b", stroke["line"])
        else:
            _draw_partial_paths(draw, current, labels, stop,
                                project, "#ffd03b", stroke["line"])

        x_value = axis_value(analysis.coefficients_x, n, phase)
        y_value = axis_value(analysis.coefficients_y, n, phase)
        px, py = project(x_value, y_value)

        # Epiciclos em espaço auxiliar com escala independente. Ambos
        # continuam usando exatamente o mesmo t da caneta.
        x_scale = _circle_scale(analysis, w, h, cfg, "x", n)
        y_scale = _circle_scale(analysis, w, h, cfg, "y", n)
        top = (w * .64 + x_scale * analysis.coefficients_x[0].real,
               h * (.20 if cfg.preset == "viral" else .14))
        left = (w * .20, cy - y_scale * analysis.coefficients_y[0].real)
        x_end = _epicycles(draw, analysis.coefficients_x, n, phase,
                           top, x_scale, "x", "#14bfd6")
        y_end = _epicycles(draw, analysis.coefficients_y, n, phase,
                           left, y_scale, "y", "#90cf4c")
        _dashed(draw, (x_end.real, x_end.imag), (px, py), "#176c78")
        _dashed(draw, (y_end.real, y_end.imag), (px, py), "#557c31")
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill="#fff1ae")

    draw.text((w*.5, h*.70), f"N = {n}", anchor="mm",
              font=_font(max(34, w // 17), True), fill="#ffcf2f")
    draw.text((w*.5, h*.75), f"Erro = {error:.5f}%", anchor="mm",
              font=_font(max(26, w // 25), True), fill="#f4f1e9")
    if mode == "final" or cfg.preset == "viral":
        _draw_formulas(draw, w, h)
    _hook(draw, cfg, frame / cfg.fps)
    draw.text((w*.5, h*.955), "FOURIER MOTION", anchor="mm",
              font=_font(max(18, w // 40)), fill="#8a8f9e")
    return image


def render_video(analysis: Analysis, path_ids: np.ndarray,
                 destination: str | Path, settings: Settings,
                 audio: str | Path | None = None) -> None:
    """Gera MP4 H.264 atomicamente e falha se FFmpeg falhar."""
    settings.validate()
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg não encontrado no PATH")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + ".partial.mp4")
    total = round(settings.duration * settings.fps)
    soundtrack = validate_audio(audio)
    cmd = ffmpeg_command(settings, temp, soundtrack)
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for i in range(total):
            process.stdin.write(render_frame(analysis, path_ids, settings, i, total).tobytes())
        process.stdin.close()
        error = process.stderr.read().decode(errors="replace") if process.stderr else ""
        if process.wait() != 0:
            raise RuntimeError("Falha no FFmpeg: " + error[-1500:])
        temp.replace(destination)
    except BaseException:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        temp.unlink(missing_ok=True)
        raise
