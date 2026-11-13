#!/usr/bin/env python3
"""Fetch today's prayer times and update cron jobs.

Called daily at midnight and @reboot by cron.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from azan import config, prayer_times, scheduler


def main():
    dry_run = "--dry-run" in sys.argv

    cfg = config.load_config_or_exit()

    masjid_name = config.get(cfg, "masjid_name")
    latitude = float(config.get(cfg, "latitude"))
    longitude = float(config.get(cfg, "longitude"))
    method = int(config.get(cfg, "method"))
    school = int(config.get(cfg, "school"))

    print(
        f"[{datetime.now()}] Fetching prayer times for {masjid_name} "
        f"({latitude}, {longitude}) "
        f"[method={method}, school={school}]..."
    )

    try:
        times = prayer_times.fetch_prayer_times(
            latitude, longitude, method, school,
        )
    except Exception as e:
        print(f"ERROR fetching prayer times: {e}")
        sys.exit(1)

    print("\nToday's Prayer Schedule:")
    for name, t in times.items():
        print(f"  {name}: {t}")

    cron_lines = scheduler.generate_cron_jobs(cfg, times)

    if dry_run:
        scheduler.print_cron_preview(cron_lines)
    else:
        if scheduler.write_cron(cron_lines):
            print("\nCron updated successfully.")
        else:
            print("\nERROR updating cron.")
            sys.exit(1)


if __name__ == "__main__":
    main()
