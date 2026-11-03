"""Interface da aplicação: imagem -> análise -> JSON -> MP4."""
import argparse
import json
from pathlib import Path
import numpy as np
from .config import Settings
from .contours import extract_contours
from .continuous import make_continuous
from .fourier import analyze
from .render import render_video
from .audio import choose_audio


def save_coefficients(path: Path, result, continuous_path: bool = False) -> None:
    def terms(coeff):
        return [
            {"k": k, "real": float(v.real), "imag": float(v.imag),
             "amplitude": float((1 if k in (0, len(coeff)-1) else 2) * abs(v)),
             "phase_radians": float(np.angle(v))}
            for k, v in enumerate(coeff[:result.n_terms + 1])
        ]
    data = {
        "harmonics": result.n_terms,
        "continuous_path": continuous_path,
        "error_percent": result.error_percent,
        "error_definition": "100 * RMS(Euclidean distance) / original bounding-box diagonal",
        "samples": len(result.original), "scale": result.scale,
        "x": terms(result.coefficients_x), "y": terms(result.coefficients_y),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_stage_terms(text: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part.strip()) for part in text.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use inteiros separados por vírgula") from exc
    if not values or any(n < 1 for n in values):
        raise argparse.ArgumentTypeError("Estágios devem ser inteiros positivos")
    return values


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FourierMotion: contornos para Reels")
    p.add_argument("image", type=Path)
    p.add_argument("--preset", choices=("classic", "viral"), default="classic",
                   help="classic: 60s, viral: 20s com revelação aos 16s")
    p.add_argument("--output", type=Path, default=Path("output/reel.mp4"))
    p.add_argument("--samples", type=int, default=2048)
    p.add_argument("--error", type=float, default=0.05)
    p.add_argument("--max-terms", type=int)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--final-seconds", type=float, default=None)
    p.add_argument("--min-contour-length", type=float, default=25.0)
    p.add_argument("--speed", default="medium")
    p.add_argument("--hook-text", default="", help="Gancho textual nos primeiros 3 segundos")
    p.add_argument("--flash-seconds", type=float, default=None)
    p.add_argument("--transition-seconds", type=float, default=None)
    p.add_argument("--cycle-seconds", type=float, default=None)
    p.add_argument("--target-fill-ratio", type=float, default=0.68)
    p.add_argument("--visual-max-terms", type=int, default=200,
                   help="Máximo visual; a precisão final continua usando N*")
    p.add_argument("--stage-terms", type=parse_stage_terms,
                   default=(1, 2, 5, 15, 40, 100, 150, 200))
    p.add_argument("--continuous-path", action="store_true",
                   help="Trajetória única com conexões pontilhadas entre contornos")
    p.add_argument("--audio", type=Path, help="Trilha WAV/MP3/M4A específica")
    p.add_argument("--audio-dir", type=Path,
                   help="Escolhe aleatoriamente um áudio da pasta a cada vídeo")
    p.add_argument("--audio-seed", type=int,
                   help="Semente opcional para repetir a mesma escolha")
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args(argv)
    viral = args.preset == "viral"
    cfg = Settings(preset=args.preset, samples=args.samples,
                   threshold_percent=args.error, fps=args.fps,
                   duration=args.duration if args.duration is not None else (20.0 if viral else 60.0),
                   width=args.width, height=args.height,
                   final_seconds=args.final_seconds if args.final_seconds is not None else (4.0 if viral else 7.0),
                   max_terms=args.max_terms,
                   min_contour_length=args.min_contour_length, speed=args.speed,
                   hook_text=args.hook_text,
                   flash_seconds=args.flash_seconds if args.flash_seconds is not None else (0.5 if viral else 7.0),
                   transition_seconds=args.transition_seconds if args.transition_seconds is not None else (0.2 if viral else 0.4),
                   cycle_seconds=args.cycle_seconds if args.cycle_seconds is not None else 3.5,
                   target_fill_ratio=args.target_fill_ratio,
                   visual_max_terms=args.visual_max_terms,
                   stage_terms=args.stage_terms)
    cfg.validate()
    soundtrack = choose_audio(args.audio, args.audio_dir, args.audio_seed,
                              preset=args.preset)
    if soundtrack is not None and not args.analyze_only:
        print(f"Trilha selecionada: {soundtrack.name}", flush=True)
    contours = extract_contours(args.image, cfg.samples, cfg.min_contour_length,
                                cfg.max_contours)
    if args.continuous_path:
        contours = make_continuous(contours)
    result = analyze(contours.points, cfg.threshold_percent, cfg.max_terms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_coefficients(args.output.with_suffix(".fourier.json"), result,
                      continuous_path=args.continuous_path)
    print(f"Contornos={contours.count}; continuo={args.continuous_path}; amostras={cfg.samples}; "
          f"N={result.n_terms}; erro={result.error_percent:.8f}%")
    if not args.analyze_only:
        render_video(result, contours.path_ids, args.output, cfg, audio=soundtrack)
        print(f"Vídeo: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
