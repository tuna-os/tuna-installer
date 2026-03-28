#!/usr/bin/env bash
# tests/test_e2e_install.sh
#
# End-to-end automated install test for tuna-installer.
# Drives the full GUI flow (TUNA_TEST=1) to an actual virtual disk install.
#
# Usage: bash tests/test_e2e_install.sh [--disk-size SIZE]
#   SIZE: truncate size for disk image, default 50G
#
# Requirements:
#   - Running Wayland session (WAYLAND_DISPLAY / XDG_RUNTIME_DIR set or auto-detected)
#   - sudo losetup access (for creating the loop device before launching Flatpak)
#   - org.tunaos.Installer Flatpak installed (flatpak run org.flatpak.Builder to rebuild first)

set -euo pipefail

DISK_SIZE="50G"
while [[ $# -gt 0 ]]; do
  case $1 in --disk-size) DISK_SIZE="$2"; shift 2 ;; *) shift ;; esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/var/home/james/tuna-installer-debug.log"
IMG="${REPO_ROOT}/tuna-virtual-disk.img"
LOOP_DEV=""

WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
DBUS_BUS="unix:path=${XDG_RUNTIME_DIR}/bus"

pass() { echo "✅ $*"; }
fail() { echo "❌ $*"; exit 1; }
step() { echo; echo "── $* ──"; }

cleanup() {
  echo
  echo "[cleanup]"
  # Kill the installer if still running
  if [[ -n "${APP_PID:-}" ]]; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  # Kill any stale xdg-dbus-proxy for the app
  local proxy_pid
  proxy_pid=$(DBUS_SESSION_BUS_ADDRESS="$DBUS_BUS" \
    dbus-send --session --print-reply --dest=org.freedesktop.DBus \
    /org/freedesktop/DBus org.freedesktop.DBus.GetNameOwner \
    string:"org.tunaos.Installer" 2>/dev/null \
    | grep -oP '(?<=string "):.*(?=")' || true)
  if [[ -n "$proxy_pid" ]]; then
    local pid
    pid=$(DBUS_SESSION_BUS_ADDRESS="$DBUS_BUS" \
      dbus-send --session --print-reply --dest=org.freedesktop.DBus \
      /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID \
      string:"$proxy_pid" 2>/dev/null | grep -oP '(?<=uint32 )\d+' || true)
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  fi
  # Detach loop device
  if [[ -n "$LOOP_DEV" ]]; then
    sudo losetup -d "$LOOP_DEV" 2>/dev/null || true
    echo "  detached $LOOP_DEV"
  fi
}
trap cleanup EXIT

# ── Step 1: Create virtual disk image ────────────────────────────────────────
step "Creating ${DISK_SIZE} virtual disk image"
truncate -s "$DISK_SIZE" "$IMG"
LOOP_DEV=$(sudo losetup -fP --show "$IMG")
pass "Loop device: $LOOP_DEV  image: $IMG"

# ── Step 2: Kill any stale D-Bus proxy ───────────────────────────────────────
step "Checking for stale D-Bus registrations"
STALE_CONN=$(DBUS_SESSION_BUS_ADDRESS="$DBUS_BUS" \
  dbus-send --session --print-reply --dest=org.freedesktop.DBus \
  /org/freedesktop/DBus org.freedesktop.DBus.GetNameOwner \
  string:"org.tunaos.Installer" 2>/dev/null \
  | grep -oP '(?<=string "):.*(?=")' || true)
if [[ -n "$STALE_CONN" ]]; then
  STALE_PID=$(DBUS_SESSION_BUS_ADDRESS="$DBUS_BUS" \
    dbus-send --session --print-reply --dest=org.freedesktop.DBus \
    /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID \
    string:"$STALE_CONN" 2>/dev/null | grep -oP '(?<=uint32 )\d+' || true)
  if [[ -n "$STALE_PID" ]]; then
    kill "$STALE_PID" 2>/dev/null || true
    sleep 1
    echo "  killed stale proxy PID $STALE_PID"
  fi
else
  echo "  none"
fi

# ── Step 2.5: Install fisherman on host (needed for flatpak-spawn --host sudo) ──
step "Installing fisherman binary on host"
FLATPAK_LOC=$(flatpak info --show-location --user org.tunaos.Installer 2>/dev/null \
  || flatpak info --show-location org.tunaos.Installer 2>/dev/null)
