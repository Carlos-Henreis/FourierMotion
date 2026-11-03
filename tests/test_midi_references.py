"""Validate checked-in original MIDI sources before audio CI consumes them."""
from pathlib import Path
import base64
import zlib

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "soundtracks" / "references"
NAMES = ("ambient", "synthwave", "lofi", "orchestral", "chiptune")


def test_original_midi_references_decode_without_corruption():
    for name in NAMES:
        source = (REFERENCE_DIR / f"{name}.mid.b85").read_text().strip()
        binary = zlib.decompress(base64.b85decode(source))
        assert binary.startswith(b"MThd"), name
        assert len(binary) > 1000, name
        assert int.from_bytes(binary[4:8], "big") == 6, name
