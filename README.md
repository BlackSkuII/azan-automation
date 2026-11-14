# Azan Automation

Automated prayer time (Azan) player for Google Home / Chromecast devices.

Fetches daily prayer times from the [Aladhan API](https://aladhan.com/prayer-times-api) using the **same query as the masjid's website** (same coordinates, ISNA method, Hanafi asr), casts Azan audio to your Google Home at each prayer time, and optionally pauses/resumes your TV via Home Assistant.

**Works on:** Raspberry Pi (Zero 2 W, 3, 4, 5), Linux, macOS

## Quick Start

No prerequisites — just run:

```bash
git clone https://github.com/BlackSkuII/azan-automation.git
cd azan-automation
./setup.sh
```

`setup.sh` installs Python 3 if missing, then launches the interactive installer.

The installer will guide you through:

1. **System deps** — installs `python3-venv` etc. on Pi/Linux
2. **Virtual env** — creates `venv/` with all Python packages
3. **Masjid location** — coordinates, calculation method, asr school (pre-filled with the masjid's values)
4. **Device discovery** — scans for Google Home devices on your network
5. **Home Assistant** *(optional)* — pauses/resumes TV during Azan
6. **Audio files** — paths to your Azan MP3 files
7. **Cron setup** — schedules everything automatically

### Add Your Audio Files

Place your Azan MP3s in the `audio/` directory:

```
audio/azan.mp3        # Regular azan
audio/fajr_azan.mp3   # Fajr azan (different recitation)
```

Set the duration (in seconds) in `config.yaml` to match your audio files (+ a few seconds buffer).

## How It Works

```
Daily @ Midnight + @Reboot
        │
        ▼
  setup_cron.py                ← Fetches today's prayer times from API
        │
        ▼
  Cron Updated                 ← 10 jobs: 5 device checks + 5 azan plays
        │
   ┌────┴──────────────────────────────────────┐
   │                                            │
   ▼  (5 min before prayer)                    ▼  (at prayer time)
  check_device.py            play_azan.py
  Scans for Google Home      Pauses TV → Plays Azan → Resumes TV
  Reboots Pi if not found
```

## Configuration

Shared settings are stored in the tracked `config.yaml`, which you can edit on GitHub and pull onto your Pi. The optional `config.local.yaml` is ignored by Git and overrides shared settings. Keep secrets such as `ha_token` only in `config.local.yaml` (the installer saves the token there). Never commit tokens to GitHub.

To update an existing Pi for the first time, back up its old ignored config **outside the repository** before pulling, because it would otherwise conflict with the new tracked file:

```bash
cp config.yaml ~/azan-config-backup.yaml
rm config.yaml
git pull
```

If the old config contains a Home Assistant token, copy it into `config.local.yaml` on the Pi (for example, `ha_token: "your-token"`); also copy any other settings you want to override locally. Treat the backup as sensitive. After editing `config.yaml` on GitHub and pulling, run `venv/bin/python setup_cron.py` to apply changes to the schedule and the volume stored in existing cron jobs immediately. Otherwise, cron refreshes at midnight or reboot. The installer can also modify the tracked config locally, so commit or back up local changes before pulling.

Settings include:

| Setting | Default | Description |
|---------|---------|-------------|
| `masjid_name` | Allston Brighton Islamic Center | Name used in logs |
| `latitude` | 42.3601 | Masjid latitude (fixed — not device GPS) |
| `longitude` | -71.0589 | Masjid longitude |
| `method` | 2 | Prayer calculation method (2 = ISNA) |
| `school` | 1 | 0=Shafi, 1=Hanafi (1 = Hanafi asr) |
| `device_name` | — | Google Home device name |
| `volume` | 100 | Volume during non-Fajr Azans (0-100); reset to 100 afterward |
| `fajr_volume` | Same as `volume` | Volume during Fajr Azan (0-100); reset to 100 afterward |
| `azan_file` | audio/azan.mp3 | Path to regular azan audio |
| `fajr_azan_file` | audio/fajr_azan.mp3 | Path to Fajr azan audio |
| `scan_before_minutes` | 5 | Minutes before prayer to check device |
| `ha_url` | — | Home Assistant URL (empty = skip TV control) |
| `ha_token` | — | HA long-lived access token; store in `config.local.yaml` only |
| `tv_entity_id` | — | HA media_player entity for TV |

### Prayer Times API

Prayer times come from the Aladhan API with the exact request the masjid's website/app uses:

```
https://api.aladhan.com/v1/timings/<DD-MM-YYYY>
    ?latitude=42.3601&longitude=-71.0589&method=2&school=1
```

- **Fixed masjid coordinates** — device GPS is never used, so every screen and speaker shows identical times.
- **`method=2`** — Islamic Society of North America (ISNA), the masjid's calculation method.
- **`school=1`** — Hanafi asr, the masjid's school.

If the masjid changes any of these, update `latitude`, `longitude`, `method`, or `school` in `config.yaml` (the defaults live in `azan/prayer_times.py` and `azan/config.py`). The API returns **adhan** times; iqamah offsets are handled by the masjid's app, not here.

Existing `config.yaml` files from the old city-based version (with `city`/`country` and `method: 1`) are upgraded automatically: they switch to the masjid's fixed coordinates and ISNA/Hanafi settings on load. Delete `city`/`country` from the file when convenient.

### Prayer Calculation Methods

| ID | Method |
|----|--------|
| 1 | University of Islamic Sciences, Karachi |
| 2 | Islamic Society of North America (ISNA) — **masjid default** |
| 3 | Muslim World League |
| 4 | Umm Al-Qura University, Makkah |
| 5 | Egyptian General Authority of Survey |
| 7 | Institute of Geophysics, University of Tehran |

## Manual Commands

```bash
# Reconfigure
python3 install.py

# Fetch today's prayer times and update cron
python3 setup_cron.py

# Preview cron without writing
python3 setup_cron.py --dry-run

# Play azan manually (the supplied volume overrides config for that run)
venv/bin/python play_azan.py 100
venv/bin/python play_azan.py 100 fajr

# Check device connectivity
venv/bin/python check_device.py

# Run tests (no network needed)
venv/bin/python -m unittest discover -s tests
```

## Requirements

- **None** — `setup.sh` installs everything (Python 3, venv, pip packages)
- A Google Home / Chromecast device on the same network
- *(Optional)* Home Assistant running locally for TV control

## Platform Notes

- **Raspberry Pi Zero 2 W**: Fully supported. Uses `--no-cache-dir` for pip to save disk space. If the Google Home is unreachable before prayer time, the Pi reboots automatically.
- **Raspberry Pi 3/4/5**: Recommended. Best performance.
- **Linux desktop/server**: Works. Uses cron for scheduling.
- **macOS**: Works for development/testing. Reboot on device failure is skipped.

## License

MIT
