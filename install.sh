#!/usr/bin/env bash
# Azan Automation — one-command installer.
#
# On a fresh Raspberry Pi (or any Linux/macOS machine with Python 3.9+):
#
#   curl -fsSL https://raw.githubusercontent.com/BlackSkuII/azan-automation/main/install.sh | bash
#
# or, inside a checkout:
#
#   ./install.sh
#
# This does only what a web page cannot do: fetch the code, create the Python
# environment, install catt + mutagen, install the systemd service and start
# it. Everything else — masjid, speaker, recording, volume, TV pause, a test
# azan — is set up in the browser. Open http://<device-ip>:9090 afterwards.
#
# Safe to run again at any time (after a git pull, or to change the port).

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

REPO_URL="${AZAN_REPO:-https://github.com/BlackSkuII/azan-automation.git}"
INSTALL_DIR="${AZAN_DIR:-$HOME/azan-automation}"
PORT="${AZAN_PORT:-9090}"
RUN_USER="$(id -un)"

[ "$RUN_USER" = "root" ] && error "Run this as your normal user, not with sudo."

echo ""
echo "  Azan Automation — install"
echo ""

# ── 1. Find the code ────────────────────────────────────────
# As ./install.sh the checkout is this script's folder (also after a git pull).
# Piped from curl there is no checkout, so clone it into INSTALL_DIR instead.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/azan/__main__.py" ]; then
    DIR="$SELF_DIR"
    info "Using the checkout in $DIR"
else
    DIR="$INSTALL_DIR"
    if ! command -v git >/dev/null 2>&1; then
        warn "git is not installed — installing it"
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update -qq && sudo apt-get install -y git
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y git
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm git
        elif command -v brew >/dev/null 2>&1; then
            brew install git
        else
            error "Please install git, then run this again."
        fi
    fi
    if [ -f "$DIR/azan/__main__.py" ]; then
        if [ -d "$DIR/.git" ]; then
            info "Updating $DIR"
            git -C "$DIR" pull --ff-only || warn "Could not update — using the copy that is there."
        else
            info "Using the code in $DIR"
        fi
    else
        info "Downloading the code to $DIR"
        git clone --depth 1 "$REPO_URL" "$DIR" || error "Could not download $REPO_URL"
    fi
fi
cd "$DIR"

IS_PI=0; IS_ZERO=0
if [ -r /proc/device-tree/model ]; then
    MODEL="$(tr -d '\0' < /proc/device-tree/model)"
    echo "$MODEL" | grep -qi "raspberry" && IS_PI=1
    echo "$MODEL" | grep -qi "zero" && IS_ZERO=1
fi

# ── 2. Python ───────────────────────────────────────────────
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

# ── 3. Packages ─────────────────────────────────────────────
[ -x venv/bin/python ] || python3 -m venv venv
PIP_FLAGS=(--quiet --disable-pip-version-check)
[ "$IS_ZERO" = 1 ] && PIP_FLAGS+=(--no-cache-dir)   # save space on the Pi Zero
echo "  Installing packages (a few minutes on a Pi Zero)..."
venv/bin/python -m pip install "${PIP_FLAGS[@]}" -r requirements.txt
[ -x venv/bin/catt ] || error "catt did not install correctly."
info "Packages installed"

mkdir -p data audio

# ── 4. Remove the old cron jobs from version 1 ──────────────
if command -v crontab >/dev/null 2>&1 && crontab -l >/dev/null 2>&1; then
    if crontab -l | grep -Eq 'play_azan\.py|check_device\.py|setup_cron\.py'; then
        crontab -l | grep -Ev 'play_azan\.py|check_device\.py|setup_cron\.py' | crontab - || true
        info "Old cron jobs removed (the service schedules the azan now)"
    fi
fi

# The service keeps its own small rotating log; drop the old logrotate rule.
if [ -f /etc/logrotate.d/azan ]; then sudo rm -f /etc/logrotate.d/azan || true; fi

# ── 5. Start on boot ────────────────────────────────────────
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
        STARTED=1
    else
        warn "The service did not start. See: sudo journalctl -u azan -n 30"
        STARTED=0
        SERVICE_FAILED=1
    fi

    # Let the service restart the Pi (speaker check / web page) without a password.
    if [ "$IS_PI" = 1 ] && ! sudo grep -rqs "NOPASSWD:.*reboot" /etc/sudoers.d 2>/dev/null; then
        echo "$RUN_USER ALL=(ALL) NOPASSWD: $(command -v reboot || echo /usr/sbin/reboot)" |
            sudo tee /etc/sudoers.d/azan-reboot >/dev/null
        sudo chmod 440 /etc/sudoers.d/azan-reboot
        info "Passwordless restart enabled"
    fi
else
    STARTED=0
fi

# ── Done ────────────────────────────────────────────────────
IP="$(venv/bin/python -c 'from azan.system import local_ip; print(local_ip() or "")' 2>/dev/null || true)"
STARTED="${STARTED:-0}"; SERVICE_FAILED="${SERVICE_FAILED:-0}"
echo ""
echo "  ─────────────────────────────────────────────"
if [ "$STARTED" = 1 ]; then
    echo "  Open this on any phone or computer on your network:"
    echo ""
    echo "      http://${IP:-<this-device-ip>}:$PORT"
    echo ""
    echo "  The page walks you through the rest: masjid, speaker,"
    echo "  recording, volume and a test azan."
elif [ "$SERVICE_FAILED" = 1 ]; then
    echo "  The service is installed but did not start."
    echo ""
    echo "      sudo journalctl -u azan -n 30"
    echo ""
    echo "  Fix that, then open http://${IP:-<this-device-ip>}:$PORT in a browser."
else
    echo "  No systemd here, so start it yourself:"
    echo ""
    echo "      venv/bin/python -m azan"
    echo ""
    echo "  Then open http://${IP:-localhost}:$PORT — the page walks"
    echo "  you through the rest."
fi
echo "  ─────────────────────────────────────────────"
echo ""
