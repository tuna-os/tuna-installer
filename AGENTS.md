# AGENTS.md — AI Agent Guide for tuna-installer

This document describes the architecture, dev workflow, and key commands needed
to work on this project as an AI agent. Read it before making changes.

---

## Repository layout

```
tuna-installer/               ← this repo (tuna-os/tuna-installer)
├── tuna_installer/           ← Python GTK4/Adwaita GUI (the Flatpak app)
│   └── views/
│       ├── progress.py       ← VTE terminal, fisherman launcher, progress JSON parser
│       ├── done.py           ← final screen (reboot / log viewer)
│       └── confirm.py        ← confirmation screen before install
├── fisherman/                ← git submodule → tuna-os/fisherman (Go backend)
│   └── fisherman/
│       ├── cmd/fisherman/main.go          ← install pipeline (steps 1-9)
│       └── internal/
│           ├── disk/         ← partition, format, mount, finalize
│           ├── luks/         ← LUKS format, open, TPM2 enrol
│           ├── install/      ← bootc install to-filesystem (podman run)
│           ├── post/         ← hostname, flatpak copy, cleanup/unmount
│           ├── progress/     ← JSON-line progress emitter
│           ├── recipe/       ← recipe.go schema + Validate()
│           └── runner/       ← Run() helper (exec + set-x logging)
├── flatpak/
│   └── org.tunaos.Installer.json   ← Flatpak manifest (GNOME 50 runtime)
├── data/                     ← GSchema, desktop file, icons
├── po/                       ← translations
└── .github/workflows/flatpak.yml   ← CI: builds + publishes "continuous" pre-release
```

---

## Two-component architecture

### fisherman (Go, submodule)

fisherman is a root-level CLI that reads a JSON recipe and executes the full
disk install pipeline. It emits newline-delimited JSON progress to stdout:

```json
{"type":"step","step":2,"total_steps":9,"step_name":"Formatting EFI partition"}
{"type":"substep","message":"Pulling container image"}
{"type":"info","message":"Writing hostname: tunaos"}
{"type":"complete","message":"Installation complete!"}
```

**Install pipeline (main.go):**

| Step | Action |
|------|--------|
| 1 | Partition disk (`sgdisk` via `disk.Partition` / `disk.PartitionEncrypted`) |
| 2 | Format EFI (`mkfs.fat -F32`) and optionally /boot (`mkfs.ext4`) |
| 3 | Set up LUKS (optional: `cryptsetup luksFormat` + `luksOpen`) |
| 4 | Format root filesystem (`mkfs.xfs` or `mkfs.btrfs`) |
| 5 | Mount everything at `/mnt/fisherman-target` |
| 6 | `bootc install to-filesystem` via `podman run --privileged` |
| 7 | Copy system Flatpaks (`/var/lib/flatpak` → target) |
| 8 | Write `/etc/hostname` into the ostree deployment |
| 9 | Finalize: fstrim → remount ro → fsfreeze/thaw |

**Key design decisions:**
- `--skip-finalize` is passed to bootc so the target stays writable for step 8.
  Step 9 manually replicates `bootc`'s internal `finalize_filesystem()`.
- Scratch space for bootc blob downloads is `/var/fisherman-tmp` (disk-backed),
  bind-mounted to `/var/tmp` on the host. Do NOT change this to `/run/*` —
  `/run` is a tmpfs (~50% RAM) and too small for large images.
- Partition layout: always **3-partition** (EFI + `/boot` ext4 + root). The
  separate ext4 `/boot` is required for two reasons: (1) GRUB's built-in XFS
  driver cannot read el10 XFS features (`nrext64`, `exchange`, `rmapbt`), so
  GRUB must only ever read ext4; (2) for encrypted installs, `bootupctl` (inside
  its bwrap sandbox) must be able to find the `/boot` UUID from a raw block
  device rather than a LUKS mapper. Both `Partition()` and
  `PartitionEncrypted()` produce the same 3-partition GPT table; the difference
  is that encrypted installs additionally set up LUKS on p3.

### tuna-installer (Python, GTK4/Adwaita)

The GUI collects user choices and writes a recipe JSON, then launches fisherman
via a VTE terminal.

