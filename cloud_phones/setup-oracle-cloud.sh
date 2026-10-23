#!/bin/bash
# Oracle Cloud ARM / Linux VPS setup for Redroid (Android in Docker).
#
# Redroid CANNOT boot under Docker Desktop/WSL2 (no binder transport) — phones
# sit "offline". This script provisions a native-Linux host the correct way,
# based on the official redroid-doc quickstart and a verified Oracle Cloud
# ARM64 Ubuntu 24.04 walkthrough:
#   * https://github.com/remote-android/redroid-doc        (official docs)
#   * https://ggami.net/posts/282                          (Oracle A1 + Ubuntu 24.04)
#
# Run as your normal user over SSH on the cloud instance:
#     bash setup-oracle-cloud.sh [cloud_phones/docker-compose.redroid.yml]
#
# What it does:
#   1. updates the OS
#   2. installs Docker Engine + the compose plugin
#   3. enables the Android binder transport that redroid MUST have:
#        apt install linux-modules-extra-$(uname -r)
#        modprobe binder_linux devices="binder,hwbinder,vndbinder"
#      (ashmem_linux is OPTIONAL on kernel >= 5.18 / Oracle 6.8 — see research)
#   4. boots the same docker-compose.redroid.yml stack from your PharmFlow repo
#   5. verifies containers are up AND that the ADB port is actually listening
#
# If this kernel ships no binder device, the script ABORTS with exact
# remediation rather than pretending it works.

set -euo pipefail

# Resolve the compose file, then operate from its directory so the relative
# `./data/redroid-*` volume mounts land in the right place regardless of CWD.
COMPOSE_REL="${1:-docker-compose.redroid.yml}"
COMPOSE="$(realpath "$COMPOSE_REL")"
COMPOSE_DIR="$(dirname "$COMPOSE")"
cd "$COMPOSE_DIR"

START_ADB="${ADB_START_PORT:-5555}"
COUNT="${REDROID_COUNT:-8}"

echo "=============================================="
echo "  Oracle Cloud / Linux VPS Redroid setup"
echo "  compose: $COMPOSE"
echo "=============================================="

echo "[1/7] Updating system..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

echo "[2/7] Installing Docker Engine + compose plugin..."
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo docker compose version >/dev/null 2>&1 \
    || sudo apt-get install -y docker-compose-plugin
sudo systemctl enable --now docker >/dev/null 2>&1 || true

# -----------------------------------------------------------------------------
# 3. Android binder transport — the decisive step. binder_linux ships in the
#    distro's linux-modules-extra for your kernel; that package is what we must
#    install (NOT a manual kernel build).
# -----------------------------------------------------------------------------
echo "[3/7] Enabling Android binder transport (redroid requires this)..."
sudo apt-get install -y "linux-modules-extra-$(uname -r)"

binder_present() {
    # legacy nodes OR binderfs
    { test -e /dev/binder  || test -e /dev/binder0; } \
        || { test -e /dev/hwbinder && test -e /dev/vndbinder; } \
        || test -e /dev/binderfs/binder
}

if ! binder_present; then
    echo "  Loading binder_linux with devices=binder,hwbinder,vndbinder ..."
    sudo modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null \
        || sudo modprobe binder_linux 2>/dev/null \
        || echo "  (binder_linux did not auto-load — trying binderfs, then gating)"
fi

# binderfs: many modern distro kernels expose binder via binderfs instead of a
# legacy /dev/binder node. Mount it and alias the classic node names.
if ! binder_present; then
    echo "  Trying binderfs at /dev/binderfs ..."
    sudo mkdir -p /dev/binderfs
    sudo mount -t binder binder /dev/binderfs 2>/dev/null || true
    if test -e /dev/binderfs/binder; then
        sudo ln -sf /dev/binderfs/binder         /dev/binder
        sudo ln -sf /dev/binderfs/hwbinder       /dev/hwbinder
        sudo ln -sf /dev/binderfs/vndbinder      /dev/vndbinder
        sudo ln -sf /dev/binderfs/binder-control /dev/binder-control
        echo "  ✓ binderfs mounted, classic binder nodes linked."
    fi
