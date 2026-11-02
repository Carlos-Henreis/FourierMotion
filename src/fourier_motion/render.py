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
    """7s de abertura, uma volta completa por N e resultado final sem pausas.

    Não diluímos frames excedentes nos estágios. Assim que t chega a 1,
    a próxima etapa começa imediatamente. O tempo restante do vídeo
    pertence à tela de resultado, sem fingir que N<=200 convergiu.
    """
    opening = round(cfg.flash_seconds * cfg.fps)
    cycle_frames = max(2, round(cfg.cycle_seconds * cfg.fps))
    final_minimum = round(cfg.final_seconds * cfg.fps)
    required = opening + len(stages) * cycle_frames + final_minimum
    if required > total:
        raise ValueError(
            f"Duração insuficiente: {required / cfg.fps:.2f}s necessários "
            f"para abertura, {len(stages)} ciclos e encerramento."
        )
    if frame < opening:
        return ("flash", stages[-1], 1.0, -1)
    step_frame = frame - opening
    stage_index = step_frame // cycle_frames
    if stage_index < len(stages):
        local_frame = step_frame % cycle_frames
        phase = local_frame / (cycle_frames - 1)
        return ("stage", stages[stage_index], phase, stage_index)
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
    if scene in ("flash", "final"):
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
    """Abertura central de 7s, ciclos imediatos e resultado grande central."""
    w, h = cfg.width, cfg.height
    stages = visual_stages(analysis, cfg)
    mode, n, phase, stage = stage_timing(frame, total, cfg, stages)
    scale = _visual_scale(analysis, w, h, cfg, scene=mode)
    cx = w * (.50 if mode in ("flash", "final") else .65)
    cy = h * (.405 if mode in ("flash", "final") else .415)

    def project(x, y):
        return (int(round(cx + x * scale)), int(round(cy - y * scale)))

    image = Image.new("RGB", (w, h), "#08090d")
    draw = ImageDraw.Draw(image)

    if mode in ("flash", "final"):
        glow = Image.new("RGB", (w, h), "#08090d")
        _paths(ImageDraw.Draw(glow), analysis.reconstructed,
               labels, project, "#dca300", max(12, w // 75))
        image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(max(9, w // 75))), .75)
        draw = ImageDraw.Draw(image)
        _paths(draw, analysis.reconstructed, labels, project, "#ffdc45", max(4, w // 210))
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
        _paths(draw, analysis.original, labels, project, "#32343c", 2)
        stop = len(labels) if phase >= 1.0 else max(
            2, int(round(phase * (len(labels) - 1))) + 1)
        if stop == len(labels):
            _paths(draw, current, labels, project, "#ffd03b", max(4, w // 210))
        else:
            _draw_partial_paths(draw, current, labels, stop,
                                project, "#ffd03b", max(4, w // 210))

        x_value = axis_value(analysis.coefficients_x, n, phase)
        y_value = axis_value(analysis.coefficients_y, n, phase)
        px, py = project(x_value, y_value)

        # Epiciclos em espaço auxiliar com escala independente. Ambos
        # continuam usando exatamente o mesmo t da caneta.
        x_scale = _circle_scale(analysis, w, h, cfg, "x", n)
        y_scale = _circle_scale(analysis, w, h, cfg, "y", n)
        top = (w * .64 + x_scale * analysis.coefficients_x[0].real, h * .14)
        left = (w * .20, cy - y_scale * analysis.coefficients_y[0].real)
        x_end = _epicycles(draw, analysis.coefficients_x, n, phase,
                           top, x_scale, "x", "#14bfd6")
        y_end = _epicycles(draw, analysis.coefficients_y, n, phase,
                           left, y_scale, "y", "#90cf4c")
        _dashed(draw, (x_end.real, x_end.imag), (px, py), "#176c78")
        _dashed(draw, (y_end.real, y_end.imag), (px, py), "#557c31")
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill="#fff1ae")
        draw.text((w*.5, h*.645),
                  f"ETAPA {stage + 1}/{len(stages)}  -  1 volta por N",
                  anchor="mm", font=_font(max(18, w // 39)), fill="#989ca8")

    draw.text((w*.5, h*.70), f"N = {n}", anchor="mm",
              font=_font(max(34, w // 17), True), fill="#ffcf2f")
    draw.text((w*.5, h*.75), f"Erro = {error:.5f}%", anchor="mm",
              font=_font(max(26, w // 25), True), fill="#f4f1e9")
    if mode == "final":
        draw.text((w*.5, h*.815), "x(t) = a0 + Σ Ak cos(2πkt + φk)",
                  anchor="mm", font=_font(max(19, w // 37), True), fill="#16cde1")
        draw.text((w*.5, h*.855), "y(t) = b0 + Σ Bk cos(2πkt + ψk)",
                  anchor="mm", font=_font(max(19, w // 37), True), fill="#8be25c")
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
