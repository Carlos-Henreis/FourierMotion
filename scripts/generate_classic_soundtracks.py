"""Generate five original 60-second classic soundtracks with scene-aware arrangements.

No third-party samples or copyrighted melodies. Deterministic synthesis with numpy.
Run: python scripts/generate_classic_soundtracks.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import wave
import numpy as np

SR = 16000
DURATION = 60
SIZE = SR * DURATION
ROOT = Path(__file__).resolve().parents[1] / "soundtracks" / "classic"
SECTIONS = (3.0, 3.4, 54.6, 55.0)
GENRES = ("rock", "anime", "forro", "sertanejo", "hiphop")

# Each genre has its own tempo, orchestration, harmony and rhythm.
SPECS = {
    "rock": (112, [40, 43, 45, 47], [0, 3, 5, 7, 10]),
    "anime": (148, [45, 48, 50, 52], [0, 2, 4, 7, 11]),
    "forro": (120, [38, 43, 45, 41], [0, 2, 4, 7, 9]),
    "sertanejo": (98, [43, 47, 40, 45], [0, 2, 4, 7, 9]),
    "hiphop": (88, [36, 41, 43, 38], [0, 3, 5, 7, 10]),
}


def midi(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def synth(kind: str, hz: float, length: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(length, dtype=np.float64) / SR
    phase = 2 * np.pi * hz * t
    if kind == "guitar":
        # Band-limited additive string, amp-driven soft clipping.
        x = sum(np.sin(phase * k + 0.2 * k) / (k ** 1.1) for k in range(1, 15))
        x = np.tanh(1.9 * x) * np.exp(-2.6 * t)
    elif kind == "piano":
        x = sum(np.sin(phase * k * (1 + .00013 * k)) / k ** 1.65
                for k in range(1, 10))
        x *= (1 - np.exp(-110 * t)) * np.exp(-3.4 * t)
    elif kind == "strings":
        x = sum(np.sin(phase * k + .28 * np.sin(2 * np.pi * 5.4 * t)) / k**1.25
                for k in range(1, 10))
        x *= (1 - np.exp(-9 * t)) * np.exp(-.8 * t)
    elif kind == "accordion":
        x = sum(np.sin(phase * k + .1 * np.sin(2*np.pi*5.2*t)) / k**1.05
                for k in range(1, 12))
        x += .24 * np.sin(phase * 1.008)
        x *= (1 - np.exp(-55 * t)) * np.exp(-1.6 * t)
    elif kind == "viola":
        x = np.zeros(length)
        for detune in (.996, 1.004):
            x += sum(np.sin(phase * k * detune) / k**1.2 for k in range(1, 12))
        x *= (1 - np.exp(-175 * t)) * np.exp(-5.6 * t)
    elif kind == "rhodes":
        x = np.sin(phase) + .43*np.sin(phase*2.01) + .18*np.sin(phase*5.02)
        x *= (1-np.exp(-100*t))*np.exp(-3.0*t)
        x = np.tanh(x * 1.3)
    elif kind == "bass":
        x = np.sin(phase) + .25*np.sin(2*phase) + .12*np.sin(3*phase)
        x *= (1-np.exp(-90*t))*np.exp(-3*t)
    else:
        raise ValueError(kind)
    return x.astype(np.float32)


def drum(kind: str, length: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(length, dtype=np.float64) / SR
    noise = rng.standard_normal(length)
    if kind == "kick":
        phase = 2 * np.pi * (55*t + 105*(1-np.exp(-24*t))/24)
        x = (np.sin(phase) * np.exp(-18*t) + .14*noise*np.exp(-110*t))
    elif kind == "snare":
        noise = np.diff(np.r_[noise[0],noise])
        x = .55*noise*np.exp(-26*t) + .3*np.sin(2*np.pi*175*t)*np.exp(-35*t)
    elif kind == "hat":
        noise = np.diff(np.r_[noise[0], noise])
        x = .24*noise*np.exp(-85*t)
    elif kind == "zabumba":
        x = np.sin(2*np.pi*(70*t+32*(1-np.exp(-24*t))/24))*np.exp(-19*t)
    elif kind == "triangle":
        x = (.5*np.sin(2*np.pi*3100*t)+.3*np.sin(2*np.pi*4350*t))*np.exp(-37*t)
    elif kind == "clap":
        noise = np.diff(np.r_[noise[0], noise])
        gate = (np.sin(2*np.pi*29*t) > -.2).astype(float)
        x = .43*noise*gate*np.exp(-22*t)
    else:
        raise ValueError(kind)
    return x.astype(np.float32)


def add(buf: np.ndarray, sound: np.ndarray, at: float, gain: float) -> None:
    start = round(at*SR)
    if start < 0 or start >= len(buf):
        return
    n = min(len(sound), len(buf)-start)
    buf[start:start+n] += gain*sound[:n]


def envelope(t: np.ndarray) -> np.ndarray:
    # Short opening teaser; two 400ms transition sweeps; confident payoff.
    out = np.ones_like(t, dtype=np.float32)
    out *= np.minimum(1, t/.17)
    out *= np.minimum(1, (60-t)/.45)
    for start in (3.0, 54.6):
        delta = np.abs(t-(start+.20))
        out *= 1 - .45*np.clip(1-delta/.24, 0, 1)
    return out


def make(genre: str) -> np.ndarray:
    rng = np.random.default_rng(20261103 + GENRES.index(genre)*71)
    bpm, roots, scale = SPECS[genre]
    beat = 60.0 / bpm
    result = np.zeros(SIZE, dtype=np.float32)
    voice = {"rock":"guitar","anime":"piano","forro":"accordion",
             "sertanejo":"viola","hiphop":"rhodes"}[genre]
    # Entire opening and reveal get their own harmony, not just a constant drone.
    for start, stop in ((0.0, 3.0), (3.4, 54.6), (55.0, 60.0)):
        k = 0
        while start + k*beat < stop:
            at = start + k*beat
            bar = k//4
            root = roots[bar % len(roots)]
            intro = start == 0.0
            reveal = start == 55.0
            # Downbeat bass is clear; chords and riffs identify the genre.
            bass_at = at
            if k % 2 == 0 or genre == "hiphop":
                add(result, synth("bass", midi(root-12), round(.48*SR), rng),
                    bass_at, .21 if genre != "hiphop" else .31)
            note = root + 12 + scale[(k + (bar % 3)) % len(scale)]
            duration = (.34 if not reveal else .65)
            if genre == "rock":
                if k%2 == 0:
                    for interval in (0, 7, 12):
                        add(result, synth(voice, midi(root+interval), round(.43*SR),rng),
                            at, .095)
                add(result,synth(voice,midi(note),round(duration*SR),rng),at,.13)
            elif genre == "anime":
                for offset, level in ((0,.14),(7,.08),(12,.055)):
                    add(result,synth("piano",midi(root+12+offset),round(.56*SR),rng),at,level)
                if k%2 == 0:
                    add(result,synth("strings",midi(note),round(.85*SR),rng),at,.065)
            elif genre == "forro":
                for offset in (0, 4, 7):
                    add(result,synth("accordion",midi(root+12+offset),
                                     round(.38*SR),rng),at,.08)
                if k%2 == 1:
                    add(result,synth(voice,midi(note+12),round(.24*SR),rng),at,.11)
            elif genre == "sertanejo":
                for offset, delay in ((0,0), (7,beat*.20),(12,beat*.4)):
                    if at+delay < stop:
                        add(result,synth("viola",midi(root+12+offset),
                                         round(.48*SR),rng),at+delay,.15)
                add(result,synth(voice,midi(note),round(.24*SR),rng),at,.075)
            else:
                for offset in (0,3,7):
                    add(result,synth("rhodes",midi(root+12+offset),
                                     round(.85*SR),rng),at,.095)
                if k%4 == 2:
                    add(result,synth("rhodes",midi(note+12),
                                     round(.40*SR),rng),at+.12,.14)
            # Distinct groove from each style, subdued while introducing the image.
            rhythm = .52 if intro else (1.08 if reveal else .85)
            hit = k%4
            if genre == "forro":
                add(result, drum("zabumba",round(.28*SR),rng),at,.23*rhythm)
                add(result, drum("triangle",round(.12*SR),rng),at,.20*rhythm)
                if at+beat*.5 < stop:
                    add(result, drum("triangle",round(.09*SR),rng),
                        at+beat*.5,.14*rhythm)
            else:
                if hit in ((0,2) if genre != "hiphop" else (0,3)):
                    add(result,drum("kick",round(.35*SR),rng),at,.34*rhythm)
                if hit in (1,3):
                    percussion = "clap" if genre=="hiphop" else "snare"
                    add(result,drum(percussion,round(.23*SR),rng),at,.16*rhythm)
                if genre != "sertanejo":
                    add(result,drum("hat",round(.12*SR),rng),at,.085*rhythm)
                    if at+beat*.5 < stop and genre in ("rock","anime","hiphop"):
                        add(result,drum("hat",round(.09*SR),rng),
                            at+beat*.5,.045*rhythm)
            k += 1

    # Follow the Fourier pen's nominal 3.5s revolutions: a rising accent
    # anticipates each reset (actual stage count varies by input image).
    for at in np.arange(3.4,54.6,3.5):
        add(result,drum("kick",round(.33*SR),rng),float(at),.29)
        add(result,synth(voice,midi(roots[int((at-3.4)//3.5)%4]+24),
                         round(.37*SR),rng),float(at),.13)

    # Sonic riser/sweep tightly mirrors each visual 400ms crossfade.
    for at in (3.0,54.6):
        length = round(.4*SR)
        t = np.arange(length)/SR
        noise = rng.standard_normal(length)
        swoosh = .15*noise*np.sin(np.pi*t/.4)**2
        swoosh += .18*np.sin(2*np.pi*(320*t+900*t*t))*np.sin(np.pi*t/.4)**2
        add(result,swoosh.astype(np.float32),at,1.0)
        add(result,drum("kick",round(.4*SR),rng),at+.32,.37)

    # Distinct final 5s melodic resolve and impact precisely at 55.
    root = roots[0]
    for offset, at, gain in ((0,55.0,.25),(7,56.0,.17),(12,57.2,.22),
                             (16,58.4,.13)):
        add(result,synth(voice,midi(root+12+offset),round(1.15*SR),rng),at,gain)
    add(result,drum("kick",round(.55*SR),rng),55.0,.50)

    t = np.arange(SIZE)/SR
    result *= envelope(t)
    # Soft limiter avoids digital clipping and keeps mastering consistent.
    result = np.tanh(result*1.5)
    peak = max(float(np.max(np.abs(result))), 1e-9)
    return (result / peak * 0.88 * 32767).astype("<i2")


def main() -> None:
    ROOT.mkdir(parents=True,exist_ok=True)
    for index, genre in enumerate(GENRES,1):
        name = f"FourierMotion_{index:02d}_{genre}_60s.wav"
        samples = make(genre)
        output = ROOT/name
        with wave.open(str(output),"wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SR)
            wav.writeframes(samples.tobytes())
        print(f"{output.name} sha256={hashlib.sha256(samples.tobytes()).hexdigest()}")


if __name__ == "__main__":
    main()
