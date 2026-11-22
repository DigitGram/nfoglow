#!/usr/bin/env python3
"""Offline beat analysis of the built-in tracks: tempo and beat grid from spectral flux (needs numpy + ffmpeg).

    python3 tools/analyze_beats.py [file.ogg ...]     # report only
    python3 tools/analyze_beats.py --write            # also write data/music/beats.json

All built-in tracks run at 120 bpm, but are dense: onsets sit on nearly every eighth note. So the pulse does not
chase loudness; it is a grid of eighth notes (STEP seconds) per track, with the accent of every position in a
bar (BAR seconds), measured here. The grid phase is the onset position mod STEP, in seconds from the file start.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR, WIN, HOP = 22050, 1024, 256
INTRO, LOOP_END = 8.0, 48.0
BPM = 120.0
STEP, BAR = 60 / BPM / 2, 4 * 60 / BPM   # an eighth note; a bar of four beats (8 positions)


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def onset_envelope(x):
    """Spectral flux: how much new energy appears per frame, summed over all bands (log-compressed)."""
    n = 1 + (len(x) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(WIN), axis=1))[:, 2:370]   # up to about 8 kHz
    spec = np.log1p(100 * spec)
    flux = np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)
    flux = np.maximum(0, flux - np.convolve(flux, np.ones(41) / 41, "same"))   # minus the local average
    return flux / (flux.max() or 1)


def tempo(env, fps, lo=70, hi=200):
    env = env - env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    best = max(range(int(fps * 60 / hi), int(fps * 60 / lo)), key=lambda l: ac[l] + .5 * ac[min(2 * l, len(ac) - 1)])
    return 60 * fps / best, ac


def grid(env, fps, bpm):
    """Phase of the beat grid: the offset (seconds) whose comb collects the most onset energy."""
    period = 60 / bpm * fps
    best = max(np.arange(0, period, .5),
               key=lambda p: env[np.minimum((p + period * np.arange(int((len(env) - p) / period))).astype(int), len(env) - 1)].sum())
    return best / fps


def onset_times(env, fps, start):
    """Seconds (in the file) of every frame of the envelope; an onset is seen a quarter window after it begins."""
    return start + (np.arange(len(env)) + 1) / fps + WIN / 4 / SR


def profile(x):
    """(phase, accents): the grid phase (seconds mod STEP) and the strength 0..1 of each of the 8 positions of a bar."""
    env = onset_envelope(x[int(INTRO * SR):int(LOOP_END * SR)])
    t = onset_times(env, SR / HOP, INTRO)
    h, edges = np.histogram(t % STEP, bins=100, range=(0, STEP), weights=env)
    h = np.convolve(np.r_[h[-2:], h, h[:2]], np.ones(5) / 5, "valid")   # smooth, wrapping round
    phase = (np.argmax(h) + .5) * STEP / 100
    if min(phase, STEP - phase) < .04:   # the flux sees an attack about 20 ms early: a phase this close to 0 is 0
        phase = 0.0
    pos = np.round((t - phase) / STEP).astype(int)
    near = np.abs(t - phase - pos * STEP) < STEP / 3   # the onsets that belong to a grid point
    acc = np.bincount(pos[near] % 8, env[near], 8)
    return round(float(phase), 3), [round(float(v), 3) for v in acc / acc.max()]


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [Path(a) for a in args] or sorted(Path(__file__).resolve().parent.parent.glob("data/music/*.ogg"))
    fps = SR / HOP
    out = {}
    for f in files:
        x = decode(f)
        loop = onset_envelope(x[int(INTRO * SR):int(LOOP_END * SR)])
        bpm, _ = tempo(loop, fps)
        phase, acc = profile(x)
        out[f.name] = {"phase": phase, "accents": acc}
        print(f"{f.name}: {bpm:6.1f} bpm (taken: {BPM:.0f})  phase {phase:.3f} s  accents {acc}")
    if "--write" in sys.argv:
        dest = Path(__file__).resolve().parent.parent / "data" / "music" / "beats.json"
        dest.write_text(json.dumps({"bpm": BPM, "tracks": out}, indent=1) + "\n")
        print("wrote", dest)
