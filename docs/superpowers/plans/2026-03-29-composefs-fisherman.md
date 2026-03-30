# Composefs-Native Backend Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fisherman support composefs-native bootc images by adding `--composefs-backend` flag support and dual-path post-install hostname writing, then add CI regression tests against ghcr.io/bootcrew images.

**Architecture:** Add `ComposeFsBackend bool` to the recipe; extract `buildBootcArgs` as a pure function so it's unit-testable; detect the deployed backend by checking whether `$TARGET/ostree/` exists post-install; branch `WriteHostname` accordingly. Two new GitHub Actions workflows share a single YAML matrix file.

**Tech Stack:** Go 1.22 (stdlib only), Bash (fake bins), GitHub Actions, YAML (`tests/bootcrew-matrix.yaml`), yq + jq (CI matrix parsing).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `fisherman/fisherman/internal/recipe/recipe.go` | Modify | Add `ComposeFsBackend bool` field |
| `fisherman/fisherman/internal/recipe/recipe_test.go` | Modify | Add composeFsBackend test cases |
| `fisherman/fisherman/internal/install/bootc.go` | Modify | Add `ComposeFsBackend` to `Options`; extract `buildBootcArgs`; pass `--composefs-backend` |
| `fisherman/fisherman/internal/install/bootc_test.go` | Create | Test `buildBootcArgs` for all flag combinations |
| `fisherman/fisherman/internal/post/post.go` | Modify | Add `isComposeFsNative`; add `deploymentDirFn` var; update `WriteHostname` |
| `fisherman/fisherman/internal/post/post_test.go` | Create | Test `WriteHostname` for both backends |
| `fisherman/fisherman/cmd/fisherman/main.go` | Modify | Wire `r.ComposeFsBackend` into `install.Options` |
| `tests/bootcrew-matrix.yaml` | Create | Image matrix (single source of truth for both workflows) |
| `tests/fake-bins/podman` | Create | Fake podman for PR disk-ops test |
| `tests/fake-bins/ostree` | Create | Fake ostree for PR disk-ops test |
| `.github/workflows/bootcrew-fast.yml` | Create | PR gate: disk ops with fake podman/ostree |
| `.github/workflows/bootcrew-nightly.yml` | Create | Weekly full install against bootcrew images |

---

### Task 1: Add `ComposeFsBackend` to recipe + tests

**Files:**
- Modify: `fisherman/fisherman/internal/recipe/recipe.go`
- Modify: `fisherman/fisherman/internal/recipe/recipe_test.go`

- [ ] **Step 1: Add the field to the Recipe struct**

In `fisherman/fisherman/internal/recipe/recipe.go`, add after the `UnifiedStorage` field:

```go
// ComposeFsBackend passes --composefs-backend to bootc install to-filesystem.
// Required for composefs-native images (e.g. ghcr.io/bootcrew/*).
// Independent of UnifiedStorage — these are different bootc features.
ComposeFsBackend bool `json:"composeFsBackend"`
```

The full struct becomes:
```go
type Recipe struct {
	Disk            string     `json:"disk"`
	Filesystem      string     `json:"filesystem"`
	BtrfsSubvolumes bool       `json:"btrfsSubvolumes"`
	Encryption      Encryption `json:"encryption"`
	Image           string     `json:"image"`
	TargetImgref    string     `json:"targetImgref"`
	SelinuxDisabled bool       `json:"selinuxDisabled"`
	UnifiedStorage  bool       `json:"unifiedStorage"`
	ComposeFsBackend bool      `json:"composeFsBackend"`
	Hostname        string     `json:"hostname"`
	Flatpaks        []string   `json:"flatpaks"`
}
```

- [ ] **Step 2: Add test cases to recipe_test.go**

In `fisherman/fisherman/internal/recipe/recipe_test.go`, add these cases to the `tests` slice in `TestValidate`, after the `"valid tpm2-luks-passphrase"` case:

```go
{
    name: "valid composefs_backend true",
    r:    recipe.Recipe{Disk: diskPath, Filesystem: "xfs", Hostname: "h", ComposeFsBackend: true},
},
{
    name: "valid composefs_backend with luks-passphrase",
    r: recipe.Recipe{
        Disk: diskPath, Filesystem: "xfs", Hostname: "h",
        ComposeFsBackend: true,
        Encryption:       recipe.Encryption{Type: "luks-passphrase", Passphrase: "secret"},
    },
},
{
    name: "valid composefs_backend with btrfs",
    r:    recipe.Recipe{Disk: diskPath, Filesystem: "btrfs", Hostname: "h", ComposeFsBackend: true},
},
```

