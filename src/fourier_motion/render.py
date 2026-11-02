"""Renderização Pillow transmitida diretamente para FFmpeg, sem PNGs intermediários."""
from pathlib import Path
import shutil
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .config import Settings
from .fourier import Analysis, reconstruct


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
        segment = points[labels == label]
        if len(segment) >= 2:
            xy = [project(*point) for point in segment]
            draw.line(xy, fill=color, width=width, joint="curve")
            draw.line((xy[-1], xy[0]), fill=color, width=width)


def visual_stages(analysis: Analysis, cfg: Settings) -> tuple[int, ...]:
    """Marcos fixos da animação; a convergência matemática continua independente."""
    limit = min(analysis.n_terms, cfg.visual_max_terms)
    stages = sorted(set([1, limit] + [n for n in cfg.stage_terms if 1 <= n <= limit]))
    return tuple(stages)


def stage_timing(frame: int, total: int, cfg: Settings, stages: tuple[int, ...]):
    """Retorna ('flash'|'stage'|'final', N, fase, índice).

    Cada etapa percorre t=0..1 em cycle_seconds; frames restantes são
    distribuídos como pausa entre os ciclos. Nenhuma etapa é cortada.
    """
    flash = round(cfg.flash_seconds * cfg.fps)
    end = total - round(cfg.final_seconds * cfg.fps)
    if frame < flash:
        return ("flash", stages[-1], 1.0, -1)
    if frame >= end:
        return ("final", stages[-1], 1.0, len(stages) - 1)
    available = end - flash
    cycle_frames = max(2, round(cfg.cycle_seconds * cfg.fps))
    required = len(stages) * cycle_frames
    if available < required:
        raise ValueError(
            f"Duração insuficiente para {len(stages)} etapas de "
            f"{cfg.cycle_seconds}s; aumente --duration ou reduza --stage-terms"
        )
    extra = available - required
    position = frame - flash
    for i, n in enumerate(stages):
        hold = (i + 1) * extra // len(stages) - i * extra // len(stages)
        span = cycle_frames + hold
        if position < span:
            phase = min(1.0, position / (cycle_frames - 1))
            return ("stage", n, phase, i)
        position -= span
    raise RuntimeError("Falha no escalonamento da animação")


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


def _visual_scale(analysis: Analysis, w: int, h: int, cfg: Settings) -> float:
    """Bounding box do sinal centralizado, em 68% da região útil de desenho.

    Uma restrição adicional limita a soma dos raios de círculos destacados
    para impedir que as cadeias X e Y saiam do enquadramento.
    """
    width, height = np.ptp(analysis.original, axis=0)
    drawing_region_w = w * .49
    drawing_region_h = h * .46
    base = min(cfg.target_fill_ratio * drawing_region_w / max(width, 1e-9),
               cfg.target_fill_ratio * drawing_region_h / max(height, 1e-9))
    def radius_budget(coeff):
        k = _highlight_indices(coeff, min(cfg.visual_max_terms, analysis.n_terms))
        return float(sum((1 if idx == len(coeff) - 1 else 2) * abs(coeff[idx]) for idx in k))
    x_budget = radius_budget(analysis.coefficients_x)
    y_budget = radius_budget(analysis.coefficients_y)
    return min(base,
               h * .145 / max(2 * x_budget, 1e-9),
               w * .17 / max(2 * y_budget, 1e-9))


def _hook(draw, cfg: Settings, elapsed: float):
    if not cfg.hook_text or elapsed >= 3.0:
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
        sub = points[:stop][labels[:stop] == label]
        if len(sub) > 1:
            draw.line([project(*p) for p in sub], fill=color, width=width, joint="curve")


