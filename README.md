# Azan Automation

Plays the Azan on a Google Home / Chromecast speaker at each prayer time, and
gives you a web page to control it from any phone or computer on your network:

```
http://<your-pi's-ip>:9090
```

**Runs on:** Raspberry Pi (Zero 2 W, 3, 4, 5), Linux, macOS (for testing)

## What you can do from the web page

| Tab | What's there |
|-----|--------------|
| **Today** | Today's azan times, countdown to the next one, on/off switch per prayer, test buttons, speaker check |
| **Settings** | Speaker (with a *Find* button), volumes, per-prayer time shift, masjid location and calculation method, TV pause |
| **Audio** | Listen to, upload, choose and delete azan recordings |
| **Activity** | What happened and when (played, failed, speaker not found…) |

### Add it to your phone's home screen

The page can be saved as an app icon and then opens full screen, without the
browser bars.

- **iPhone / iPad:** open the page in Safari → **Share** → **Add to Home Screen**.
- **Android:** open it in Chrome → menu (⋮) → **Add to Home screen**.

It still talks to the Pi over your Wi-Fi, so it only works at home.

All settings are stored **on the device** in `data/settings.json`. That folder
is ignored by Git, so `git pull` never touches your settings and nothing
personal ends up on GitHub.

## Install

```bash
git clone https://github.com/BlackSkuII/azan-automation.git
cd azan-automation
./setup.sh
```

`setup.sh` installs the Python packages, makes the service start on boot, and
prints the address of the web page. Open it, press **Find** under
*Settings → Speaker*, choose your speaker, and save. That's all.

Run `./setup.sh` again after every `git pull`; it is safe to repeat.

### Upgrading from version 1 (cron + `config.yaml`)

Keep your old settings by putting `config.yaml` aside while you pull:

```bash
cd ~/azan-automation
mv config.yaml /tmp/config.yaml
git checkout -- config.yaml
git pull
mv /tmp/config.yaml config.yaml
./setup.sh
```

On first start the service imports `config.yaml` (and the Home Assistant token
from `config.local.yaml`) into `data/settings.json`. After that the old files
are not read again and can be deleted. `setup.sh` also removes the old cron
jobs. If you skip this, just enter your speaker and volumes on the web page.

## How it works

One small service (`python -m azan`) does everything:

```
            ┌──────────────────────── azan service ───────────────────────┐
 browser ──▶│ web page :9090 ──▶ data/settings.json                       │
            │                                                             │
            │ scheduler ── once a day ──▶ Aladhan API (today's times)     │
            │     │                                                       │
            │     ├─ a few minutes before each azan ──▶ is the speaker    │
            │     │                                     on the network?   │
            │     └─ at azan time ──▶ pause TV → set volume → cast azan   │
            │                         → put volume back → resume TV      │
            └─────────────────────────────────────────────────────────────┘
```

Things it takes care of:

- **No network at midnight** — it keeps retrying, and meanwhile uses the last
  times it had (they move by a minute or two per day). The page tells you.
- **Speaker asleep** — the cast is retried up to three times.
- **Volume** — after the azan the speaker goes back to the volume it had
  before (or to a fixed level, if you prefer).
- **Recording length** — detected from the MP3; there is nothing to type in.
- **Restarts** — an azan is never replayed if the Pi or the service restarts.
- **Timezone** — the azan follows the masjid's local time even if the Pi's
  clock is set to another zone.
- **Speaker missing** — optionally restarts the Pi, which fixes a silently
  dropped Wi-Fi connection (at most once per 15 minutes of uptime).

### Prayer times

Times come from the [Aladhan API](https://aladhan.com/prayer-times-api) using
the same query as the masjid's website, so the azan matches its published
times:

```
https://api.aladhan.com/v1/timings/<DD-MM-YYYY>
    ?latitude=42.3601&longitude=-71.0589&method=2&school=1
```

`method=2` is ISNA and `school=1` is Hanafi Asr. Change them under
*Settings → Masjid & calculation*. These are **adhan** times; use the
per-prayer shift if you want it a few minutes earlier or later.

## Security

The web page has **no password**. Anyone on your home network can change the
settings or play a test azan, so do not forward port 9090 on your router or
expose it to the internet. The Home Assistant token is stored in a file only
your user can read and is never sent back to the browser.

## Useful commands

```bash
sudo systemctl status azan        # is it running?
sudo systemctl restart azan       # restart it
sudo journalctl -u azan -n 50     # service output
tail -50 azan.log                 # the same log the Activity tab shows

venv/bin/python -m azan --port 9090             # run by hand (stop the service first)
venv/bin/python -m unittest discover -s tests -t .   # tests (no network or speaker needed)
```

To use another port, run `AZAN_PORT=8080 ./setup.sh`.

## Project layout

```
azan/
├── __main__.py      start the service (web server + scheduler)
├── web.py           JSON API and page serving
├── static/index.html   the web page
├── scheduler.py     fetches times, fires the speaker check and the azan
├── player.py        pause TV → volume → cast → restore
├── cast.py          wrapper around the catt command
├── prayer_times.py  Aladhan API
├── settings.py      data/settings.json: defaults, validation, v1 import
├── audio.py         files in audio/, upload, MP3 length
├── tv_control.py    Home Assistant pause/resume
└── system.py        Pi detection, restart, IP address
audio/               azan recordings (MP3)
data/                settings and state — on the device only, not in Git
setup.sh             install / update
setup-pi.sh          one-shot preparation of a freshly flashed Pi
wifi-logger.sh       optional Wi-Fi event logger (NetworkManager dispatcher)
```

## License

MIT
