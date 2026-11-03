"""FFmpeg command builder for an optional original or licensed soundtrack."""
from pathlib import Path
import random

SUPPORTED_AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def validate_audio(audio: str | Path | None) -> Path | None:
    if audio is None:
        return None
    path = Path(audio).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Arquivo de áudio não encontrado: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO:
        raise ValueError(
            "Use um arquivo de áudio WAV, MP3, M4A, AAC, FLAC ou OGG. "
            "Arquivos MIDI devem primeiro ser exportados como áudio."
        )
    return path


def ffmpeg_command(settings, output: Path, audio: Path | None = None) -> list[str]:
    """Encode RGB video, optionally muxing an audio file.

    apad fills a too-short soundtrack; atrim trims longer audio. Audio starts
    exactly at video t=0. Viral audio has its climax at t=16, classic at t=53.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{settings.width}x{settings.height}",
        "-framerate", str(settings.fps), "-i", "-",
    ]
    if audio is not None:
        cmd.extend(["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend(["-map", "0:v:0"])
    cmd.extend([
        "-c:v", "libx264", "-preset", settings.speed, "-crf", "20",
        "-pix_fmt", "yuv420p",
    ])
    if audio is None:
        cmd.append("-an")
    else:
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k",
            "-af", (f"apad,atrim=duration={settings.duration},asetpts=N/SR/TB,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11"),
        ])
    cmd.extend([
        "-movflags", "+faststart", "-t", str(settings.duration), str(output),
    ])
    return cmd


def choose_audio(
    audio: str | Path | None = None,
    audio_dir: str | Path | None = None,
    audio_seed: int | None = None,
    preset: str = "classic",
) -> Path | None:
    """Choose one track uniformly from a local folder, with optional seeded RNG.

    The selection is performed once per run, before frame rendering. The chosen
    track is reported by the CLI, allowing the video to be reproduced.
    """
    if audio is not None and audio_dir is not None:
        raise ValueError("Use --audio OU --audio-dir, nunca ambos")
    if audio_dir is None:
        return validate_audio(audio)
    folder = Path(audio_dir).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Pasta de trilhas não encontrada: {folder}")
    # The repo ships 20-second compositions under soundtracks/viral.
    # Classic keeps its previous flat-directory behavior, unchanged.
    if preset == "viral" and (folder / "viral").is_dir():
        folder = folder / "viral"
    tracks = sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO
    )
    if not tracks:
        raise ValueError(f"Nenhuma trilha de áudio compatível encontrada em: {folder}")
    selected = random.Random(audio_seed).choice(tracks)
    return validate_audio(selected)
