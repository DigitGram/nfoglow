# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Background music: the built-in chiptunes by Stennish (CC BY 4.0, see data/music/README.md), or the tracks of a
folder (MOD/XM/S3M/IT like the old C64 and Amiga demos, or OGG/MP3/FLAC/WAV). Played with GStreamer, which comes with every
GNOME desktop."""
import math
import os
import random
from collections import deque
from pathlib import Path

import gi
from gi.repository import GLib

try:   # only ask whether GStreamer is installed: loading and starting it waits until music is switched on
    gi.require_version("Gst", "1.0")
    INSTALLED = True
except ValueError:   # no GStreamer: NfoGlow works, just without music
    INSTALLED = False
Gst = None   # the module, imported by the first Player

AUDIO = (".mod", ".xm", ".s3m", ".it", ".mptm", ".ogg", ".oga", ".opus", ".mp3", ".flac", ".wav", ".m4a")
HERE = Path(__file__).resolve().parent
BUILTIN = next((str(d) for d in (HERE / "music", HERE.parent / "data" / "music") if d.is_dir()), "")  # installed / checkout
INTRO, LOOP_END, LOOPS = 8.0, 48.0, 2   # built-in tracks: intro 0-8 s, loop 8-48 s; the loop plays twice per track
FADE_IN, FADE_END, FADE_OFF = 3.0, 3.0, 1.5   # seconds: start of the music, end of each track, switching it off


def available():
    return INSTALLED


def tracks(folder):
    """The audio files of a folder, sorted by name."""
    try:
        return sorted((os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(AUDIO)),
                      key=str.lower)
    except OSError:
        return []


class Beat:
    """Turns the loudness of 25 ms windows (dB, in the order they are heard) into a pulse 0..1 that jumps on a beat
    and fades out until the next one.

    The loudness itself hardly moves in dense music: a chiptune stays within a few dB, so a glow that follows it only
    flickers around the middle. A beat is a window that is clearly louder than the moment before it, so the pulse
    follows that rise, measured against the strongest rises of the last second: loud and quiet tracks pulse alike,
    small rises (hi-hats, the notes of a melody) stay under the threshold, a long tone flashes once and then rests."""

    STEP = .025          # seconds per window, the level meter's interval
    THRESHOLD = .5       # a rise must be at least half the recent strongest one to count
    RELEASE = .18        # seconds for the pulse to fall to a third

    def __init__(self):
        self.avg, self.ref, self.value = -60.0, 3.0, 0.0

    def feed(self, db):
        db = max(db, -60.0)
        heard = max(db, self.avg - 12)   # a moment of silence between two notes is no beat when the next one comes
        rise = max(0.0, heard - self.avg)
        self.avg += (heard - self.avg) * (self.STEP / .3)   # the loudness of about the last 0.3 s
        self.ref = max(rise, 3.0, self.ref * math.exp(-self.STEP))   # the strongest rise of about the last second
        loud = min(1.0, max(0.0, (db + 30) / 20))   # a soft beat pulses a little less
        hit = min(1.0, max(0.0, (rise / self.ref - self.THRESHOLD) / ((1 - self.THRESHOLD) * .85))) * (.5 + .5 * loud)
        self.value = max(hit, self.value * math.exp(-self.STEP / self.RELEASE))
        return self.value


class Player:
    """One playbin for the whole app. level(): the beat of what is heard now, 0..1, for the pulsing glow (see Beat).

    Built-in tracks play their intro once and then their loop, without a gap: a "segment seek" ends at the end of
    the loop, and when GStreamer reports the segment done, the next segment seek starts the loop again. That report
    comes when the data is read, about a second before it is heard; so the last round is a normal seek, whose
    end-of-stream comes only when everything has played, and only then the next track starts."""

    def __init__(self):
        global Gst
        from gi.repository import Gst as gst
        Gst = gst
        if not Gst.is_initialized():
            Gst.init(None)
        self.bin = Gst.ElementFactory.make("playbin")
        if self.bin is None:
            raise RuntimeError("GStreamer has no playbin (gst-plugins-base is missing)")
        meter = Gst.ElementFactory.make("level")
        if meter:
            meter.set_property("interval", 25_000_000)   # ns: short windows, so a beat shows up close to when it starts
            meter.set_property("post-messages", True)
            self.bin.set_property("audio-filter", meter)
        bus = self.bin.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", lambda *a: self._next())
        bus.connect("message::error", self._error)
        bus.connect("message::element", self._level)
        bus.connect("message::async-done", self._prerolled)
        bus.connect("message::segment-done", self._segment_done)
        self.queue, self.order, self.shuffle, self.playing = [], [], True, False
        self.on_track = None   # called with (path, number in the list, list length) when a different track starts
        self._current = None
        self.builtin, self._seek_pending, self._loops_left, self._level_value, self._errors = False, False, 0, 0.0, 0
        self.fade, self._in, self._off, self._ticking = False, 1.0, None, False
        self._levels = deque(maxlen=200)   # (running time when it is heard, loudness in dB), see _level
        self._beat = Beat()

    def level(self):
        """The beat of what is heard now: the measurements wait until the playback clock reaches them."""
        if not self.playing:
            return 0.0
        now = self._now()
        while self._levels and now is not None and self._levels[0][0] <= now:
            self._level_value = self._beat.feed(self._levels.popleft()[1])
        return self._level_value

    def _now(self):
        """The running time of the playback in ns, or None without a clock."""
        clock = self.bin.get_clock()
        return clock.get_time() - self.bin.get_base_time() if clock else None

    def play(self, folder, shuffle, volume, fade=True):
        """fade: start quietly (nothing blares out of the speakers) and let every track end softly."""
        self.stop()
        self.playing, self.shuffle, self._errors, self.fade = True, shuffle, 0, fade
        self._in = 0.0 if fade else 1.0
        self.set_volume(volume)
        if not self._ticking:
            self._ticking = True
            GLib.timeout_add(50, self._tick)
        self.queue = tracks(folder) if folder else []
        self.builtin = not self.queue
        if self.builtin:
            self.queue = tracks(BUILTIN)
        if not self.queue:
            self.stop()
            return
        self.order = []
        self._next()

    def _next(self):
        if not self.playing or not self.queue:
            return
        if not self.order:
            self.order = random.sample(self.queue, len(self.queue)) if self.shuffle else list(self.queue)
        track = self.order.pop(0)
        if self.on_track and track != self._current:   # one track on repeat is announced once
            self.on_track(track, self.queue.index(track) + 1, len(self.queue))
        self._current = track
        self._levels.clear()   # a new track starts its clock anew
        self._loops_left = LOOPS - 1 if self.builtin else 0
        self._seek_pending = self.builtin
        self.bin.set_state(Gst.State.NULL)
        self.bin.set_property("uri", GLib.filename_to_uri(track, None))
        self.bin.set_state(Gst.State.PAUSED if self.builtin else Gst.State.PLAYING)

    def _seek(self, start, flags):
        if self._loops_left > 0:   # more rounds to come: end in segment-done, not in end-of-stream
            flags |= Gst.SeekFlags.SEGMENT
        self.bin.seek(1.0, Gst.Format.TIME, flags | Gst.SeekFlags.ACCURATE,
                      Gst.SeekType.SET, int(start * Gst.SECOND), Gst.SeekType.SET, int(LOOP_END * Gst.SECOND))

    def _prerolled(self, *_a):
        self._errors = 0   # a track loaded: only failures in a row make the player give up
        if self._seek_pending:   # a built-in track is ready: intro plus loop as the first segment
            self._seek_pending = False
            self._seek(0, Gst.SeekFlags.FLUSH)
            self.bin.set_state(Gst.State.PLAYING)

    def _segment_done(self, *_a):
        self._loops_left -= 1
        self._seek(INTRO, Gst.SeekFlags.NONE)   # no flush: the loop follows without a gap

    def _error(self, _bus, _msg):
        self._errors += 1   # e.g. a format without a plugin: skip it, but give up when nothing plays
        if self._errors < max(3, len(self.queue)):
            self._next()
        else:
            self.stop()

    def _level(self, _bus, msg):
        """A loudness measurement. It is made when the music is decoded, about a second before the sound card plays
        it; so it is kept with the running time of its start and used when playback gets there (level()). Its start,
        not its end: the window that holds the beat is then shown when the beat begins, not one window later."""
        st = msg.get_structure()
        if st and st.get_name() == "level":
            rms = st.get_value("rms")
            db = max(rms) if rms else -60
            ok, heard = st.get_uint64("running-time")
            if ok:
                self._levels.append((heard, db))
            else:   # an old GStreamer without the field: use it at once
                self._level_value = self._beat.feed(db)

    def _left(self):
        """Seconds until the track ends, or None while that is not known (or a built-in loop comes round again)."""
        if self.builtin and self._loops_left > 0:
            return None
        ok, pos = self.bin.query_position(Gst.Format.TIME)
        end = LOOP_END * Gst.SECOND if self.builtin else self.bin.query_duration(Gst.Format.TIME)[1]
        return (end - pos) / Gst.SECOND if ok and end > 0 else None

    def _fades(self):
        """The volume factor now: fading in, towards the end of a track, or while switching off."""
        f = self._in
        if self.fade:
            left = self._left()
            if left is not None:
                f *= max(0.0, min(1.0, left / FADE_END))
        if self._off is not None:
            f *= self._off
        return f

    def _tick(self):
        if not self.playing:
            self._ticking = False
            return False
        self._in = min(1.0, self._in + 0.05 / FADE_IN)
        if self._off is not None:
            self._off -= 0.05 / FADE_OFF
            if self._off <= 0:
                self.stop()
                self._ticking = False
                return False
        self.set_volume(self.volume)
        return True

    def set_volume(self, volume):
        self.volume = volume
        self.bin.set_property("volume", (volume * self._fades()) ** 2)   # squared sounds more even

    def stop(self, fade=False):
        """Stop at once, or with fade over a second and a half."""
        if fade and self.playing:
            self._off = 1.0 if self._off is None else self._off
            return
        self.playing, self._level_value, self._seek_pending, self._current, self._off = False, 0.0, False, None, None
        self._levels.clear()
        self._beat = Beat()
        self.bin.set_state(Gst.State.NULL)
