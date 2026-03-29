# Boot Verification for Bootcrew Nightly CI

**Date:** 2026-03-30
**Status:** Approved

---

## Context

The `bootcrew-nightly.yml` workflow installs each matrix image onto a loop device and verifies the resulting partition structure and file layout. It does not verify that the installed system actually boots. A broken GRUB config, corrupt initrd, or bad EFI entry would pass the current checks.

This spec adds a QEMU+OVMF boot step after the existing install verification. It boots the loop device as a full VM and waits for a login prompt on the serial console. Failure to reach a login prompt within the timeout fails the matrix job.

---

## Scope

One deliverable: modify `.github/workflows/bootcrew-nightly.yml` to add boot verification after the existing install verification step.

No new files. No changes to fisherman Go code. No changes to `bootcrew-fast.yml` (that workflow uses fake podman and produces no bootable system).

---

## Design

### Tools

Add `qemu-system-x86 ovmf` to the existing `sudo apt-get install -y` line in the "Install tools" step:

```bash
sudo apt-get install -y podman xfsprogs btrfs-progs cryptsetup-bin ostree qemu-system-x86 ovmf
```

`qemu-system-x86` provides `qemu-system-x86_64`. `ovmf` provides `/usr/share/OVMF/OVMF_CODE.fd`.

### Boot command

```bash
timeout 180 qemu-system-x86_64 \
  -enable-kvm \
  -m 2G \
  -drive file=$LOOPDEV,format=raw,if=virtio \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
  -serial stdio \
  -nographic \
  -no-reboot 2>&1 | tee /tmp/boot-$IMAGE_NAME.log
```

- `-enable-kvm`: uses hardware virtualisation available on `ubuntu-latest` runners (`/dev/kvm`). Without this, boot would be prohibitively slow.
- `-m 2G`: sufficient RAM for all matrix images to reach login.
- `-drive file=$LOOPDEV,format=raw,if=virtio`: attaches the installed loop device as a virtio block device. virtio is faster than IDE and is supported by all matrix images.
- `-drive if=pflash,...,file=OVMF_CODE.fd`: UEFI firmware. Required because the installed system's bootloader is an EFI application.
- `-serial stdio -nographic`: all serial output goes to stdout, captured by `tee`.
- `-no-reboot`: VM halts instead of rebooting on shutdown (prevents infinite boot loops on panic).
- `timeout 180`: kills QEMU after 3 minutes if login prompt has not appeared.

### Success detection

```bash
grep -q "login:" /tmp/boot-$IMAGE_NAME.log
```

`login:` appears in the getty prompt on all major Linux distributions (`ubuntu-bootc`, `gnomeos-bootc`, `opensuse-bootc`, `yellowfin`). If the grep succeeds, the step passes. If `timeout` fires or the grep finds no match, the step exits non-zero and fails the matrix job.

### SELinux

The boot test boots whatever was installed. No kernel command-line overrides are applied. The existing matrix entry `selinux_disabled: true` for `yellowfin-gnome50` only affects the `bootc install` flags; it does not affect how the installed system boots.

### Timeout

180 seconds. Expected boot times with KVM:
- `yellowfin-gnome50` (ostree/XFS): ~60s
- `ubuntu-bootc` (composefs-native): ~90s
- `gnomeos-bootc` (composefs-native): ~90s
- `opensuse-bootc` (composefs-native): ~90s

180s gives ~2× headroom for runner variance.

### Failure behaviour

Boot failure fails the matrix job. `fail-fast: false` is already set on the matrix, so other images continue running. The job summary step (already present) reports per-image pass/fail.

---

## Files modified

| File | Change |
|------|--------|
| `.github/workflows/bootcrew-nightly.yml` | Add `qemu-system-x86 ovmf` to apt install; add "Boot verification" step after "Verify installation" |

---

## Verification

After implementation, trigger the workflow manually:

```bash
gh workflow run bootcrew-nightly.yml
```

Check that each matrix job shows a "Boot verification" step and that the log contains `login:`.