**Flatpak sandbox constraints:**
- fisherman is staged to `~/.cache/tuna-installer/fisherman` (host-visible via
  `--filesystem=host`) by `_stage_fisherman_on_host()` in `progress.py`.
- fisherman runs on the **host** via `flatpak-spawn --host pkexec <path>`.
- `systemctl reboot` must be called as `flatpak-spawn --host systemctl reboot`
  from inside the sandbox (see `done.py`).
- The installer log is written to `~/.cache/tuna-installer/fisherman-output.log`.

**Recipe JSON written by the GUI:**

```json
{
  "disk": "/dev/nvme0n1",
  "filesystem": "xfs",
  "btrfsSubvolumes": false,
  "encryption": {
    "type": "tpm2-luks-passphrase",
    "passphrase": "hunter2"
  },
  "image": "ghcr.io/tuna-os/yellowfin:gnome50",
  "targetImgref": "ghcr.io/tuna-os/yellowfin:gnome50",
  "selinuxDisabled": true,
  "hostname": "tunaos",
  "flatpaks": ["org.mozilla.firefox", "..."]
}
```

Encryption types: `"none"`, `"luks-passphrase"`, `"tpm2-luks"`, `"tpm2-luks-passphrase"`.

---

## Development workflow

### Making changes to fisherman

fisherman lives at `fisherman/` and is a **git submodule** pointing to
`github.com/tuna-os/fisherman`. You must commit and push changes there
**separately** before updating the parent repo's submodule pointer.

```bash
# 1. Edit files inside fisherman/fisherman/
cd fisherman/fisherman
# ... make changes ...
go build ./cmd/fisherman/   # quick compile check
go vet ./...                # lint

# 2. Commit + push fisherman
git add -A && git commit -m "fix: describe the change"
git push

# 3. Update the submodule pointer in the parent repo
cd /var/home/james/dev/tuna-installer
git add fisherman
git commit -m "chore: update fisherman submodule (describe the change)"
git push
```

### Making changes to the Python GUI

```bash
cd /var/home/james/dev/tuna-installer
# edit tuna_installer/views/*.py or other files
git add -A && git commit -m "fix: describe the change"
git push
```

### Building and deploying the Flatpak locally

```bash
cd /var/home/james/dev/tuna-installer

# Build and install locally (takes ~10 min first time; cached after)
flatpak run org.flatpak.Builder \
  --force-clean --user --install \
  _build flatpak/org.tunaos.Installer.json

# Bundle for deployment to a remote machine
flatpak build-bundle \
  ~/.local/share/flatpak/repo \
  org.tunaos.Installer.flatpak \
  org.tunaos.Installer

# Deploy to a remote machine (e.g. 192.168.0.119)
scp org.tunaos.Installer.flatpak james@192.168.0.119:~
ssh james@192.168.0.119 \
  "flatpak uninstall --user -y org.tunaos.Installer; \
   flatpak install --user --bundle -y ~/org.tunaos.Installer.flatpak"
```

### Running the installer (on a live machine)

```bash
flatpak run org.tunaos.Installer
# Or with a local fisherman binary (dev/test):
TUNA_FISHERMAN_PATH=/path/to/fisherman flatpak run org.tunaos.Installer
```

### Invoking fisherman directly (for testing)

```bash
# Build fisherman
cd fisherman/fisherman
go build -o /tmp/fisherman ./cmd/fisherman/

# Run with a recipe (as root — fisherman needs root for disk ops)
sudo /tmp/fisherman /path/to/recipe.json

# Watch the log on a remote machine
ssh james@192.168.0.119 "tail -f ~/.cache/tuna-installer/fisherman-output.log"
```

---

## CI / releases

- **Every push to `main`** triggers `.github/workflows/flatpak.yml` which builds
  the Flatpak and publishes it as the `continuous` pre-release on GitHub.
- **Tagged pushes** (`v*`) publish a named release.
- Container: `ghcr.io/flathub-infra/flatpak-github-actions:gnome-50`
- The submodule is checked out recursively by CI (`submodules: recursive`).

Always verify CI passes after pushing both submodule + parent repo commits.

---

## Key files to know

