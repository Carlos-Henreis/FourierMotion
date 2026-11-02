"""FFmpeg command builder for an optional original or licensed soundtrack."""
from pathlib import Path

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
    """Encode 60 seconds of RGB video, optionally muxing an audio file.

    apad fills a too-short soundtrack; atrim trims longer audio. Audio starts
    exactly at video t=0, without changing video frames, harmonic staging,
    or the 53-second visual payoff.
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
            "-af", f"apad,atrim=duration={settings.duration},asetpts=N/SR/TB",
        ])
    cmd.extend([
        "-movflags", "+faststart", "-t", str(settings.duration), str(output),
    ])
    return cmd
