#!/usr/bin/env bash
# Azan Automation — installer / updater.
# Safe to run again at any time (for example after `git pull`).
#
# It installs the Python packages, sets the service to start on boot and
# prints the address of the web page. Everything else is done in the browser.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${AZAN_PORT:-9090}"
RUN_USER="$(id -un)"
cd "$DIR"

[ "$RUN_USER" = "root" ] && error "Run this as your normal user, not with sudo."

IS_PI=0; IS_ZERO=0
if [ -r /proc/device-tree/model ]; then
    MODEL="$(tr -d '\0' < /proc/device-tree/model)"
    echo "$MODEL" | grep -qi "raspberry" && IS_PI=1
    echo "$MODEL" | grep -qi "zero" && IS_ZERO=1
fi

echo ""
echo "  Azan Automation — setup"
echo ""

# ── 1. Python ───────────────────────────────────────────────
python_ok() {
    command -v python3 >/dev/null 2>&1 &&
        python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' &&
        python3 -c 'import venv, ensurepip' >/dev/null 2>&1
}
if ! python_ok; then
    warn "Python 3.9+ with venv not found — installing"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm python python-pip
    elif command -v brew >/dev/null 2>&1; then
        brew install python3
    else
        error "Please install Python 3.9 or newer, then run this again."
    fi
    python_ok || error "Python 3.9+ is still not available."
fi
info "Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# ── 2. Packages ─────────────────────────────────────────────
[ -x venv/bin/python ] || python3 -m venv venv
PIP_FLAGS=(--quiet --disable-pip-version-check)
[ "$IS_ZERO" = 1 ] && PIP_FLAGS+=(--no-cache-dir)   # save space on the Pi Zero
echo "  Installing packages (a few minutes on a Pi Zero)..."
venv/bin/python -m pip install "${PIP_FLAGS[@]}" -r requirements.txt
[ -x venv/bin/catt ] || error "catt did not install correctly."
info "Packages installed"

mkdir -p data audio

# ── 3. Remove the old cron jobs from version 1 ──────────────
if command -v crontab >/dev/null 2>&1 && crontab -l >/dev/null 2>&1; then
    if crontab -l | grep -Eq 'play_azan\.py|check_device\.py|setup_cron\.py'; then
        crontab -l | grep -Ev 'play_azan\.py|check_device\.py|setup_cron\.py' | crontab - || true
        info "Old cron jobs removed (the service schedules the azan now)"
    fi
fi

# The service keeps its own small rotating log; drop the old logrotate rule.
if [ -f /etc/logrotate.d/azan ]; then sudo rm -f /etc/logrotate.d/azan || true; fi

# ── 4. Start on boot ────────────────────────────────────────
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    sudo tee /etc/systemd/system/azan.service >/dev/null <<UNIT
[Unit]
Description=Azan Automation (prayer-time azan player and web page)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
Environment=AZAN_PORT=$PORT
ExecStart="$DIR/venv/bin/python" -m azan
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable azan.service >/dev/null 2>&1
    sudo systemctl restart azan.service
    sleep 3
    if systemctl is-active --quiet azan.service; then
        info "Service is running and will start on boot"
    else
        warn "The service did not start. See: sudo journalctl -u azan -n 30"
    fi

    # Let the service restart the Pi (speaker check / web page) without a password.
    if [ "$IS_PI" = 1 ] && ! sudo grep -rqs "NOPASSWD:.*reboot" /etc/sudoers.d 2>/dev/null; then
        echo "$RUN_USER ALL=(ALL) NOPASSWD: $(command -v reboot || echo /usr/sbin/reboot)" |
            sudo tee /etc/sudoers.d/azan-reboot >/dev/null
        sudo chmod 440 /etc/sudoers.d/azan-reboot
        info "Passwordless restart enabled"
    fi
    STARTED=1
else
    STARTED=0
fi

# ── Done ────────────────────────────────────────────────────
IP="$(venv/bin/python -c 'from azan.system import local_ip; print(local_ip() or "")' 2>/dev/null || true)"
echo ""
echo "  ─────────────────────────────────────────────"
if [ "$STARTED" = 1 ]; then
    echo "  Open this on any phone or computer on your network:"
    echo ""
    echo "      http://${IP:-<this-device-ip>}:$PORT"
    echo ""
    echo "  Choose your speaker there and you're done."
else
    echo "  No systemd here, so start it yourself:"
    echo ""
    echo "      venv/bin/python -m azan"
    echo ""
    echo "  Then open http://${IP:-localhost}:$PORT"
fi
echo "  ─────────────────────────────────────────────"
echo ""