- [ ] **Step 3: Run tests**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go test -v -count=1 ./internal/recipe/...
```

Expected: all tests pass including the 3 new cases.

- [ ] **Step 4: Commit**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
git add internal/recipe/recipe.go internal/recipe/recipe_test.go
git commit -m "feat: add ComposeFsBackend field to recipe"
```

---

### Task 2: Extract `buildBootcArgs` + add `ComposeFsBackend` to Options

**Files:**
- Modify: `fisherman/fisherman/internal/install/bootc.go`
- Create: `fisherman/fisherman/internal/install/bootc_test.go`

- [ ] **Step 1: Write the failing tests first**

Create `fisherman/fisherman/internal/install/bootc_test.go`:

```go
package install_test

import (
	"testing"

	"github.com/tuna-os/fisherman/internal/install"
)

func TestBuildBootcArgs_BaseArgs(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{Target: "/mnt/target"}, "", "/target")
	// Must always include these
	assertContains(t, args, "install")
	assertContains(t, args, "to-filesystem")
	assertContains(t, args, "--skip-finalize")
	assertContains(t, args, "/target")
}

func TestBuildBootcArgs_ComposeFsBackend(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{ComposeFsBackend: true}, "", "/target")
	assertContains(t, args, "--composefs-backend")
}

func TestBuildBootcArgs_NoComposeFsBackend(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{ComposeFsBackend: false}, "", "/target")
	assertAbsent(t, args, "--composefs-backend")
}

func TestBuildBootcArgs_UnifiedStorage(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{UnifiedStorage: true}, "", "/target")
	assertContains(t, args, "--experimental-unified-storage")
}

func TestBuildBootcArgs_NoUnifiedStorage(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{UnifiedStorage: false}, "", "/target")
	assertAbsent(t, args, "--experimental-unified-storage")
}

func TestBuildBootcArgs_SelinuxDisabled(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{SelinuxDisabled: true}, "", "/target")
	assertContains(t, args, "--disable-selinux")
}

func TestBuildBootcArgs_NoSelinux(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{SelinuxDisabled: false}, "", "/target")
	assertAbsent(t, args, "--disable-selinux")
}

func TestBuildBootcArgs_TargetImgref(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{}, "ghcr.io/tuna-os/yellowfin:gnome50", "/target")
	assertContains(t, args, "--target-imgref")
	assertContains(t, args, "ghcr.io/tuna-os/yellowfin:gnome50")
}

func TestBuildBootcArgs_NoTargetImgref(t *testing.T) {
	args := install.BuildBootcArgs(install.Options{}, "", "/target")
	assertAbsent(t, args, "--target-imgref")
}

func TestBuildBootcArgs_AllFlags(t *testing.T) {
	opts := install.Options{
		ComposeFsBackend: true,
		UnifiedStorage:   true,
		SelinuxDisabled:  true,
	}
	args := install.BuildBootcArgs(opts, "img:tag", "/target")
	assertContains(t, args, "--composefs-backend")
	assertContains(t, args, "--experimental-unified-storage")
	assertContains(t, args, "--disable-selinux")
	assertContains(t, args, "--target-imgref")
}

// assertContains fails the test if s is not present in slice.
func assertContains(t *testing.T, slice []string, s string) {
	t.Helper()
	for _, v := range slice {
		if v == s {
			return
		}
	}
	t.Errorf("expected %q in args %v", s, slice)
}

// assertAbsent fails the test if s is present in slice.
func assertAbsent(t *testing.T, slice []string, s string) {
	t.Helper()
	for _, v := range slice {
		if v == s {
			t.Errorf("unexpected %q in args %v", s, slice)
			return
		}
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go test -v -count=1 ./internal/install/...
```

Expected: FAIL — `install.BuildBootcArgs undefined`.

- [ ] **Step 3: Add `ComposeFsBackend` to Options and extract `BuildBootcArgs`**

In `fisherman/fisherman/internal/install/bootc.go`:

Add `ComposeFsBackend bool` to the `Options` struct after `UnifiedStorage`:
```go
// ComposeFsBackend passes --composefs-backend when true.
// Required for images using the composefs-native deployment backend (e.g. ghcr.io/bootcrew/*).
ComposeFsBackend bool
```