def render_frame(analysis: Analysis, labels: np.ndarray, cfg: Settings,
                 frame: int, total: int) -> Image.Image:
    """Flash antecipatório, etapas completas de 3.5s e equação final."""
    w, h = cfg.width, cfg.height
    stages = visual_stages(analysis, cfg)
    mode, n, phase, stage = stage_timing(frame, total, cfg, stages)
    cx, cy = w * .70, h * .425
    scale = _visual_scale(analysis, w, h, cfg)

    def project(x, y):
        return (int(round(cx + x * scale)), int(round(cy - y * scale)))

    image = Image.new("RGB", (w, h), "#08090d")
    draw = ImageDraw.Draw(image)
    if mode in ("flash", "final"):
        glow = Image.new("RGB", (w, h), "#08090d")
        _paths(ImageDraw.Draw(glow), analysis.reconstructed,
               labels, project, "#dca300", 11)
        image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(14)), .75)
        draw = ImageDraw.Draw(image)
        _paths(draw, analysis.reconstructed, labels, project, "#ffdc45", 4)

        if mode == "flash":
            _hook(draw, cfg, frame / cfg.fps)
            draw.text((w * .5, h * .73), "A matemática vai desenhar isso.",
                      anchor="mm", font=_font(max(19, w // 29), True),
                      fill="#fff1ae")
            # Últimos instantes do flash escurecem antes do início do N=1.
            length = max(1, round(cfg.flash_seconds * cfg.fps))
            if length > 2 and frame >= max(0, length - 3):
                image = Image.blend(image, Image.new("RGB", (w, h), "#08090d"),
                                    (frame - (length - 3) + 1) / 3)
            return image
        error = analysis.error_percent
        n = analysis.n_terms
    else:
        current = reconstruct(analysis.coefficients_x,
                              analysis.coefficients_y, n, len(labels))
        error = float(analysis.error_history[n])
        _paths(draw, analysis.original, labels, project, "#32343c", 2)
        # Progresso geométrico acompanha a MESMA fase t dos epiciclos.
        stop = len(labels) if phase >= 1.0 else max(
            2, int(round(phase * (len(labels) - 1))) + 1)
        if stop == len(labels):
            _paths(draw, current, labels, project, "#ffd03b", 4)
        else:
            _draw_partial_paths(draw, current, labels, stop,
                                project, "#ffd03b", 4)

        x_value = axis_value(analysis.coefficients_x, n, phase)
        y_value = axis_value(analysis.coefficients_y, n, phase)
        px, py = project(x_value, y_value)
        top = (cx + scale * analysis.coefficients_x[0].real, h * .19)
        left = (w * .19, cy - scale * analysis.coefficients_y[0].real)
        x_end = _epicycles(draw, analysis.coefficients_x, n, phase,
                           top, scale, "x", "#14bfd6")
        y_end = _epicycles(draw, analysis.coefficients_y, n, phase,
                           left, scale, "y", "#90cf4c")
        _dashed(draw, (x_end.real, x_end.imag), (px, py), "#176c78")
        _dashed(draw, (y_end.real, y_end.imag), (px, py), "#557c31")
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill="#fff1ae")
        draw.text((w*.5, h*.645),
                  f"ETAPA {stage + 1}/{len(stages)}  -  1 volta completa por N",
                  anchor="mm", font=_font(max(18, w // 39)), fill="#989ca8")

    draw.text((w*.5, h*.70), f"N = {n}", anchor="mm",
              font=_font(max(34, w // 17), True), fill="#ffcf2f")
    draw.text((w*.5, h*.75), f"error = {error:.5f}%", anchor="mm",
              font=_font(max(26, w // 25), True), fill="#f4f1e9")
    if mode == "final":
        draw.text((w*.5, h*.815), "x(t) = a0 + Σ Ak cos(2πkt + φk)",
                  anchor="mm", font=_font(max(19, w // 37), True), fill="#16cde1")
        draw.text((w*.5, h*.855), "y(t) = b0 + Σ Bk cos(2πkt + ψk)",
                  anchor="mm", font=_font(max(19, w // 37), True), fill="#8be25c")
        note = (f"Animação: N <= {cfg.visual_max_terms}  |  "
                f"solução precisa: N={analysis.n_terms}")
        draw.text((w*.5, h*.90), note, anchor="mm",
                  font=_font(max(16, w // 43)), fill="#b9b9c1")
    _hook(draw, cfg, frame / cfg.fps)
    draw.text((w*.5, h*.955), "FOURIER MOTION", anchor="mm",
              font=_font(max(18, w // 40)), fill="#8a8f9e")
    return image


def render_video(analysis: Analysis, path_ids: np.ndarray,
                 destination: str | Path, settings: Settings) -> None:
    """Gera MP4 H.264 atomicamente e falha se FFmpeg falhar."""
    settings.validate()
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg não encontrado no PATH")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + ".partial.mp4")
    total = round(settings.duration * settings.fps)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
           "-pixel_format", "rgb24", "-video_size", f"{settings.width}x{settings.height}",
           "-framerate", str(settings.fps), "-i", "-", "-an", "-c:v", "libx264",
           "-preset", settings.speed, "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-t", str(settings.duration), str(temp)]
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
