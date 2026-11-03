"""Re-orchestrate the five original FourierMotion MIDI scores into classic genres.

Preserves original melody, bass, harmonic movement and progressive layers.
The included .mid.b85 files are lossless zlib/base85 copies of the user's
original MIDI compositions, not algorithmically reconstructed approximations.
Uses General MIDI programs so a real SF2 soundfont renders every instrument.
"""
from __future__ import annotations

import base64
from pathlib import Path
import zlib

import pretty_midi

BASE = Path(__file__).resolve().parents[1]
REFERENCES = BASE / "soundtracks" / "references"
OUTPUT = BASE / "soundtracks" / "classic"
DURATION = 60.0
INTRO_END = 3.0
TRANSITION_IN_END = 3.4
TRANSITION_OUT_START = 54.6
FINAL_START = 55.0

# Reference score, four instrument patches (harmony, lead, bass, rising arp).
# Every score retains its original note pitches, timing and progression.
SCORES = {
    "rock": ("synthwave", (30, 29, 33, 27)),
    "anime": ("chiptune", (48, 80, 38, 10)),
    "forro": ("ambient", (21, 21, 32, 24)),
    "sertanejo": ("orchestral", (24, 25, 32, 26)),
    "hiphop": ("lofi", (4, 10, 38, 11)),
}
DRUMS = {
    "rock": (36, 38, 42),
    "anime": (36, 38, 46),
    "forro": (35, 37, 81),      # zabumba-like bass drum, side stick, triangle
    "sertanejo": (36, 37, 54), # acoustic kick, side stick, tambourine
    "hiphop": (36, 39, 42),    # deep kick, hand clap, closed hat
}


def load_reference(name: str) -> pretty_midi.PrettyMIDI:
    data = base64.b85decode((REFERENCES / f"{name}.mid.b85").read_text().strip())
    if not data.startswith(b"MThd"):
        data = zlib.decompress(data)
    return pretty_midi.PrettyMIDI(__import__("io").BytesIO(data))


def emit(inst, pitch: int, begin: float, duration: float, velocity: int) -> None:
    if begin < 0 or begin >= DURATION or duration <= 0:
        return
    end = min(DURATION - .005, begin + duration)
    if end > begin:
        inst.notes.append(pretty_midi.Note(
            velocity=max(1, min(127, velocity)),
            pitch=max(0, min(127, pitch)), start=begin, end=end))


def arrangement(genre: str) -> pretty_midi.PrettyMIDI:
    source, patches = SCORES[genre]
    original = load_reference(source)
    out = pretty_midi.PrettyMIDI(initial_tempo=120)
    for index, source_part in enumerate(original.instruments[:4]):
        inst = pretty_midi.Instrument(program=patches[index],
                                      name=f"{genre}: {source_part.name}")
        for note in source_part.notes:
            # MIDI source is composed on the same 60s score. Preserve its
            # progression, but do not bleed any notes over either transition.
            if INTRO_END <= note.start < TRANSITION_IN_END:
                continue
            if TRANSITION_OUT_START <= note.start < FINAL_START:
                continue
            end = (INTRO_END if note.start < INTRO_END
                   else TRANSITION_OUT_START if note.start < TRANSITION_OUT_START
                   else DURATION - .015)
            if note.start < end:
                v = note.velocity
                if note.start < INTRO_END:
                    v = int(v * .82)
                elif note.start >= FINAL_START:
                    v = min(127, int(v * 1.10))
                emit(inst, note.pitch, note.start,
                     min(note.end, end)-note.start, v)
        out.instruments.append(inst)

    percussion = pretty_midi.Instrument(program=0, is_drum=True,
                                        name=f"{genre}: dedicated groove")
    kick, snare, hat = DRUMS[genre]
    beat = .5
    for index in range(120):
        at = index * beat
        if (INTRO_END <= at < TRANSITION_IN_END or
                TRANSITION_OUT_START <= at < FINAL_START):
            continue
        if at < 3:
            # Intro previews the pulse; full rhythm enters after the cut.
            if index % 4 == 0:
                emit(percussion, kick, at, .10, 66)
            continue
        section_gain = 1.10 if at >= FINAL_START else 1.0
        gain = section_gain * (.82 if at < 15 else 1.0)
        step = index % 4
        if genre == "forro":
            emit(percussion, kick, at, .11, int(90*gain))
            emit(percussion, hat, at, .08, int(75*gain))
            if at + .25 < TRANSITION_OUT_START or at >= FINAL_START:
                emit(percussion, hat, at + .25, .07, int(60*gain))
            if step in (1, 3):
                emit(percussion, snare, at, .11, int(65*gain))
        elif genre == "sertanejo":
            if step in (0, 2):
                emit(percussion, kick, at, .10, int(78*gain))
            else:
                emit(percussion, snare, at, .10, int(70*gain))
            if index % 2 == 0:
                emit(percussion, hat, at, .12, int(62*gain))
        elif genre == "hiphop":
            if step in (0, 3):
                emit(percussion, kick, at, .14, int(100*gain))
            if step in (1, 3):
                emit(percussion, snare, at, .12, int(85*gain))
            emit(percussion, hat, at, .07, int(50*gain))
            if index % 4 in (1, 3):
                emit(percussion, hat, at+.25, .07, int(38*gain))
        else:
            if step in (0, 2):
                emit(percussion, kick, at, .12, int(98*gain))
            if step in (1, 3):
                emit(percussion, snare, at, .13, int(83*gain))
            emit(percussion, hat, at, .09, int(67*gain))
            if genre == "anime":
                emit(percussion, hat, at+.25, .08, int(48*gain))

    # Musical emphasis follows the normal Fourier revolution period.
    # Exact image-dependent changes are layered at video rendering time.
    for number, at in enumerate(__import__("numpy").arange(3.4, 54.6, 3.5)):
        emit(percussion, kick, float(at), .16, 95 if number%2 == 0 else 82)

    for at in (3.0, 54.6):
        # 400ms rising orchestral gesture, then downbeat near crossfade exit.
        effects = pretty_midi.Instrument(program=96, name=f"{genre}: transition sweep {at}")
        for index in range(8):
            start = at + index*.045
            emit(effects, 60 + index*2, start, .085, 36 + index*6)
        out.instruments.append(effects)
        emit(percussion, 49, at+.32, .12, 90)  # Crash at transition edge.

    # Five-second payoff is harmonically resolved, not a generic loop ending.
    emit(percussion, kick, FINAL_START, .22, 118)
    emit(percussion, 49, FINAL_START, .65, 112)
    for at in (56.0, 57.0, 58.0):
        emit(percussion, kick, at, .13, 80)
    out.instruments.append(percussion)
    return out


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for order, genre in enumerate(SCORES, 1):
        midi = arrangement(genre)
        destination = OUTPUT / f"FourierMotion_{order:02d}_{genre}_60s.mid"
        midi.write(str(destination))
        print(f"{genre}: {sum(len(i.notes) for i in midi.instruments)} MIDI notes -> {destination}")


if __name__ == "__main__":
    main()