Add the exported `BuildBootcArgs` function (add after the `Options` struct, before `BootcInstall`):
```go
// BuildBootcArgs builds the argument slice for `bootc install to-filesystem`.
// resolvedTargetImgref is the --target-imgref value (empty to omit the flag).
// installTarget is the final positional argument (e.g. "/target" in container mode,
// or opts.Target in direct mode).
func BuildBootcArgs(opts Options, resolvedTargetImgref, installTarget string) []string {
	args := []string{"install", "to-filesystem"}
	if resolvedTargetImgref != "" {
		args = append(args, "--target-imgref", resolvedTargetImgref)
	}
	if opts.SelinuxDisabled {
		args = append(args, "--disable-selinux")
	}
	if opts.UnifiedStorage {
		args = append(args, "--experimental-unified-storage")
	}
	if opts.ComposeFsBackend {
		args = append(args, "--composefs-backend")
	}
	args = append(args, "--skip-finalize")
	args = append(args, installTarget)
	return args
}
```

- [ ] **Step 4: Replace inline arg-building in `bootcViaContainer`**

Replace the block in `bootcViaContainer` (lines 62-73) that builds `bootcArgs`:

Old:
```go
bootcArgs := []string{"install", "to-filesystem"}
if targetImgref != "" {
    bootcArgs = append(bootcArgs, "--target-imgref", targetImgref)
}
if opts.SelinuxDisabled {
    bootcArgs = append(bootcArgs, "--disable-selinux")
}
if opts.UnifiedStorage {
    bootcArgs = append(bootcArgs, "--experimental-unified-storage")
}
bootcArgs = append(bootcArgs, "--skip-finalize")
bootcArgs = append(bootcArgs, "/target")
```

New (one line):
```go
bootcArgs := BuildBootcArgs(opts, targetImgref, "/target")
```

- [ ] **Step 5: Replace inline arg-building in `bootcDirect`**

Replace the block in `bootcDirect` (lines 104-115) that builds `args`:

Old:
```go
args := []string{"install", "to-filesystem"}
if opts.TargetImgref != "" {
    args = append(args, "--target-imgref", opts.TargetImgref)
}
if opts.SelinuxDisabled {
    args = append(args, "--disable-selinux")
}
if opts.UnifiedStorage {
    args = append(args, "--experimental-unified-storage")
}
args = append(args, "--skip-finalize")
args = append(args, opts.Target)
```

New (one line):
```go
args := BuildBootcArgs(opts, opts.TargetImgref, opts.Target)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go test -v -count=1 ./internal/install/...
```

Expected: all 9 tests pass.

- [ ] **Step 7: Run full test suite to confirm no regressions**

```bash
go test -count=1 ./...
```

Expected: all packages pass.

- [ ] **Step 8: Commit**

```bash
git add internal/install/bootc.go internal/install/bootc_test.go
git commit -m "feat: extract BuildBootcArgs, add ComposeFsBackend flag support"
```

---

### Task 3: Wire `ComposeFsBackend` through `main.go`

**Files:**
- Modify: `fisherman/fisherman/cmd/fisherman/main.go`

- [ ] **Step 1: Add `ComposeFsBackend` to the `install.Options` call**

In `fisherman/fisherman/cmd/fisherman/main.go`, find the `install.BootcInstall` call (around line 189) and add the new field:

Old:
```go
if err := install.BootcInstall(install.Options{
    SourceImgref:    r.Image,
    TargetImgref:    targetImgref,
    SelinuxDisabled: r.SelinuxDisabled,
    UnifiedStorage:  r.UnifiedStorage,
    Target:          targetMount,
}); err != nil {
```

New:
```go
if err := install.BootcInstall(install.Options{
    SourceImgref:     r.Image,
    TargetImgref:     targetImgref,
    SelinuxDisabled:  r.SelinuxDisabled,
    UnifiedStorage:   r.UnifiedStorage,
    ComposeFsBackend: r.ComposeFsBackend,
    Target:           targetMount,
}); err != nil {
```

- [ ] **Step 2: Build to verify compilation**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go build ./cmd/fisherman/
```

Expected: compiles with no errors.

- [ ] **Step 3: Run full test suite**

```bash
go test -count=1 ./...
```

Expected: all packages pass.

- [ ] **Step 4: Commit**

```bash
git add cmd/fisherman/main.go
git commit -m "feat: wire ComposeFsBackend through main.go to bootc install"
```

---

### Task 4: Add `isComposeFsNative`, `deploymentDirFn`, update `WriteHostname` + tests

**Files:**
- Modify: `fisherman/fisherman/internal/post/post.go`
- Create: `fisherman/fisherman/internal/post/post_test.go`

- [ ] **Step 1: Write the failing tests first**

Create `fisherman/fisherman/internal/post/post_test.go`:

```go
package post_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/tuna-os/fisherman/internal/post"
	"github.com/tuna-os/fisherman/internal/runner"
)

