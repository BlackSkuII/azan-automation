"""Plays the azan: pause TV → set volume → cast → restore volume → resume TV."""

import logging
import os
import threading
import time

from azan import audio, cast as cast_module, tv_control

log = logging.getLogger("azan")

CAST_ATTEMPTS = 3
RETRY_DELAY = 6          # seconds between attempts (lets a sleeping speaker wake)
EARLY_FAILURE = 45       # a failure this soon after starting is worth retrying
STARTUP_ALLOWANCE = 25   # connecting + buffering before sound starts
MAX_UNKNOWN_DURATION = 600


class Player:
    def __init__(self, store, cast=cast_module, tv=tv_control,
                 clock=time.monotonic, sleep=time.sleep, on_result=None):
        self.store = store
        self.cast = cast
        self.tv = tv
        self.clock = clock
        self.sleep = sleep
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._now_playing = None
        self.last_result = None
        self.on_result = on_result  # told about every finished playback

    # ── public ──────────────────────────────────────────────────────────

    def status(self):
        return {"playing": self._now_playing, "last": self.last_result}

    def stop(self):
        if self._now_playing:
            log.info("Stop requested.")
            self._stop.set()
            return True
        return False

    def play_async(self, label, fajr=False, file=None, volume=None):
        """Start playback in the background. Returns False if already playing."""
        if self._busy.locked():
            return False
        threading.Thread(target=self.play, args=(label, fajr, file, volume),
                         name="azan-play", daemon=True).start()
        return True

    def play(self, label, fajr=False, file=None, volume=None):
        """Play now and wait until it finishes. Returns True on success."""
        if not self._busy.acquire(blocking=False):
            log.warning("%s: skipped — something is already playing.", label)
            return False
        try:
            self._stop.clear()
            ok, message = self._play(label, fajr, file, volume)
        except Exception as exc:  # never let a surprise kill the scheduler
            log.exception("%s: unexpected error", label)
            ok, message = False, str(exc)
        finally:
            self._now_playing = None
            self._busy.release()
        self.last_result = {"label": label, "ok": ok, "message": message,
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if self.on_result is not None:
            try:
                self.on_result(label, ok, message)
            except Exception:  # a notification must never break playback
                log.exception("Notification hook failed")
        return ok

    # ── internals ───────────────────────────────────────────────────────

    def _play(self, label, fajr, file, volume):
        s = self.store.get()
        device = s["device_name"]
        if not device:
            log.error("%s: no speaker chosen yet — open Settings.", label)
            return False, "No speaker chosen"

        name = file or (s["fajr_azan_file"] if fajr else s["azan_file"])
        try:
            path = audio.path_for(name)
        except audio.AudioError:
            path = ""
        length = audio.duration(path) if path else None
        if not path or not os.path.isfile(path):
            log.error("%s: audio file '%s' is missing.", label, name)
            return False, f"Audio file '{name}' is missing"
        if volume is None:
            volume = s["fajr_volume"] if fajr else s["volume"]

        self._now_playing = {"label": label, "file": name, "volume": volume,
                             "duration": length}
        log.info("%s: playing %s on %s at volume %s.", label, name, device, volume)

        previous = self.cast.get_volume(device)
        tv_paused = False
        try:
            tv_paused = self.tv.pause_tv(s)
        except Exception as exc:
            log.warning("TV pause failed: %s", exc)

        try:
            return self._cast_with_retries(label, device, path, volume, length,
                                           s["end_buffer_seconds"])
        finally:
            self._restore_volume(device, previous, s["volume_after"])
            if tv_paused:
                try:
                    self.tv.resume_tv(s)
                except Exception as exc:
                    log.warning("TV resume failed: %s", exc)

    def _cast_with_retries(self, label, device, path, volume, length, buffer_s):
        error = "Unknown error"
        for attempt in range(1, CAST_ATTEMPTS + 1):
            if attempt > 1:
                log.info("%s: retrying (attempt %d of %d)…", label, attempt, CAST_ATTEMPTS)
                if self._wait(RETRY_DELAY):
                    return False, "Stopped"
            try:
                self.cast.set_volume(device, volume)
            except cast_module.CastError as exc:
                error = f"Could not reach the speaker: {exc}"
                log.warning("%s: %s", label, error)
                continue
            try:
                proc = self.cast.start_cast(device, path)
            except cast_module.CastError as exc:
                log.error("%s: %s", label, exc)
                return False, str(exc)

            outcome, error = self._watch(proc, device, length, buffer_s)
            if outcome == "done":
                log.info("%s: finished.", label)
                return True, "Played"
            if outcome == "stopped":
                log.info("%s: stopped.", label)
                return False, "Stopped"
            if outcome == "failed-late":
                break
            log.warning("%s: cast failed (%s).", label, error)
        log.error("%s: could not play — %s", label, error)
        return False, error

    def _watch(self, proc, device, length, buffer_s):
        """Follow one catt process. Returns (outcome, error_text)."""
        started = self.clock()
        limit = (length + buffer_s + STARTUP_ALLOWANCE) if length else MAX_UNKNOWN_DURATION
        while True:
            code = proc.poll()
            elapsed = self.clock() - started
            if code is not None:
                if code == 0:
                    # Old catt versions return straight away; wait the track out.
                    if length and elapsed < 3:
                        if self._wait(length + buffer_s):
                            self.cast.stop(device)
                            return "stopped", ""
                    return "done", ""
                text = _last_line(proc)
                return ("failed" if elapsed < EARLY_FAILURE else "failed-late"), text
            if self._stop.is_set():
                _terminate(proc)
                self.cast.stop(device)
                return "stopped", ""
            if elapsed >= limit:
                _terminate(proc)  # sound has ended; catt just did not notice
                return "done", ""
            self.sleep(0.5)

    def _wait(self, seconds):
        """Sleep, waking early if stop is requested. Returns True if stopped."""
        end = self.clock() + seconds
        while self.clock() < end:
            if self._stop.is_set():
                return True
            self.sleep(0.5)
        return self._stop.is_set()

    def _restore_volume(self, device, previous, volume_after):
        target = volume_after if volume_after is not None else previous
        if target is None:
            log.warning("Could not read the speaker's earlier volume, so it was left as is.")
            return
        for _ in range(2):
            try:
                self.cast.set_volume(device, target)
                log.info("Speaker volume set back to %s.", target)
                return
            except cast_module.CastError:
                self.sleep(2)
        log.warning("Could not set the speaker volume back to %s.", target)


def _terminate(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _last_line(proc):
    try:
        text = (proc.stderr.read() if proc.stderr else "") or ""
    except Exception:
        text = ""
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return lines[-1].replace("Error: ", "") if lines else f"catt exit code {proc.returncode}"