| File | Purpose |
|------|---------|
| `fisherman/fisherman/cmd/fisherman/main.go` | Install pipeline, step ordering, totalSteps |
| `fisherman/fisherman/internal/disk/format.go` | `FinalizeFilesystem`, `FormatBoot`, `MountEFI`, `BindMount` |
| `fisherman/fisherman/internal/disk/partition.go` | `Partition` (2-part), `PartitionEncrypted` (3-part) |
| `fisherman/fisherman/internal/luks/luks.go` | LUKS format, open, close, `EnrollTPM2` |
| `fisherman/fisherman/internal/install/install.go` | `BootcInstall` → podman command |
| `fisherman/fisherman/internal/post/post.go` | `WriteHostname`, `CopyFlatpaks`, `Cleanup` |
| `fisherman/fisherman/internal/recipe/recipe.go` | Recipe struct, `Validate()` |
| `tuna_installer/views/progress.py` | VTE terminal, fisherman launch, JSON progress parsing |
| `tuna_installer/views/done.py` | Final screen, reboot button, log viewer |
| `flatpak/org.tunaos.Installer.json` | Flatpak manifest (runtime, finish-args, Go version) |
| `.github/workflows/flatpak.yml` | CI build + publish workflow |

---

## Known issues / in-progress work

- **UI freeze during blob download**: `__on_vte_contents_changed` in `progress.py`
  scrapes the entire VTE text buffer on every character change. When bootc fires
  60+ blob copy lines per second, the GTK main loop starves. Fix: switch to tailing
  the log file directly with `GLib.io_add_watch`.
- **TPM2 enrolment failure**: `systemd-cryptenroll --unlock-key-file=-` fails with
  "Reading keyfile /var/roothome/- failed". Non-fatal (password fallback works).
- **`bootc install finalize` is a no-op upstream**: We replicate the real finalization
  ops in `disk.FinalizeFilesystem()` ourselves (fstrim, remount ro, fsfreeze/thaw).
- **Set BootNext on Reboot**: The "Reboot Now" button should temporarily set the 
  boot drive to the newly installed drive for the next boot (via `efibootmgr --bootnext`). 
  This ensures the system doesn't reboot back into the installer if the installation 
  media is still plugged in.

---

## Useful diagnostic commands (on a remote install target)

```bash
# Watch the live install log
tail -f ~/.cache/tuna-installer/fisherman-output.log

# Check the most recent recipe used
ls -lt ~/.cache/tuna-installer/tuna-recipe-*.json | head -1 | xargs cat

# Inspect the installed disk after install (replace nvme0n1 with actual disk)
sudo lsblk -o NAME,SIZE,FSTYPE,LABEL,UUID /dev/nvme0n1
sudo mount /dev/nvme0n1p2 /tmp/ir && sudo mount /dev/nvme0n1p1 /tmp/ie
cat /tmp/ir/boot/grub2/grub.cfg
cat /tmp/ie/EFI/almalinux/bootuuid.cfg
ls /tmp/ir/boot/loader/entries/
sudo umount /tmp/ie /tmp/ir

# Check EFI boot entries
efibootmgr

# Check bootupd state on installed root
sudo mount /dev/nvme0n1p2 /tmp/ir
cat /tmp/ir/boot/bootupd-state.json
sudo umount /tmp/ir
```

## Future Architectural Considerations

- **Move `images.json` to `fisherman` (Done)**: The image registry (`fisherman/data/images.json`) now lives in the `fisherman` backend. This allows `fisherman` to act as a universal registry of BootC images, containing not just the OCI references but also the specific installation requirements for each image (e.g., whether it requires manual user creation, specific kernel arguments, or filesystem defaults).
- **Universal BootC Registry**: Evolving the image manifest into a standard format that other installers or tools could consume to understand the "metadata" of a BootC image.
- **Dynamic Installation Carousel**: The `images.json` should eventually include a `carousel` property for each image or group, allowing for distribution-specific slideshows during the installation process, with support for inheritance and `/etc` overrides.

---

## GitHub org context

- **`tuna-os/tuna-installer`** — this repo (GUI + submodule)
- **`tuna-os/fisherman`** — Go backend (submodule at `fisherman/`)
- **`tuna-os/github-copr`** — COPR definitions for c10s-gnome COPRs used in the image
- Images are published to `ghcr.io/tuna-os/` (e.g. `yellowfin:gnome50`, `yellowfin:gnome-hwe`)