// setupRecorder, recorder, execCall are defined in cleanup_test.go (same package)

// TestWriteHostname_ComposeFsNative verifies that when no /ostree/ directory
// exists under the target (composefs-native deployment), hostname is written
// directly to $TARGET/etc/hostname.
func TestWriteHostname_ComposeFsNative(t *testing.T) {
	// No runner interception needed — this path uses os.WriteFile, not exec.
	target := t.TempDir()
	// Deliberately do NOT create target/ostree/ — that's what makes it composefs-native.

	if err := post.WriteHostname(target, "myhost"); err != nil {
		t.Fatalf("WriteHostname: %v", err)
	}

	hostnameFile := filepath.Join(target, "etc", "hostname")
	data, err := os.ReadFile(hostnameFile)
	if err != nil {
		t.Fatalf("reading hostname file: %v", err)
	}
	if string(data) != "myhost\n" {
		t.Errorf("hostname file content = %q, want %q", string(data), "myhost\n")
	}
}

// TestWriteHostname_ComposeFsNative_CreatesEtcDir verifies that /etc is created
// if it doesn't already exist (composefs-native path).
func TestWriteHostname_ComposeFsNative_CreatesEtcDir(t *testing.T) {
	target := t.TempDir()
	// No ostree dir, no etc dir — both should be created.
	if err := post.WriteHostname(target, "tunaos"); err != nil {
		t.Fatalf("WriteHostname: %v", err)
	}
	if _, err := os.Stat(filepath.Join(target, "etc", "hostname")); err != nil {
		t.Errorf("hostname file not created: %v", err)
	}
}

