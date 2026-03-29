# Boot Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a QEMU+OVMF boot verification step to `bootcrew-nightly.yml` that boots each installed image and fails the matrix job if a login prompt does not appear within 180 seconds.

**Architecture:** Two edits to `.github/workflows/bootcrew-nightly.yml`: add `qemu-system-x86 ovmf` to the apt install line, and insert a "Boot verification" step between "Verify installation" and "Cleanup". The step boots the loop device with KVM acceleration, tees serial output to a log file, and greps for `login:`.

**Tech Stack:** GitHub Actions, QEMU (`qemu-system-x86_64`), OVMF UEFI firmware, Bash.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `.github/workflows/bootcrew-nightly.yml` | Modify | Add QEMU tools to apt install; add boot verification step |

---

### Task 1: Add QEMU tools to the apt install line and boot verification step

**Files:**
- Modify: `.github/workflows/bootcrew-nightly.yml`

This is a CI-only change. There is no unit-testable Go code involved. The verification is done by triggering the workflow manually after the edit.

- [ ] **Step 1: Add `qemu-system-x86 ovmf` to the apt install line**

In `.github/workflows/bootcrew-nightly.yml`, find the "Install tools" step (line 50–52) and extend the apt install line:

Old:
```yaml
      - name: Install tools
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y podman xfsprogs btrfs-progs cryptsetup-bin ostree
```

New:
```yaml
      - name: Install tools
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y podman xfsprogs btrfs-progs cryptsetup-bin ostree qemu-system-x86 ovmf
```

- [ ] **Step 2: Insert the "Boot verification" step**

Insert the following step between the "Verify installation" step (ends at line 127) and the "Cleanup" step (starts at line 129). The `working-directory` default is `fisherman/fisherman`, so use `working-directory: ${{ github.workspace }}` to run from the repo root where the loop device path is accessible.

```yaml
      - name: Boot verification
        working-directory: ${{ github.workspace }}
        run: |
          LOOPDEV="${{ steps.loopdev.outputs.loopdev }}"
          IMAGE_NAME="${{ matrix.image.name }}"
          LOG="/tmp/boot-${IMAGE_NAME}.log"

          echo "Booting $IMAGE_NAME with QEMU+OVMF (timeout 180s)..."
          sudo timeout 180 qemu-system-x86_64 \
            -enable-kvm \
            -m 2G \
            -drive file="$LOOPDEV",format=raw,if=virtio \
            -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
            -serial stdio \
            -nographic \
            -no-reboot 2>&1 | tee "$LOG" || true

          if grep -q "login:" "$LOG"; then
            echo "PASS: login prompt found for $IMAGE_NAME"
          else
            echo "FAIL: no login prompt found for $IMAGE_NAME"
            echo "--- last 50 lines of boot log ---"
            tail -50 "$LOG"
            exit 1
          fi
```

> **Why `|| true` after the pipe:** `timeout` exits with code 124 when it fires, and QEMU may exit non-zero on `-no-reboot`. We capture the output first and let the `grep` decide pass/fail, so we suppress the QEMU exit code. The `exit 1` inside the `if` block propagates failure correctly.

> **Why `sudo` on QEMU:** The loop device is owned by root (created with `sudo losetup`), so QEMU needs root to open it directly.

- [ ] **Step 3: Verify the full workflow file looks correct**

Read `.github/workflows/bootcrew-nightly.yml` and confirm:
- The apt line now includes `qemu-system-x86 ovmf`
- The "Boot verification" step appears between "Verify installation" and "Cleanup"
- The "Cleanup" step still has `if: always()` so it runs even when boot verification fails

- [ ] **Step 4: Commit**

```bash
cd /var/home/james/dev/tuna-installer
git add .github/workflows/bootcrew-nightly.yml
git commit -m "ci: add QEMU+OVMF boot verification to bootcrew-nightly"
```

- [ ] **Step 5: Push and trigger the workflow**

```bash
git push
gh workflow run bootcrew-nightly.yml
```

Then watch the run:
```bash
gh run watch
```

Expected: each matrix job shows a "Boot verification" step. For a passing image the step log ends with `PASS: login prompt found for <name>`. For a failing image it prints the last 50 lines of the boot log and exits non-zero.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|-----------------|------|
| Add `qemu-system-x86 ovmf` to apt install | Task 1 Step 1 |
| Boot loop device with `-enable-kvm -m 2G -drive virtio -pflash OVMF` | Task 1 Step 2 |
| `-serial stdio -nographic -no-reboot` | Task 1 Step 2 |
| `timeout 180` | Task 1 Step 2 |
| `grep -q "login:"` for success detection | Task 1 Step 2 |
| Failure exits non-zero (fails matrix job) | Task 1 Step 2 (`exit 1`) |
| `fail-fast: false` already set — other images continue | already in workflow |

**All spec requirements covered.**

**Placeholder scan:** None found.

**Consistency:** `LOOPDEV` is sourced from `steps.loopdev.outputs.loopdev`, consistent with how the existing "Verify installation" and "Cleanup" steps reference it.
