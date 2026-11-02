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


def sample_harmonics(max_n: int, available_frames: int, min_frames: int = 24) -> list[int]:
    """Amostra ordens de Fourier sem ultrapassar a duração da animação.

    Cada N selecionado recebe pelo menos min_frames para uma volta completa.
    A sequência geométrica dá mais atenção visual aos primeiros harmônicos.
    """
    if max_n < 1 or available_frames < 1:
        raise ValueError("Valores inválidos para amostragem de N")
    count = min(max_n, max(1, available_frames // min_frames), 48)
    values = np.geomspace(1, max_n, count)
    chosen = sorted(set(int(round(v)) for v in values) | {1, max_n})
    return chosen


def stage_state(frame: int, available_frames: int, harmonics: list[int]):
    """Retorna N, progresso de ciclo e índice de etapa para um quadro."""
    index = min(len(harmonics) - 1, frame * len(harmonics) // available_frames)
    start = index * available_frames // len(harmonics)
    end = (index + 1) * available_frames // len(harmonics)
    cycle = (frame - start) / max(1, end - start - 1)
    return harmonics[index], min(1.0, cycle), index


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


def _visual_scale(analysis: Analysis, w: int, h: int) -> float:
    """Mantém desenho à direita e as duas cadeias de círculos no quadro."""
    size = np.ptp(analysis.original, axis=0)
    base = min(w * .43 / max(1, size[0]), h * .36 / max(1, size[1]))
    def budget(coeff):
        k = _highlight_indices(coeff, analysis.n_terms)
        return float(sum((1 if idx == len(coeff) - 1 else 2) * abs(coeff[idx])
                         for idx in k))
    x_total = budget(analysis.coefficients_x)
    y_total = budget(analysis.coefficients_y)
    # 2 * soma dos raios limita qualquer posição de centro e borda de círculo.
    return min(base, h * .135 / max(1e-9, 2 * x_total),
               w * .165 / max(1e-9, 2 * y_total))


def _draw_partial_paths(draw, points, labels, stop, project, color, width):
    """Rastro parcial sem unir caminhos independentes."""
    for label in np.unique(labels[:stop]):
        sub = points[:stop][labels[:stop] == label]
        if len(sub) > 1:
            draw.line([project(*p) for p in sub], fill=color, width=width, joint="curve")


def render_frame(analysis: Analysis, labels: np.ndarray, cfg: Settings,
                 frame: int, total: int) -> Image.Image:
    w, h = cfg.width, cfg.height
    last_start = max(1, total - round(cfg.final_seconds * cfg.fps))
    final = frame >= last_start
    harmonics = sample_harmonics(analysis.n_terms, last_start)
    if final:
        n, cycle, stage = analysis.n_terms, 1.0, len(harmonics) - 1
    else:
        n, cycle, stage = stage_state(frame, last_start, harmonics)

    error = float(analysis.error_history[n])
    current = analysis.reconstructed if n == analysis.n_terms else reconstruct(
        analysis.coefficients_x, analysis.coefficients_y, n, len(labels))
    im = Image.new("RGB", (w, h), "#08090d")
    draw = ImageDraw.Draw(im)

    # Movimento da imagem para a direita libera a zona dos epiciclos verdes.
    cx, cy = w * .70, h * .42
    scale = _visual_scale(analysis, w, h)

    def project(x, y):
        return (int(round(cx + x * scale)), int(round(cy - y * scale)))

    if final:
        glow = Image.new("RGB", (w, h), "#08090d")
        _paths(ImageDraw.Draw(glow), current, labels, project, "#c69800", 11)
        im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(14)), .72)
        draw = ImageDraw.Draw(im)
        _paths(draw, current, labels, project, "#ffdc45", 4)
    else:
        _paths(draw, analysis.original, labels, project, "#30323a", 2)
        # Cada N desenha TODO o contorno. O quadro final do estágio segura
        # a forma fechada antes do próximo N começar.
        stop = len(labels) if cycle >= .92 else max(2, min(
            len(labels), int(cycle / .92 * len(labels))))
        if stop == len(labels):
            _paths(draw, current, labels, project, "#ffcf2f", 4)
        else:
            _draw_partial_paths(draw, current, labels, stop, project, "#ffcf2f", 4)

        # Mesmo parâmetro t para: x, y, cursor do desenho e ambas as cadeias.
        t = min(cycle / .92, 1.0) if cycle < .92 else 1.0
        x_value = axis_value(analysis.coefficients_x, n, t)
        y_value = axis_value(analysis.coefficients_y, n, t)
        px, py = project(x_value, y_value)

        top = (cx + scale * analysis.coefficients_x[0].real, h * .17)
        left = (w * .22, cy - scale * analysis.coefficients_y[0].real)
        x_end = _epicycles(draw, analysis.coefficients_x, n, t, top,
                           scale, "x", "#14bfd6")
        y_end = _epicycles(draw, analysis.coefficients_y, n, t, left,
                           scale, "y", "#90cf4c")
        # x_end.real = px; y_end.imag = py (dentro da precisão numérica).
        _dashed(draw, (x_end.real, x_end.imag), (px, py), "#176c78")
        _dashed(draw, (y_end.real, y_end.imag), (px, py), "#557c31")
        draw.ellipse((px-5, py-5, px+5, py+5), fill="#fff1ae")
        draw.text((w*.5, h*.645),
                  f"PASSO {stage + 1}/{len(harmonics)}  ·  ciclo completo por N",
                  anchor="mm", font=_font(25), fill="#989ca8")

    draw.text((w*.5, h*.70), f"N = {n}", anchor="mm",
              font=_font(64, True), fill="#ffcf2f")
    draw.text((w*.5, h*.75), f"error = {error:.5f}%", anchor="mm",
              font=_font(43, True), fill="#f4f1e9")
    if final:
        draw.text((w*.5, h*.815), "x(t) = a0 + Σ Ak cos(2πkt + φk)",
                  anchor="mm", font=_font(30, True), fill="#16cde1")
        draw.text((w*.5, h*.855), "y(t) = b0 + Σ Bk cos(2πkt + ψk)",
                  anchor="mm", font=_font(30, True), fill="#8be25c")
        draw.text((w*.5, h*.90), f"k = 1 ... N  |  error < {cfg.threshold_percent}%",
                  anchor="mm", font=_font(27), fill="#b9b9c1")
    draw.text((w*.5, h*.955), "FOURIER MOTION", anchor="mm",
              font=_font(27), fill="#8a8f9e")
    return im


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