// TestWriteHostname_OstreeBackend verifies that when /ostree/ exists under the
// target (ostree-based deployment), hostname is written to the path returned by
// deploymentDirFn, not to $TARGET/etc/hostname directly.
func TestWriteHostname_OstreeBackend(t *testing.T) {
	target := t.TempDir()

	// Create the ostree directory to trigger the ostree code path.
	if err := os.MkdirAll(filepath.Join(target, "ostree"), 0o755); err != nil {
		t.Fatal(err)
	}

	// Create a fake deploy dir that deploymentDirFn will return.
	fakeDeployDir := filepath.Join(target, "ostree", "deploy", "default", "deploy", "abc123.0")
	if err := os.MkdirAll(fakeDeployDir, 0o755); err != nil {
		t.Fatal(err)
	}

	// Stub deploymentDirFn to return our fake deploy dir.
	post.DeploymentDirFn = func(sysroot string) (string, error) {
		return fakeDeployDir, nil
	}
	t.Cleanup(func() { post.DeploymentDirFn = post.DefaultDeploymentDir })

	// Also need runner for the ostree exec — but DeploymentDirFn bypasses exec.
	rec := setupRecorder(t)
	_ = rec // no exec calls expected in this path

	if err := post.WriteHostname(target, "tunahost"); err != nil {
		t.Fatalf("WriteHostname: %v", err)
	}

	// Hostname must be in the deploy dir's etc/, NOT in target/etc/.
	hostnameInDeploy := filepath.Join(fakeDeployDir, "etc", "hostname")
	data, err := os.ReadFile(hostnameInDeploy)
	if err != nil {
		t.Fatalf("reading hostname from deploy dir: %v", err)
	}
	if string(data) != "tunahost\n" {
		t.Errorf("hostname = %q, want %q", string(data), "tunahost\n")
	}

	// The direct target/etc/hostname must NOT exist.
	if _, err := os.Stat(filepath.Join(target, "etc", "hostname")); err == nil {
		t.Error("hostname should NOT be written to target/etc/hostname for ostree deployments")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go test -v -count=1 ./internal/post/...
```

Expected: FAIL — `post.DeploymentDirFn undefined`, `post.DefaultDeploymentDir undefined`.

- [ ] **Step 3: Add `isComposeFsNative`, `deploymentDirFn`, and update `WriteHostname` in post.go**

In `fisherman/fisherman/internal/post/post.go`, make these changes:

**3a.** Replace the existing `deploymentDir` function and `WriteHostname` function with:

```go
// DefaultDeploymentDir returns the ostree deployment directory inside sysroot
// using `ostree admin --sysroot=<sysroot> --print-current-dir`.
func DefaultDeploymentDir(sysroot string) (string, error) {
	out, err := exec.Command("ostree", "admin", "--sysroot="+sysroot, "--print-current-dir").Output()
	if err != nil {
		return "", fmt.Errorf("ostree admin --print-current-dir: %w", err)
	}
	path := strings.TrimSpace(string(out))
	if path == "" {
		return "", fmt.Errorf("ostree admin --print-current-dir returned empty path")
	}
	return path, nil
}

// DeploymentDirFn is called by WriteHostname to locate the ostree deployment
// directory. Tests replace this with a stub; restore with post.DefaultDeploymentDir.
var DeploymentDirFn = DefaultDeploymentDir

// isComposeFsNative reports whether the installed system at sysroot uses the
// composefs-native backend. Composefs-native deployments have no /ostree/
// directory; ostree-based deployments always create one.
func isComposeFsNative(sysroot string) bool {
	_, err := os.Stat(filepath.Join(sysroot, "ostree"))
	return os.IsNotExist(err)
}

// WriteHostname writes /etc/hostname into the installed system at target.
// For ostree-based deployments the hostname goes into the ostree deployment
// subtree (found via DeploymentDirFn). For composefs-native deployments it goes
// directly at $TARGET/etc/hostname.
func WriteHostname(target, hostname string) error {
	var etcDir string
	if isComposeFsNative(target) {
		etcDir = filepath.Join(target, "etc")
	} else {
		deployDir, err := DeploymentDirFn(target)
		if err != nil {
			return fmt.Errorf("finding deployment dir: %w", err)
		}
		etcDir = filepath.Join(deployDir, "etc")
	}
	if err := os.MkdirAll(etcDir, 0o755); err != nil {
		return fmt.Errorf("mkdir %s: %w", etcDir, err)
	}
	hostnameFile := filepath.Join(etcDir, "hostname")
	if err := os.WriteFile(hostnameFile, []byte(hostname+"\n"), 0o644); err != nil {
		return fmt.Errorf("write %s: %w", hostnameFile, err)
	}
	fmt.Fprintf(os.Stdout, "  wrote hostname %q to %s\n", hostname, hostnameFile)
	return nil
}
```

> **Note:** The old unexported `deploymentDir` function is removed; its logic moves into `DefaultDeploymentDir`. The `DeploymentDirFn` variable replaces all internal calls to `deploymentDir`.

- [ ] **Step 4: Run the tests**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
go test -v -count=1 ./internal/post/...
```

Expected: all post tests pass (cleanup tests + new WriteHostname tests).

- [ ] **Step 5: Run full test suite**

```bash
go test -count=1 ./...
```

Expected: all packages pass.

- [ ] **Step 6: Commit**

```bash
git add internal/post/post.go internal/post/post_test.go
git commit -m "feat: add composefs-native WriteHostname path + DeploymentDirFn"
```

---

### Task 5: Update the parent repo (submodule pointer + go-test workflow)

**Files:**
- `fisherman/` (submodule pointer in parent repo)
- `.github/workflows/go-test.yml` (already exists — verify submodule is fetched)

- [ ] **Step 1: Push fisherman changes**

```bash
cd /var/home/james/dev/tuna-installer/fisherman/fisherman
git push
```

- [ ] **Step 2: Update submodule pointer in parent repo**

```bash
cd /var/home/james/dev/tuna-installer
git add fisherman
git commit -m "chore: update fisherman submodule (composefs-native backend support)"
```

- [ ] **Step 3: Verify go-test.yml fetches submodules**

Read `.github/workflows/go-test.yml` and confirm the checkout step has `submodules: recursive`. It already does from the previous session — no change needed.

---

### Task 6: Create the image matrix and fake bins

**Files:**
- Create: `tests/bootcrew-matrix.yaml`
- Create: `tests/fake-bins/podman`
- Create: `tests/fake-bins/ostree`

- [ ] **Step 1: Create the image matrix**

Create `tests/bootcrew-matrix.yaml`:

```yaml
# Bootcrew CI regression test matrix.
# Used by both bootcrew-fast.yml (PR gate) and bootcrew-nightly.yml (full install).
# Add new images here; both workflows pick them up automatically.
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
    selinux_disabled: false

  - name: gnomeos-bootc
    image: ghcr.io/bootcrew/gnomeos-bootc:latest
    filesystem: xfs
    composefs_backend: true
    unified_storage: false
    selinux_disabled: false

  - name: opensuse-bootc
    image: ghcr.io/bootcrew/opensuse-bootc:latest
    filesystem: xfs
    composefs_backend: true
    unified_storage: false
    selinux_disabled: false
```

- [ ] **Step 2: Create fake podman**

```bash
mkdir -p /var/home/james/dev/tuna-installer/tests/fake-bins
```

Create `tests/fake-bins/podman`:

```bash
#!/usr/bin/env bash
# Fake podman for fisherman's fast disk-ops CI test.
# Used when FISHERMAN_FAKE_BINS=1 is set to avoid real container pulls.
#
# Parses the --mount type=bind,src=<TARGET>,... arg to find the bind-mount
# target, then creates the minimal post-bootc directory structure so fisherman's
# post-install steps (WriteHostname, CopyFlatpaks) can proceed.

set -euo pipefail

TARGET=""
COMPOSEFS=false

for arg in "$@"; do
    # Extract src= from --mount type=bind,src=<PATH>,dst=/target,...
    if [[ "$arg" == type=bind,src=* ]]; then
        TARGET=$(printf '%s' "$arg" | sed 's/type=bind,src=\([^,]*\).*/\1/')
    fi
    if [[ "$arg" == "--composefs-backend" ]]; then
        COMPOSEFS=true
    fi
done

# Fall back to env var if mount arg parsing failed (e.g. bootcDirect path).
if [[ -z "$TARGET" ]]; then
    TARGET="${FISHERMAN_TARGET:-}"
fi

if [[ -z "$TARGET" ]]; then
    echo "fake-podman: could not determine target directory" >&2
    exit 1
fi

if [[ "$COMPOSEFS" == "true" ]]; then
    # Composefs-native layout: /etc directly in sysroot.
    mkdir -p "$TARGET/etc"
    mkdir -p "$TARGET/boot/loader/entries"
    printf '[Match]\nName=eth0\n' > "$TARGET/etc/hostname"  # placeholder, overwritten by fisherman
else
    # Ostree layout: deployment subtree.
    DEPLOY="$TARGET/ostree/deploy/default/deploy/fake123.0"
    mkdir -p "$DEPLOY/etc"
    mkdir -p "$TARGET/boot/loader/entries"
    mkdir -p "$TARGET/boot/grub2"
    echo "fake grub cfg" > "$TARGET/boot/grub2/grub.cfg"
fi

exit 0
```

- [ ] **Step 3: Create fake ostree**

Create `tests/fake-bins/ostree`:

```bash
#!/usr/bin/env bash
# Fake ostree for fisherman's fast disk-ops CI test.
# Responds to: ostree admin --sysroot=<PATH> --print-current-dir
# Returns the fake deployment directory created by fake podman.

set -euo pipefail

SYSROOT=""
for arg in "$@"; do
    if [[ "$arg" == --sysroot=* ]]; then
        SYSROOT="${arg#--sysroot=}"
    fi
done

if [[ -n "$SYSROOT" ]]; then
    echo "$SYSROOT/ostree/deploy/default/deploy/fake123.0"
    exit 0
fi

# Pass through any other ostree subcommands (shouldn't happen in tests).
echo "fake-ostree: unhandled args: $*" >&2
exit 1
```

- [ ] **Step 4: Make the fake bins executable**

```bash
chmod +x /var/home/james/dev/tuna-installer/tests/fake-bins/podman
chmod +x /var/home/james/dev/tuna-installer/tests/fake-bins/ostree
```

- [ ] **Step 5: Commit**

```bash
cd /var/home/james/dev/tuna-installer
git add tests/bootcrew-matrix.yaml tests/fake-bins/
git commit -m "test: add bootcrew image matrix and fake podman/ostree bins"
```

---

### Task 7: Create `bootcrew-fast.yml` (PR disk-ops gate)

**Files:**
- Create: `.github/workflows/bootcrew-fast.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/bootcrew-fast.yml`:

```yaml
name: Bootcrew Fast (disk ops)

on:
  pull_request:
    branches: [main]

jobs:
  # Read the image matrix from tests/bootcrew-matrix.yaml and output JSON.
  setup:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.read-matrix.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Parse image matrix
        id: read-matrix
        run: |
          # yq and jq are pre-installed on ubuntu-latest
          MATRIX=$(yq -o json tests/bootcrew-matrix.yaml | jq -c '.images')
          echo "matrix=$MATRIX" >> "$GITHUB_OUTPUT"

  disk-ops:
    name: disk-ops / ${{ matrix.image.name }}
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        image: ${{ fromJson(needs.setup.outputs.matrix) }}

    defaults:
      run:
        working-directory: fisherman/fisherman

    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
          cache: true
          cache-dependency-path: fisherman/fisherman/go.sum

      - name: Install disk tools
        run: sudo apt-get install -y xfsprogs btrfs-progs cryptsetup-bin

      - name: Build fisherman
        run: go build -o /tmp/fisherman ./cmd/fisherman/

      - name: Add fake bins to PATH
        working-directory: ${{ github.workspace }}
        run: |
          chmod +x tests/fake-bins/podman tests/fake-bins/ostree
          echo "${{ github.workspace }}/tests/fake-bins" >> "$GITHUB_PATH"

      - name: Create loop device
        id: loopdev
        run: |
          TMPFILE=$(mktemp)
          truncate -s 20G "$TMPFILE"
          LOOPDEV=$(sudo losetup --find --show "$TMPFILE")
          echo "loopdev=$LOOPDEV" >> "$GITHUB_OUTPUT"
          echo "tmpfile=$TMPFILE" >> "$GITHUB_OUTPUT"

      - name: Generate recipe
        run: |
          cat > /tmp/recipe.json <<EOF
          {
            "disk": "${{ steps.loopdev.outputs.loopdev }}",
            "filesystem": "${{ matrix.image.filesystem }}",
            "composeFsBackend": ${{ matrix.image.composefs_backend }},
            "unifiedStorage": ${{ matrix.image.unified_storage }},
            "selinuxDisabled": ${{ matrix.image.selinux_disabled }},
            "encryption": {"type": "none"},
            "image": "${{ matrix.image.image }}",
            "hostname": "ci-test",
            "flatpaks": []
          }
          EOF

      - name: Run fisherman (fake podman/ostree)
        run: |
          sudo FISHERMAN_TARGET=/mnt/fisherman-target /tmp/fisherman /tmp/recipe.json

      - name: Verify partition layout
        run: |
          LOOPDEV="${{ steps.loopdev.outputs.loopdev }}"
          # Expect exactly 3 partitions: EFI-SYSTEM, boot, root
          LABEL_COUNT=$(sudo lsblk -o LABEL "$LOOPDEV" | grep -cE 'EFI-SYSTEM|boot|root' || true)
          if [ "$LABEL_COUNT" -ne 3 ]; then
            echo "ERROR: expected 3 labelled partitions, got $LABEL_COUNT"
            sudo lsblk -o NAME,SIZE,FSTYPE,LABEL "$LOOPDEV"
            exit 1
          fi
          echo "OK: 3 partitions found"

      - name: Cleanup
        if: always()
        run: |
          sudo losetup -d "${{ steps.loopdev.outputs.loopdev }}" || true
          rm -f "${{ steps.loopdev.outputs.tmpfile }}" || true
```

- [ ] **Step 2: Commit**

```bash
cd /var/home/james/dev/tuna-installer
git add .github/workflows/bootcrew-fast.yml
git commit -m "ci: add bootcrew-fast PR disk-ops gate"
```

---

### Task 8: Create `bootcrew-nightly.yml` (full install)

**Files:**
- Create: `.github/workflows/bootcrew-nightly.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/bootcrew-nightly.yml`:

```yaml
name: Bootcrew Nightly (full install)

on:
  schedule:
    - cron: '0 2 * * 1'   # Weekly, Monday 02:00 UTC
  workflow_dispatch:        # Manual trigger

jobs:
  # Read the image matrix from tests/bootcrew-matrix.yaml.
  setup:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.read-matrix.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Parse image matrix
        id: read-matrix
        run: |
          MATRIX=$(yq -o json tests/bootcrew-matrix.yaml | jq -c '.images')
          echo "matrix=$MATRIX" >> "$GITHUB_OUTPUT"

  full-install:
    name: install / ${{ matrix.image.name }}
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false          # All images run even if one fails
      matrix:
        image: ${{ fromJson(needs.setup.outputs.matrix) }}

    defaults:
      run:
        working-directory: fisherman/fisherman

    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
          cache: true
          cache-dependency-path: fisherman/fisherman/go.sum

      - name: Install tools
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y podman xfsprogs btrfs-progs cryptsetup-bin ostree

      - name: Build fisherman
        run: go build -o /tmp/fisherman ./cmd/fisherman/

      - name: Create loop device (50 GB sparse)
        id: loopdev
        run: |
          TMPFILE=$(mktemp)
          truncate -s 50G "$TMPFILE"
          LOOPDEV=$(sudo losetup --find --show "$TMPFILE")
          echo "loopdev=$LOOPDEV" >> "$GITHUB_OUTPUT"
          echo "tmpfile=$TMPFILE" >> "$GITHUB_OUTPUT"

      - name: Generate recipe
        run: |
          cat > /tmp/recipe.json <<EOF
          {
            "disk": "${{ steps.loopdev.outputs.loopdev }}",
            "filesystem": "${{ matrix.image.filesystem }}",
            "composeFsBackend": ${{ matrix.image.composefs_backend }},
            "unifiedStorage": ${{ matrix.image.unified_storage }},
            "selinuxDisabled": ${{ matrix.image.selinux_disabled }},
            "encryption": {"type": "none"},
            "image": "${{ matrix.image.image }}",
            "hostname": "ci-test",
            "flatpaks": []
          }
          EOF

      - name: Run fisherman
        run: sudo /tmp/fisherman /tmp/recipe.json

      - name: Verify installation
        run: |
          LOOPDEV="${{ steps.loopdev.outputs.loopdev }}"
          COMPOSEFS="${{ matrix.image.composefs_backend }}"

          # 1. Check 3-partition layout.
          LABEL_COUNT=$(sudo lsblk -o LABEL "$LOOPDEV" | grep -cE 'EFI-SYSTEM|boot|root' || true)
          if [ "$LABEL_COUNT" -ne 3 ]; then
            echo "FAIL: expected 3 labelled partitions, got $LABEL_COUNT"
            sudo lsblk -o NAME,SIZE,FSTYPE,LABEL "$LOOPDEV"
            exit 1
          fi

          # 2. Mount /boot partition (p2) and verify boot layout.
          BOOT_PART="${LOOPDEV}p2"
          VERIFY_DIR=$(mktemp -d)
          sudo mount "$BOOT_PART" "$VERIFY_DIR"

          if [ "$COMPOSEFS" = "true" ]; then
            # Composefs-native: verify hostname in sysroot /etc.
            ROOT_PART="${LOOPDEV}p3"
            ROOT_DIR=$(mktemp -d)
            sudo mount "$ROOT_PART" "$ROOT_DIR"
            if [ ! -f "$ROOT_DIR/etc/hostname" ]; then
              echo "FAIL: $ROOT_DIR/etc/hostname not found (composefs-native)"
              sudo umount "$ROOT_DIR" || true
              sudo umount "$VERIFY_DIR" || true
              exit 1
            fi
            echo "OK: composefs-native hostname at $ROOT_DIR/etc/hostname"
            sudo umount "$ROOT_DIR"
          else
            # Ostree: verify boot loader entries exist.
            if ! ls "$VERIFY_DIR/loader/entries/"*.conf 1>/dev/null 2>&1; then
              echo "FAIL: no boot loader entries in $VERIFY_DIR/loader/entries/"
              sudo umount "$VERIFY_DIR" || true
              exit 1
            fi
            echo "OK: ostree boot loader entries found"
          fi

          sudo umount "$VERIFY_DIR"
          echo "PASS: ${{ matrix.image.name }}"

      - name: Cleanup
        if: always()
        run: |
          sudo losetup -d "${{ steps.loopdev.outputs.loopdev }}" || true
          rm -f "${{ steps.loopdev.outputs.tmpfile }}" || true

      - name: Report result to job summary
        if: always()
        run: |
          STATUS="${{ job.status }}"
          IMAGE="${{ matrix.image.name }}"
          echo "| $IMAGE | $STATUS |" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Commit**

```bash
cd /var/home/james/dev/tuna-installer
git add .github/workflows/bootcrew-nightly.yml
git commit -m "ci: add bootcrew-nightly weekly full install workflow"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `ComposeFsBackend bool` in recipe | Task 1 |
| `--composefs-backend` flag passed to bootc | Task 2 |
| `buildBootcArgs` extracted as pure function | Task 2 |
| Wire through `main.go` | Task 3 |
| `isComposeFsNative` detection | Task 4 |
| `deploymentDirFn` variable | Task 4 |
| `WriteHostname` dual-path | Task 4 |
| `TestWriteHostname_ComposeFsNative` | Task 4 |
| `TestWriteHostname_OstreeBackend` | Task 4 |
| `TestBuildBootcArgs_*` suite | Task 2 |
| `tests/bootcrew-matrix.yaml` | Task 6 |
| `tests/fake-bins/podman` | Task 6 |
| `tests/fake-bins/ostree` | Task 6 |
| `bootcrew-fast.yml` | Task 7 |
| `bootcrew-nightly.yml` | Task 8 |

**All spec requirements covered. No gaps.**

**Placeholder scan:** No TBDs, no "implement later", all code blocks complete.

**Type consistency:**
- `BuildBootcArgs` exported in Task 2, referenced in Tasks 2 and 3 — consistent.
- `DeploymentDirFn` / `DefaultDeploymentDir` defined in Task 4, referenced in Task 4 test — consistent.
- `install.Options.ComposeFsBackend` added in Task 2, used in Task 3 — consistent.
- `recipe.Recipe.ComposeFsBackend` added in Task 1, used in Task 3 — consistent.
- `post.WriteHostname` signature unchanged — consistent with existing callers in `main.go`.
