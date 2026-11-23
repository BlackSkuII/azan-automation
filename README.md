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

One command on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/BlackSkuII/azan-automation/main/install.sh | bash
```

If you would rather keep the checkout yourself:

```bash
git clone https://github.com/BlackSkuII/azan-automation.git
cd azan-automation
./install.sh
```

The installer does only what a web page cannot do: it fetches the code,
creates the Python environment, installs `catt` and `mutagen`, makes the
service start on boot and prints the web page address. **Everything else is
done in the browser.** Open that address on your phone or computer and the
page walks you through it — nothing needs to be typed into the Pi.

After a `git pull`, run `./install.sh` once more (or paste the one-liner
again); it is safe to repeat and picks up new packages and code.

### Setup in the browser

A device that has not been set up yet opens a short setup flow instead of the
normal page:

| Step | What you do |
|------|-------------|
| **Masjid** | Name, latitude/longitude, calculation method and Asr school |
| **Speaker** | **Find speakers** scans the network and lists what it sees — tap yours |
| **Recording** | Pick the azan and Fajr MP3s (or upload one) and set the volumes |
| **TV pause** | Optional: Home Assistant address, token and media player |
| **Try it** | Play the azan on the speaker, then finish |

Each step is saved as you go, so closing the browser does not lose progress.
*Settings → Setup → Run setup again* reopens the same flow later, and a device
that already has `data/settings.json` is treated as set up and goes straight to
the normal page.

### Upgrading from version 1 (cron + `config.yaml`)

Keep your old settings by putting `config.yaml` aside while you pull:

```bash
cd ~/azan-automation
mv config.yaml /tmp/config.yaml
git checkout -- config.yaml
git pull
mv /tmp/config.yaml config.yaml
./install.sh
```

On first start the service imports `config.yaml` (and the Home Assistant token
from `config.local.yaml`) into `data/settings.json`. After that the old files
are not read again and can be deleted. The installer also removes the old cron
jobs. An imported v1 configuration counts as set up, so the browser setup flow
is skipped — *Settings → Setup → Run setup again* opens it if you want it.

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

To use another port, run `AZAN_PORT=8080 ./install.sh`.

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
install.sh           one-command installer / updater (code, packages, service)
setup-pi.sh          optional Pi housekeeping (tmpfs, journald, HDMI, ZeroTier…)
wifi-logger.sh       optional Wi-Fi event logger (NetworkManager dispatcher)
```

## License

MIT
