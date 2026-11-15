import os
import tempfile

from azan.cast import CastError
from azan.settings import SettingsStore


def temp_store(testcase, **values):
    d = tempfile.TemporaryDirectory()
    testcase.addCleanup(d.cleanup)
    store = SettingsStore(os.path.join(d.name, "settings.json"))
    with store._lock:
        store._data.update(values)
    return store, d.name


class FakeProc:
    """Stands in for the catt process: ``codes`` are successive poll() results."""

    def __init__(self, codes, stderr=""):
        self.codes = list(codes)
        self.returncode = None
        self.terminated = False
        self.stderr = None
        self._stderr = stderr

    def poll(self):
        if self.returncode is None and self.codes:
            self.returncode = self.codes.pop(0)
        if self.stderr is None and self.returncode is not None:
            import io
            self.stderr = io.StringIO(self._stderr)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminated = True


class FakeCast:
    CastError = CastError

    def __init__(self, procs=(), volume=30, devices=()):
        self.procs = list(procs)
        self.volume = volume
        self.devices = list(devices)
        self.calls = []
        self.volume_failures = 0
        self.scan_error = None

    def get_volume(self, device):
        return self.volume

    def set_volume(self, device, level):
        if self.volume_failures:
            self.volume_failures -= 1
            raise CastError("speaker asleep")
        self.calls.append(("volume", level))
        self.volume = level

    def start_cast(self, device, path):
        self.calls.append(("cast", os.path.basename(path)))
        return self.procs.pop(0)

    def stop(self, device):
        self.calls.append(("stop",))

    def scan(self):
        if self.scan_error:
            raise CastError(self.scan_error)
        return self.devices

    @staticmethod
    def matches(device, wanted):
        from azan import cast
        return cast.matches(device, wanted)


class FakeTV:
    def __init__(self, playing=True):
        self.playing = playing
        self.calls = []

    def pause_tv(self, settings):
        self.calls.append("pause")
        return self.playing

    def resume_tv(self, settings):
        self.calls.append("resume")


class FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
