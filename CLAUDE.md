# Azan Automation

Automated prayer time (Azan) player for Google Home / Chromecast devices on Raspberry Pi Zero 2 W.

## Project Structure

One long-running service (`python -m azan`, systemd unit `azan.service`) runs
the scheduler and a web UI on port 9090. No cron jobs are used any more.

```
azan-automation/
├── azan/                 # Python package (stdlib only, plus catt + mutagen)
│   ├── __main__.py       # entry point: logging, scheduler thread, web server
│   ├── web.py            # JSON API + serves static/index.html
│   ├── static/index.html # the whole web UI (vanilla JS, no build step)
│   ├── scheduler.py      # daily fetch, pre-azan speaker check, azan trigger
│   ├── player.py         # pause TV → volume → cast (with retries) → restore
│   ├── cast.py           # catt CLI wrapper (scan, status, volume, cast, stop)
│   ├── prayer_times.py   # Aladhan API (masjid's exact query)
│   ├── settings.py       # data/settings.json: defaults, validation, v1 import
│   ├── audio.py          # audio/ listing, upload, MP3 duration
│   ├── tv_control.py     # Home Assistant TV pause/resume
│   └── system.py         # Pi detection, guarded reboot, LAN IP
├── audio/                # Azan MP3 files
├── data/                 # settings.json, times.json, state.json (git-ignored)
├── tests/                # unittest suite, no network/speaker needed
├── install.sh            # one-command install/update: code, venv, systemd unit
├── setup-pi.sh           # optional Pi housekeeping (fresh re-flashes only)
└── wifi-logger.sh        # WiFi event logger (NM dispatcher)
```

Settings are edited in the web UI and stored only on the Pi
(`data/settings.json`). Never add settings files to Git.

## Install and First-Run Setup

There is no terminal-based app setup any more. `install.sh` is the only
command a user runs (`curl … | bash` or `./install.sh` in a checkout); it
fetches the code, builds the venv, installs `catt` + `mutagen`, writes the
systemd unit and starts the service. Everything else happens in the browser.

- On first load the page calls `GET /api/status`; when
  `setup_complete` is `false` it shows the full-screen setup flow in
  `static/index.html` (5 steps: masjid, speaker, recording/volume, TV pause,
  test). Each Next saves through `POST /api/settings`; Finish calls
  `POST /api/setup {"complete": true}`.
- `setup_complete` is a normal settings key (`settings.DEFAULTS`, validated as
  a bool). A settings file saved before the wizard existed is upgraded to
  `setup_complete: true` on load, so existing/Pi devices never see the wizard;
  a v1 `config.yaml` import is marked complete too.
- A corrupt or missing `settings.json` on a real install therefore lands in the
  wizard — that is intended, it is how the device gets configured again.
- Settings → Setup → **Run setup again** reopens the wizard without clearing
  anything (it prefills from the saved settings).
- Keep the wizard's step list, `SETUP_STEPS`, in sync with `App.setup` and the
  README's setup table when adding fields.

## Prayer Times Source
Aladhan API, fixed masjid location (no device GPS): `latitude=42.3601`,
`longitude=-71.0589`, `method=2` (ISNA), `school=1` (Hanafi) — identical to the
masjid website/app at zamongajumath.com. Defaults live in
`azan/settings.py`; changed from the web UI (Settings → Masjid & calculation).

## Common Commands

### Pi Access
```bash
ssh raspi@10.147.18.185                    # ZeroTier (may be flaky)
ssh raspi@192.168.1.5                      # Local WiFi IP
rpi-connect ssh raspi                      # rpi-connect (backup)
```

### Logs
```bash
ssh raspi@10.147.18.185 "tail -30 ~/azan-automation/azan.log"
ssh raspi@10.147.18.185 "tail -30 ~/azan-automation/wifi.log"
```

### Azan Testing
```bash
venv/bin/python -m unittest discover -s tests -t .     # local, no network
ssh raspi@10.147.18.185 "systemctl status azan --no-pager"
ssh raspi@10.147.18.185 "curl -s localhost:9090/api/status"
```
Test playback from the web UI (Today → Test azan); it can be stopped there.

### Pi Health
```bash
ssh raspi@10.147.18.185 "uptime && vcgencmd get_throttled"
ssh raspi@10.147.18.185 "free -h && df -h /"
```

### Service (runs on Pi)
```bash
sudo systemctl restart azan
sudo journalctl -u azan -n 50
```

### Install / Update
```bash
curl -fsSL https://raw.githubusercontent.com/BlackSkuII/azan-automation/main/install.sh | bash   # fresh Pi
cd ~/azan-automation && git pull && ./install.sh                                                 # update
```
The installer only handles code + packages + the systemd unit. Speaker,
recording, volumes, masjid and TV are configured in the browser (first run
opens the setup wizard automatically).
Web UI: `http://192.168.1.5:9090`

## Gotchas

### Google Home Deep Sleep
Google Home can fall into deep sleep between the pre-azan check and the azan.
`catt scan` works (mDNS) but `catt cast` fails (needs TCP). `player.py` retries
the cast up to 3 times, a few seconds apart.

### catt facts the code relies on
- `catt scan` prints `ip - name - model`; `catt scan -j` prints JSON.
- `catt cast <local file>` blocks until playback ends (exit 0), so the player
  watches the process instead of sleeping for a fixed duration.
- `catt status` prints `Volume: N`; used to restore the previous volume.

### SD Card Protection (Pi Zero 2 W)
- `/tmp`, `/var/log` → tmpfs (RAM, wiped on reboot)
- journald → volatile mode (50MB max, 1-day retention)
- `azan.log` → rotated by the service itself (300 KB, 1 backup)
- **Sudden power loss is safe** — no writes to SD card during normal operation

### WiFi Drops
Pi Zero 2 W (BCM43430) drops WiFi every 30-60 seconds. ZeroTier becomes unreachable; reconnects automatically. rpi-connect is backup access.

### Full Paths in NetworkManager Dispatcher
Scripts in `/etc/NetworkManager/dispatcher.d/` have limited PATH. Use full paths: `/usr/bin/date`, `/usr/bin/nmcli`, `/usr/bin/head`, etc.

### SSH Key Location
Always use `/home/raspi/.ssh/`, never `~/.ssh/` — `~` expands to `/root` under sudo.

## Pi Setup (setup-pi.sh)
For fresh Pi re-flashes, run `setup-pi.sh` which handles:
- WiFi power save disabled
- Sleep/suspend masked
- HDMI blanking disabled
- tmpfs for /tmp, /var/log
- journald volatile mode
- rpi-connect auto-restart
- ZeroTier install + join
- SSH key added
- `install.sh` run (service + web UI on port 9090)

After setup: authorize ZeroTier device at my.zerotier.com

## Google Home
Chosen in the web UI (Settings → Speaker → Find). Prefer the speaker's name over its IP, which changes with DHCP.
