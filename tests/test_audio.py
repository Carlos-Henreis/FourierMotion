"""Tests for audio attachment, duration and AAC output."""
import shutil
import subprocess
import wave

import pytest

from fourier_motion.audio import ffmpeg_command, validate_audio
from fourier_motion.config import Settings


def test_audio_validation(tmp_path):
    with pytest.raises(ValueError, match="não encontrado"):
        validate_audio(tmp_path / "missing.mp3")
    midi = tmp_path / "song.mid"
    midi.write_bytes(b"not audio")
    with pytest.raises(ValueError, match="MIDI"):
        validate_audio(midi)
    wav = tmp_path / "sound.wav"
    wav.write_bytes(b"data")
    assert validate_audio(wav) == wav.resolve()
    assert validate_audio(None) is None


def test_command_keeps_video_length_and_maps_soundtrack(tmp_path):
    cfg = Settings()
    sound = tmp_path / "song.wav"
    output = tmp_path / "result.mp4"
    command = ffmpeg_command(cfg, output, sound)
    assert ["-map", "0:v:0", "-map", "1:a:0"] == command[
        command.index("-map"):command.index("-map") + 4
    ]
    assert command[command.index("-t") + 1] == "60.0"
    assert command[command.index("-af") + 1].startswith("apad,atrim=duration=60.0")
    assert command[-1] == str(output)
    assert "-an" not in command
    assert "-an" in ffmpeg_command(cfg, output, None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="FFmpeg is not installed")
def test_ffmpeg_mux_smoke(tmp_path):
    cfg = Settings(width=320, height=480, fps=10, duration=1.0,
                   final_seconds=0.2, flash_seconds=0.1)
    wav = tmp_path / "tone.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\\x00\\x00" * 8000)
    dest = tmp_path / "out.mp4"
    process = subprocess.Popen(
        ffmpeg_command(cfg, dest, wav),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    frames = b"\\x00" * (cfg.width * cfg.height * 3)
    _, errors = process.communicate(input=frames * cfg.fps, timeout=30)
    assert process.returncode == 0, errors.decode(errors="replace")
    assert dest.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
         "-of", "default=noprint_wrappers=1:nokey=1", str(dest)],
        capture_output=True, text=True, check=True,
    )
    assert "h264" in probe.stdout
    assert "aac" in probe.stdout