fi

# -----------------------------------------------------------------------------
# HARD ELIGIBILITY GATE — do not claim success when redroid cannot boot.
# -----------------------------------------------------------------------------
if ! binder_present; then
    echo
    echo "!! This kernel exposes NO binder device — redroid WILL NOT boot, ADB"
    echo "   phones will sit 'offline' (the exact symptom on the Windows/WSL2 box)."
    echo
    echo "   Fix the HOST, then re-run this script:"
    echo "     • Oracle Cloud A1 (Ampere ARM): choose a 'Canonical Ubuntu 24.04'"
    echo "       AArch64 image — its paravirtualized kernel (6.8.0-*-oracle)"
    echo "       ships binder_linux; install linux-modules-extra-\$(uname -r)."
    echo "     • Generic VPS: rebuild/swap the kernel with"
    echo "         CONFIG_ANDROID_BINDER_IPC=y  CONFIG_ANDROID_BINDERFS=y"
    echo "       and reinstall linux-modules-extra-\$(uname -r)."
    echo "   Then reboot and run: modprobe binder_linux devices=\"binder,hwbinder,vndbinder\""
    exit 1
fi
echo "  ✓ binder transport confirmed (/dev/binder or binderfs)."

# Persist binder_linux across reboots with the correct device options.
# ashMem is deliberately omitted: ashmem_linux does not exist on Oracle's
# kernel 6.8 (`modprobe: FATAL ... not found`, see ggami.net/posts/282) and is
# optional since kernel 5.18 removed it — redroid uses memfd instead.
echo 'binder_linux devices=binder,hwbinder,vndbinder' \
    | sudo tee /etc/modules-load.d/binder.conf >/dev/null
# Persist binderfs mount (best-effort; harmless if binderfs unsupported).
if ! grep -qs binderfs /etc/fstab; then
    echo "none /dev/binderfs binder defaults 0 0" | sudo tee -a /etc/fstab >/dev/null || true
fi

echo "[4/7] Installing adb on the host (optional)..."
command -v adb >/dev/null 2>&1 \
    || sudo apt-get install -y adb 2>/dev/null \
    || echo "  (adb not installed here — connect from your PC instead)"

echo "[5/7] Creating per-instance data dirs..."
for i in $(seq 0 $((COUNT-1))); do
    mkdir -p "data/redroid-$i"
done

echo "[6/7] Starting redroid stack ($(basename "$COMPOSE"))..."
sudo docker compose -f "$COMPOSE" up -d

echo "[7/7] Verifying containers up + ADB ports listening..."
# Give Android time to bring up adbd.
sleep 25
up=0
for i in $(seq 0 $((COUNT-1))); do
    c="redroid-$i"
    port=$((START_ADB+i))
    if sudo docker ps --format '{{.Names}}' | grep -q "^$c$"; then
        up=$((up+1))
        if timeout 4 bash -c "</dev/tcp/127.0.0.1/$port" 2>/dev/null; then
            echo "  ✓ $c ready on ADB port $port"
        else
            echo "  - $c container up but ADB port $port not listening yet"
            echo "     check: sudo dmesg -T | grep -i binder  |  sudo docker logs $c"
        fi
    else
        echo "  ✗ $c not running"
    fi
done

echo
echo "  Containers running: $up/$COUNT"
echo
echo "Connect ADB from your Windows PC to THIS host (do NOT expose 5555 publicly):"
for i in $(seq 0 $((COUNT-1))); do
    echo "    adb connect YOUR_IP:$((START_ADB+i))"
done
echo "Or with PharmFlow:"
echo "    PharmFlow.exe --cloud-phones-cli connect --host YOUR_IP --count $COUNT --start-port $START_ADB"
echo "    PharmFlow.exe --cloud-phones-cli setup   --host YOUR_IP --count $COUNT"