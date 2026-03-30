# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**tuna-installer** is a GTK4/Libadwaita Flatpak GUI installer for TunaOS and Universal Blue bootc container images. It has two components: a Python GTK4 frontend and a Go backend (`fisherman`) that runs as a git submodule.

## Build commands

```bash
# Build and install Flatpak locally (~10 min first time, cached after)
flatpak run org.flatpak.Builder --force-clean --user --install _build flatpak/org.tunaos.Installer.json

# Bundle for deployment to another machine
flatpak build-bundle ~/.local/share/flatpak/repo org.tunaos.Installer.flatpak org.tunaos.Installer

# Deploy to a remote machine
scp org.tunaos.Installer.flatpak james@<ip>:~
ssh james@<ip> "flatpak uninstall --user -y org.tunaos.Installer; flatpak install --user --bundle -y ~/org.tunaos.Installer.flatpak"

# Native (non-Flatpak) build
meson setup build && ninja -C build && sudo ninja -C build install
```

## fisherman (Go submodule) commands

```bash
cd fisherman/fisherman
go build ./cmd/fisherman/    # compile check
go vet ./...                  # lint

# Run fisherman directly (needs root for disk ops)
go build -o /tmp/fisherman ./cmd/fisherman/
sudo /tmp/fisherman /path/to/recipe.json
```

## Two-component architecture

### fisherman (Go, `fisherman/fisherman/`)
Root-level CLI that reads a JSON recipe and executes a 9-step disk install pipeline. Emits newline-delimited JSON progress to stdout:
```json
{"type":"step","step":2,"total_steps":9,"step_name":"Formatting EFI partition"}
{"type":"substep","message":"Pulling container image"}
{"type":"complete","message":"Installation complete!"}
```

Steps: partition disk → format EFI + /boot → LUKS setup (optional) → format root → mount → `bootc install to-filesystem` (podman) → copy Flatpaks → write hostname → finalize.

**Critical design constraints:**
- Always **3-partition GPT** (EFI + ext4 `/boot` + root), even for unencrypted installs. The separate ext4 `/boot` is required because GRUB cannot read modern XFS features (`nrext64`, `exchange`, `rmapbt`), and `bootupctl` inside its bwrap sandbox needs to find `/boot` UUID from a raw block device.
- Scratch space is `/var/fisherman-tmp` (disk-backed, bind-mounted to `/var/tmp`). Do NOT change to `/run/*` — `/run` is tmpfs and too small for large image blobs.
- `--skip-finalize` is passed to bootc so step 9 can manually finalize (fstrim → remount ro → fsfreeze/thaw), because `bootc install finalize` is a no-op upstream.

### tuna-installer (Python, `tuna_installer/`)
GTK4/Adwaita GUI that collects user choices, writes a recipe JSON, then launches fisherman via a VTE terminal widget and parses its JSON progress output.

**Flatpak sandbox constraints:**
- fisherman is staged to `~/.cache/tuna-installer/fisherman` by `_stage_fisherman_on_host()` in `progress.py` (host-visible via `--filesystem=host`).
- fisherman runs on the **host** via `flatpak-spawn --host pkexec <path>`.
- Reboot must use `flatpak-spawn --host systemctl reboot` (see `done.py`).

**Recipe JSON fields:** `disk`, `filesystem` (`xfs`/`btrfs`), `btrfsSubvolumes`, `encryption` (type + passphrase), `image`, `targetImgref`, `selinuxDisabled`, `hostname`, `flatpaks[]`.
Encryption types: `none`, `luks-passphrase`, `tpm2-luks`, `tpm2-luks-passphrase`.

## fisherman submodule workflow

fisherman (`fisherman/`) is a separate git repo (`tuna-os/fisherman`). Changes there must be committed and pushed **separately**, then the parent repo's submodule pointer updated:

```bash
# 1. Commit in submodule
cd fisherman/fisherman && git add -A && git commit -m "..." && git push

# 2. Update pointer in parent repo
cd /var/home/james/dev/tuna-installer
git add fisherman && git commit -m "chore: update fisherman submodule (...)" && git push
```

CI checks out submodules recursively — always verify CI passes after both pushes.

## Image catalog

`data/images.json` is a recursive JSON tree of distro groups/leaves. Distros can override it at `/etc/tuna-installer/images.json` (system) or `$XDG_CONFIG_HOME/tuna-installer/images.json` (user).

## Known issues

- **UI freeze during blob download**: `__on_vte_contents_changed` in `progress.py` scrapes the entire VTE buffer on every character change. Fix in progress: switch to tailing the log file with `GLib.io_add_watch`.
- **TPM2 enrolment failure**: `systemd-cryptenroll --unlock-key-file=-` fails with "Reading keyfile /var/roothome/- failed". Non-fatal; password fallback works.

## Useful diagnostic commands (on install target)

```bash
tail -f ~/.cache/tuna-installer/fisherman-output.log
ls -lt ~/.cache/tuna-installer/tuna-recipe-*.json | head -1 | xargs cat
sudo lsblk -o NAME,SIZE,FSTYPE,LABEL,UUID /dev/nvme0n1
```
