"""Run the Azan service: ``python -m azan`` (web page on port 9090)."""

import argparse
import logging
import logging.handlers
import os
import sys
import threading

from azan import __version__, paths, system
from azan.player import Player
from azan.scheduler import Scheduler
from azan.settings import SettingsStore
from azan.web import App, make_server


def setup_logging():
    fmt = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("azan")
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        # Small rotating file: gentle on the SD card and never grows unbounded.
        handler = logging.handlers.RotatingFileHandler(
            paths.LOG_FILE, maxBytes=300_000, backupCount=1)
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        root.warning("Cannot write %s: %s", paths.LOG_FILE, exc)
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description="Azan Automation service")
    parser.add_argument("--host", default=os.environ.get("AZAN_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("AZAN_PORT", "9090")))
    args = parser.parse_args(argv)

    os.makedirs(paths.DATA_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(paths.LOG_FILE), exist_ok=True)
    log = setup_logging()

    store = SettingsStore()
    player = Player(store)
    scheduler = Scheduler(store, player)
    store.on_change(scheduler.settings_changed)

    try:
        server = make_server(App(store, scheduler, player), args.host, args.port)
    except OSError as exc:
        log.error("Cannot open port %d: %s", args.port, exc)
        return 1

    threading.Thread(target=scheduler.run_forever, name="azan-scheduler",
                     daemon=True).start()
    log.info("Azan Automation %s — web page at http://%s:%d",
             __version__, system.local_ip() or "localhost", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
