# Composefs-Native Backend Support + Bootcrew CI Regression Tests

**Date:** 2026-03-29
**Status:** Approved

---

## Context

Fisherman currently assumes every bootc installation uses the **ostree backend**. Post-install steps (`WriteHostname`) call `ostree admin --print-current-dir` to locate the deployment directory. This fails completely for composefs-native images.

`bootc install to-filesystem` gained a `--composefs-backend` flag that selects the composefs-native backend instead of ostree. Images from `ghcr.io/bootcrew` (ubuntu-bootc, gnomeos-bootc, opensuse-bootc, arch-bootc) use this backend. They produce a completely different filesystem layout: no `/ostree/deploy/` hierarchy; `/etc/hostname` lives directly at `$TARGET/etc/hostname`.

Without this work, fisherman cannot install any composefs-native image. With this work, fisherman supports the full spectrum of bootc images and a CI regression matrix validates that support is maintained.

---

## Scope

This spec covers two tightly coupled deliverables:

1. **fisherman composefs-native support** — recipe field, bootc flag, post-install detection, hostname writing
2. **CI regression matrix** — nightly full installs + fast PR disk-ops test against bootcrew images

---

## Design

### 1. Recipe change

Add one field to `internal/recipe/recipe.go`:

```go
ComposeFsBackend bool `json:"composeFsBackend"` // pass --composefs-backend to bootc
```

**Validation**: no constraint (both false and true are valid regardless of filesystem type).

**Relationship to `UnifiedStorage`**: These are independent flags. `UnifiedStorage` (`--experimental-unified-storage`) and `ComposeFsBackend` (`--composefs-backend`) address different bootc features and can be set independently.

---

### 2. `internal/install/bootc.go` — pass `--composefs-backend`

Add `ComposeFsBackend bool` to the `Options` struct (mirrors `UnifiedStorage`). When true, append `--composefs-backend` to the bootc args.

```go
if opts.ComposeFsBackend {
    bootcArgs = append(bootcArgs, "--composefs-backend")
}
```

This applies to both `bootcViaContainer` and `bootcDirect` paths.

---

### 3. `internal/post/post.go` — backend detection + dual hostname path

**Detection function** (new, unexported):

```go
// isComposeFsNative reports whether the installed system at sysroot uses the
// composefs-native backend. Composefs-native deployments have no /ostree/
// directory; ostree-based deployments always create it.
func isComposeFsNative(sysroot string) bool {
    _, err := os.Stat(filepath.Join(sysroot, "ostree"))
    return os.IsNotExist(err)
}
```

**`WriteHostname` updated**:

```go
func WriteHostname(target, hostname string) error {
    var etcDir string
    if isComposeFsNative(target) {
        // composefs-native: /etc is directly in the target sysroot
        etcDir = filepath.Join(target, "etc")
    } else {
        // ostree-based: /etc is inside the ostree deployment subtree
        deployDir, err := deploymentDir(target)
        if err != nil {
            return fmt.Errorf("finding deployment dir: %w", err)
        }
        etcDir = filepath.Join(deployDir, "etc")
    }
    if err := os.MkdirAll(etcDir, 0o755); err != nil {
        return fmt.Errorf("mkdir %s: %w", etcDir, err)
    }
    return os.WriteFile(
        filepath.Join(etcDir, "hostname"),
        []byte(hostname+"\n"),
        0o644,
    )
}
```

**`CopyFlatpaks`**: Destination remains `$TARGET/var/lib/flatpak` for both backends. Composefs-native images have `/var` directly in the sysroot, same path depth. If CI reveals this is wrong for composefs-native images, it will be a separate fix.

---

### 4. `main.go` — wire up `ComposeFsBackend`

Pass `r.ComposeFsBackend` through to `install.BootcInstall(install.Options{..., ComposeFsBackend: r.ComposeFsBackend})`.

---

### 5. New unit tests

**`internal/recipe/recipe_test.go`** — add cases:
- `composeFsBackend: true` with `filesystem: xfs` — valid
- `composeFsBackend: true` with encryption — valid

**`internal/post/post_test.go`** (new file, supplement cleanup_test.go):
- `TestWriteHostname_ComposeFsNative`: creates a temp dir with no `ostree/` subdirectory; calls `WriteHostname`; asserts hostname written to `$TARGET/etc/hostname`. This tests the new code path without any runner/ostree dependency.
- `TestWriteHostname_OstreeBackend`: creates a temp dir with an `ostree/` subdirectory; asserts the ostree code path is taken. To make this testable, `deploymentDir` is converted to a package-level variable `var deploymentDirFn = deploymentDir` (same pattern as `runner.RunFn`), which the test replaces with a function that returns a known temp path.

**`internal/install/bootc.go`** — extract `buildBootcArgs(opts Options) []string` as a pure function that assembles the bootc argument slice. This decouples arg-building logic from subprocess execution.

**`internal/install/bootc_test.go`** (new file):
- `TestBuildBootcArgs_ComposeFsBackend`: calls `buildBootcArgs(Options{ComposeFsBackend: true, Target: "/t"})` and asserts `--composefs-backend` is present.
- `TestBuildBootcArgs_NoComposeFsBackend`: asserts `--composefs-backend` is absent when `ComposeFsBackend: false`.
- `TestBuildBootcArgs_UnifiedStorage`: asserts `--experimental-unified-storage` appears when set.
- `TestBuildBootcArgs_SelinuxDisabled`: asserts `--disable-selinux` appears when set.