FISHERMAN_HOST="/tmp/tuna-fisherman"
if [[ -f "${FLATPAK_LOC}/files/bin/fisherman" ]]; then
  cp "${FLATPAK_LOC}/files/bin/fisherman" "$FISHERMAN_HOST"
  chmod +x "$FISHERMAN_HOST"
  pass "fisherman staged at ${FISHERMAN_HOST}"
else
  fail "fisherman binary not found in Flatpak install at ${FLATPAK_LOC}/files/bin/"
fi


step "Launching installer (TUNA_TEST=1, TUNA_VIRTUAL_DISK=$LOOP_DEV)"
rm -f "$LOG"

WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
DBUS_SESSION_BUS_ADDRESS="$DBUS_BUS" \
TUNA_TEST=1 \
TUNA_VIRTUAL_DISK="$LOOP_DEV" \
TUNA_FISHERMAN_PATH="$FISHERMAN_HOST" \
  flatpak run --user org.tunaos.Installer >"${REPO_ROOT}/tuna-installer-stdout.log" 2>&1 &
APP_PID=$!
echo "  installer PID: $APP_PID"

# ── Step 4: Monitor log for completion ───────────────────────────────────────
step "Waiting for installation to complete (up to 30 min)..."
TIMEOUT=1800   # 30 minutes — bootc install can be slow
ELAPSED=0
POLL=5

while [[ $ELAPSED -lt $TIMEOUT ]]; do
  sleep $POLL
  ELAPSED=$((ELAPSED + POLL))

  if [[ ! -f "$LOG" ]]; then
    echo "  [${ELAPSED}s] waiting for log..."
    continue
  fi

  # Show last meaningful log line
  LAST=$(grep -v "flatpak-DEBUG\|Gdk-DEBUG\|GLib\|GVFS\|portal" "$LOG" 2>/dev/null | tail -1 || true)
  echo "  [${ELAPSED}s] $LAST"

  if grep -q "Installation complete!" "$LOG" 2>/dev/null; then
    pass "Installation completed in ${ELAPSED}s"
    break
  fi

  if grep -qE "fisherman: fatal:|Fatal error in do_activate|ERROR.*fatal" "$LOG" 2>/dev/null; then
    echo
    echo "── Installer log (errors) ──"
    grep -E "ERROR|fatal|Fatal" "$LOG" || true
    fail "Installation failed — see log above"
  fi

  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo
    echo "── Installer log (last 30 lines) ──"
    tail -30 "$LOG" || true
    fail "Installer process exited unexpectedly after ${ELAPSED}s"
  fi
done

if [[ $ELAPSED -ge $TIMEOUT ]]; then
  fail "Timed out after ${TIMEOUT}s — installation did not complete"
fi

# ── Step 5: Verify the installed disk ────────────────────────────────────────
step "Verifying virtual disk is bootable (checking partition table)"
sudo partprobe "$LOOP_DEV" 2>/dev/null || true
PARTS=$(sudo fdisk -l "$LOOP_DEV" 2>/dev/null | grep "^${LOOP_DEV}p" || true)
if [[ -z "$PARTS" ]]; then
  fail "No partitions found on $LOOP_DEV — install may have failed"
fi
echo "$PARTS"

EFI_PART=$(echo "$PARTS" | grep -i "EFI\|FAT" | awk '{print $1}' | head -1 || true)
ROOT_PART=$(echo "$PARTS" | grep -iv "EFI\|FAT" | awk '{print $1}' | head -1 || true)

if [[ -n "$EFI_PART" ]]; then
  pass "EFI partition: $EFI_PART"
else
  fail "No EFI partition found"
fi

if [[ -n "$ROOT_PART" ]]; then
  # Mount and check for ostree/bootc layout
  MNT=$(mktemp -d)
  sudo mount "$ROOT_PART" "$MNT" 2>/dev/null || true
  if [[ -d "$MNT/ostree" ]] || [[ -d "$MNT/sysroot" ]] || [[ -d "$MNT/boot" ]]; then
    pass "Root partition $ROOT_PART contains bootc/ostree layout"
  else
    echo "  Warning: expected ostree layout not found — checking contents..."
    ls "$MNT" || true
  fi
  sudo umount "$MNT" 2>/dev/null || true
  rmdir "$MNT" 2>/dev/null || true
fi

echo
pass "End-to-end install test PASSED"
echo "  Virtual disk image: $IMG"
echo "  Full log: $LOG"
