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


def _circles(draw, coefficients, n, t, origin, scale, axis, color):
    pos = complex(*origin)
    projected = float(coefficients[0].real)
    for k in range(1, n + 1):
        factor = 1 if k == len(coefficients) - 1 else 2
        component = factor * coefficients[k] * np.exp(2j * np.pi * k * t)
        projected += component.real
        delta = scale * component * (1j if axis == "y" else 1)
        new_pos = pos + delta
        radius = scale * factor * abs(coefficients[k])
        if radius >= 1.3 and k <= 180:
            x, y = pos.real, pos.imag
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=color)
            draw.line((x, y, new_pos.real, new_pos.imag), fill=color, width=1)
        pos = new_pos
    return projected


def render_frame(analysis: Analysis, labels: np.ndarray, cfg: Settings,
                 frame: int, total: int) -> Image.Image:
    w, h = cfg.width, cfg.height
    last_start = max(1, total - round(cfg.final_seconds * cfg.fps))
    final = frame >= last_start
    progress = min(1.0, frame / max(1, last_start - 1))
    n = analysis.n_terms if final else max(1, min(analysis.n_terms,
                        round(1 + (analysis.n_terms - 1) * progress**1.5)))
    error = analysis.error_percent if final else float(analysis.error_history[n])
    phase = (frame / cfg.fps * .2) % 1.0
    current = analysis.reconstructed if final else reconstruct(
        analysis.coefficients_x, analysis.coefficients_y, n, len(labels))
    im = Image.new("RGB", (w, h), "#08090d")
    draw = ImageDraw.Draw(im)
    cx, cy = w * .52, h * .40
    size = np.ptp(analysis.original, axis=0)
    scale = min(w * .68 / max(1, size[0]), h * .37 / max(1, size[1]))
    def project(x, y):
        return (int(cx + x * scale), int(cy - y * scale))

    if final:
        glow = Image.new("RGB", (w, h), "#08090d")
        _paths(ImageDraw.Draw(glow), current, labels, project, "#c69800", 11)
        im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(14)), .72)
        draw = ImageDraw.Draw(im)
        _paths(draw, current, labels, project, "#ffdc45", 4)
    else:
        _paths(draw, analysis.original, labels, project, "#30323a", 2)
        stop = min(len(labels), max(2, round(phase * (len(labels) - 1))))
        for label in np.unique(labels[:stop]):
            path = current[:stop][labels[:stop] == label]
            if len(path) > 1:
                draw.line([project(*v) for v in path], fill="#ffcf2f", width=4)
        px, py = project(*current[stop - 1])
        draw.ellipse((px-5, py-5, px+5, py+5), fill="#fff1ae")
        top = (cx, h * .14)
        left = (w * .16, cy)
        xval = _circles(draw, analysis.coefficients_x, n, phase, top, scale, "x", "#14bfd6")
        yval = _circles(draw, analysis.coefficients_y, n, phase, left, scale, "y", "#90cf4c")
        gx, gy = project(xval, yval)
        draw.line((gx, top[1], gx, gy), fill="#176c78", width=2)
        draw.line((left[0], gy, gx, gy), fill="#557c31", width=2)
    draw.text((w*.5, h*.70), f"N = {n}", anchor="mm", font=_font(64, True), fill="#ffcf2f")
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