---

### 6. CI regression matrix

**`tests/bootcrew-matrix.yaml`** — single source of truth for both workflows:

```yaml
images:
  - name: yellowfin-gnome50
    image: ghcr.io/tuna-os/yellowfin:gnome50
    filesystem: xfs
    composefs_backend: false
    unified_storage: false
    selinux_disabled: true

  - name: ubuntu-bootc
    image: ghcr.io/bootcrew/ubuntu-bootc:latest
    filesystem: xfs
    composefs_backend: true
    unified_storage: false

  - name: gnomeos-bootc
    image: ghcr.io/bootcrew/gnomeos-bootc:latest
    filesystem: xfs
    composefs_backend: true
    unified_storage: false

  - name: opensuse-bootc
    image: ghcr.io/bootcrew/opensuse-bootc:latest
    filesystem: xfs
    composefs_backend: true
    unified_storage: false
```

---

### 7. `.github/workflows/bootcrew-fast.yml` — PR disk-ops gate

Runs on every PR. No image pulls. Tests that fisherman's disk ops complete successfully for each matrix entry.

**Mechanism**: A fake `podman` script in `tests/fake-bins/podman` that:
1. Scans its `$@` for the `--mount` argument and extracts `src=<value>` using `sed` to find the bind-mounted target path. This is more robust than line-by-line iteration. If the mount arg cannot be parsed (e.g. `bootcDirect` path), falls back to `FISHERMAN_TARGET` env var.
2. Creates the minimal directory structure fisherman expects post-bootc. Which layout to create is inferred by checking whether `--composefs-backend` appears in `$@`:
   - With `--composefs-backend`: `$TARGET/etc/`, `$TARGET/boot/loader/entries/`
   - Without: `$TARGET/ostree/deploy/default/deploy/test123.0/etc/`, `$TARGET/boot/loader/entries/`
3. Exits 0

**Setup in workflow**:
```yaml
- name: Add fake bins to PATH
  run: |
    chmod +x tests/fake-bins/podman
    echo "$PWD/tests/fake-bins" >> $GITHUB_PATH
```

**Verification**: After fisherman completes, assert partition count and labels:
```bash
lsblk -o NAME,LABEL /dev/loopN | grep -c "EFI-SYSTEM\|boot\|root" | grep -q 3
```

**Runtime**: ~30s per matrix entry.

---

### 8. `.github/workflows/bootcrew-nightly.yml` — full install schedule

Runs weekly (`schedule: cron: '0 2 * * 1'`) and on `workflow_dispatch`.

**Runner**: `ubuntu-latest` (has root access, losetup, sfdisk available).

**Setup**:
```bash
sudo apt-get install -y podman xfsprogs btrfs-progs cryptsetup-bin
```

**Per-image steps**:
1. Build fisherman: `go build -o /tmp/fisherman ./cmd/fisherman/`
2. Create loop device: `losetup --find --show -f $(dd if=/dev/zero of=$TMPFILE bs=1M count=50000 && echo $TMPFILE)`
3. Generate recipe JSON from matrix entry
4. Run: `sudo /tmp/fisherman /tmp/recipe.json`
5. Verify:
   - `lsblk` shows 3 partitions on loop device
   - `sudo mount /dev/loopNp2 /tmp/verify`
   - Check `ls /tmp/verify/boot/loader/entries/*.conf` exists (ostree) OR `/tmp/verify/etc/hostname` exists (composefs-native)
   - Unmount and detach loop device
6. Report pass/fail to job summary

**Failure behavior**: Individual image failures do not cancel other matrix entries (`continue-on-error: true` per matrix job). The job summary shows which images passed and which failed.

---

## Files modified

| File | Change |
|------|--------|
| `fisherman/fisherman/internal/recipe/recipe.go` | Add `ComposeFsBackend bool` field |
| `fisherman/fisherman/internal/install/bootc.go` | Add `ComposeFsBackend` to Options; pass `--composefs-backend` |
| `fisherman/fisherman/internal/post/post.go` | Add `isComposeFsNative`; update `WriteHostname` |
| `fisherman/fisherman/cmd/fisherman/main.go` | Wire `r.ComposeFsBackend` to install options |
| `fisherman/fisherman/internal/recipe/recipe_test.go` | Add composeFsBackend test cases |
| `fisherman/fisherman/internal/post/post_test.go` | New: `TestWriteHostname_*` |
| `fisherman/fisherman/internal/install/bootc_test.go` | New: `TestOptions_ComposeFsBackend` |
| `tests/bootcrew-matrix.yaml` | New: image matrix definition |
| `tests/fake-bins/podman` | New: fake podman for fast PR test |
| `.github/workflows/bootcrew-fast.yml` | New: PR disk-ops gate |
| `.github/workflows/bootcrew-nightly.yml` | New: weekly full install |

---

## Verification

After implementation:

```bash
# Unit tests
cd fisherman/fisherman && go test -v -count=1 ./...

# Race detector
go test -race -count=1 ./...

# Manual test of fast workflow (locally)
bash tests/test_bootcrew_disk.sh

# Nightly workflow (trigger manually)
gh workflow run bootcrew-nightly.yml
```

CI: both new workflows appear in GitHub Actions; fast test runs on PR; nightly runs on schedule and can be triggered manually with `workflow_dispatch`.
