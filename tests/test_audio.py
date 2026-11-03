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


def test_random_audio_directory_and_reproducibility(tmp_path):
    from fourier_motion.audio import choose_audio

    for name in ("01_ambient.mp3", "02_synthwave.mp3", "03_lofi.mp3",
                 "04_cinematic.mp3", "05_chiptune.mp3"):
        (tmp_path / name).write_bytes(b"audio-placeholder")
    (tmp_path / "README.txt").write_text("ignore")
    first = choose_audio(audio_dir=tmp_path, audio_seed=2026)
    second = choose_audio(audio_dir=tmp_path, audio_seed=2026)
    assert first == second
    assert first.suffix == ".mp3"
    observed = {choose_audio(audio_dir=tmp_path, audio_seed=i).name for i in range(60)}
    assert len(observed) == 5


def test_audio_choice_rejects_conflicting_and_missing_inputs(tmp_path):
    from fourier_motion.audio import choose_audio

    song = tmp_path / "one.mp3"
    song.write_bytes(b"audio-placeholder")
    assert choose_audio(audio=song) == song.resolve()
    with pytest.raises(ValueError, match="OU"):
        choose_audio(audio=song, audio_dir=tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="Nenhuma trilha"):
        choose_audio(audio_dir=empty)


def test_viral_audio_selects_only_20_second_tracks(tmp_path):
    from fourier_motion.audio import choose_audio

    (tmp_path / "old_60s.mp3").write_bytes(b"old")
    viral = tmp_path / "viral"
    viral.mkdir()
    names = ["01_ambient_20s.wav", "02_synthwave_20s.wav",
             "03_lofi_20s.wav", "04_orchestral_20s.wav",
             "05_chiptune_20s.wav"]
    for name in names:
        (viral / name).write_bytes(b"new")
    picks = {choose_audio(audio_dir=tmp_path, audio_seed=i, preset="viral").name
             for i in range(80)}
    assert picks == set(names)
    assert choose_audio(audio_dir=tmp_path, preset="classic").name == "old_60s.mp3"


def test_bundled_viral_soundtracks_are_five_distinct_20s_wavs():
    from pathlib import Path
    import hashlib

    base = Path(__file__).resolve().parents[1] / "soundtracks" / "viral"
    songs = sorted(base.glob("*.wav"))
    assert len(songs) == 5
    checksums = []
    for song in songs:
        with wave.open(str(song), "rb") as music:
            assert music.getnchannels() == 1
            assert music.getsampwidth() == 2
            assert music.getframerate() == 16000
            assert music.getnframes() == 20 * 16000
        checksums.append(hashlib.sha256(song.read_bytes()).hexdigest())
    assert len(set(checksums)) == 5


def test_classic_playlist_prefers_five_new_genres(tmp_path):
    from fourier_motion.audio import choose_audio

    (tmp_path / "old_60s.mp3").write_bytes(b"old")
    target = tmp_path / "classic"
    target.mkdir()
    names = ("rock", "anime", "forro", "sertanejo", "hiphop")
    for genre in names:
        (target / f"FourierMotion_{genre}_60s.wav").write_bytes(b"test")
    picked = {choose_audio(audio_dir=tmp_path, preset="classic", audio_seed=i).name
              for i in range(100)}
    assert picked == {f"FourierMotion_{genre}_60s.wav" for genre in names}
    assert choose_audio(audio_dir=tmp_path, preset="classic", audio_seed=42) == (
        choose_audio(audio_dir=tmp_path, preset="classic", audio_seed=42)
    )
    # Explicit selection must override playlist discovery.
    assert choose_audio(audio=tmp_path / "old_60s.mp3", preset="classic").name == (
        "old_60s.mp3"
    )


def test_bundled_classic_soundtracks_are_distinct_audible_sixty_second_wavs():
    import hashlib
    from array import array
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "soundtracks" / "classic"
    tracks = sorted(root.glob("*.wav"))
    assert len(tracks) == 5
    assert {p.stem.split("_")[2] for p in tracks} == {
        "rock", "anime", "forro", "sertanejo", "hiphop"
    }
    digests = set()
    for path in tracks:
        with wave.open(str(path), "rb") as source:
            assert source.getnchannels() == 1
            assert source.getsampwidth() == 2
            assert source.getframerate() == 16000
            assert source.getnframes() == 60 * 16000
            samples = source.readframes(source.getnframes())
            data = array('h')
            data.frombytes(samples)
            peak = max(abs(v) for v in data)
            rms = (sum(v * v for v in data) / len(data)) ** 0.5
            assert rms > 900
            assert peak > 2500
        digests.add(hashlib.sha256(samples).hexdigest())
    assert len(digests) == 5
