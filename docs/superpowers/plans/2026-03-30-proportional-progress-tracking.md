# Proportional Progress Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fisherman's progress bar proportional to actual install time, fix skopeo layer tracking, and add a pre-flight image cache check.

**Architecture:** fisherman emits `weight_pct`/`cumulative_pct` on every step event — computed from empirical timing profiles chosen based on whether the image is already cached. The Python GUI reads `cumulative_pct` directly for bar position instead of `step/total_steps`.

**Tech Stack:** Go 1.22 (fisherman), Python/GTK4 (GUI), skopeo, podman/bootc

---

## File Map

| File | Change |
|------|--------|
| `fisherman/fisherman/internal/progress/progress.go` | Add `weight_pct`/`cumulative_pct` to `stepEvent`; update `Step()` signature |
| `fisherman/fisherman/internal/progress/progress_test.go` | Update `Step` call sites; add weight field assertions |
| `fisherman/fisherman/internal/install/bootc.go` | Add `CheckImage()`; add `skopeoInspectFn` var; add `LayerCount`/`NeedsPull` to `Options`; remove `getLayerCount()`; fix blob counting; add `classifyLine` pattern |
| `fisherman/fisherman/internal/install/bootc_test.go` | Add tests for `CheckImage`, `ClassifyLine` "layers needed" pattern |
| `fisherman/fisherman/cmd/fisherman/main.go` | Fix `totalSteps` (9→8); add `step++` after configure; add `buildProfile()`; call `CheckImage` pre-flight; pass weights to all `progress.Step()` calls |
| `tuna_installer/views/progress.py` | Use `cumulative_pct / 100.0` for bar fraction |

---

## Task 1: Fix step counter bug in main.go

**Files:**
- Modify: `fisherman/fisherman/cmd/fisherman/main.go`

The base install has 8 steps, not 9. Also `step++` is missing after "Configuring installed system", causing both it and "Finalizing installation" to emit `step: 7`.

- [ ] **Step 1: Fix totalSteps and add missing step++**

In `fisherman/fisherman/cmd/fisherman/main.go`, make two edits:

Change line `totalSteps := 9` to:
```go
totalSteps := 8
```

After the `progress.Step(step, totalSteps, "Configuring installed system")` call (around line 225), add:
```go
step++
```

So that block becomes:
```go
// ── Step 8: Post-install configuration ───────────────────────────────────────
progress.Step(step, totalSteps, "Configuring installed system")
step++

progress.Info(fmt.Sprintf("Writing hostname: %s", r.Hostname))
if err := post.WriteHostname(targetMount, r.Hostname); err != nil {
    fatal("writing hostname: %v", err)
}

// ── Step 9: Finalize ─────────────────────────────────────────────────────
progress.Step(step, totalSteps, "Finalizing installation")
```

- [ ] **Step 2: Verify it compiles**

```bash
cd fisherman/fisherman && go build ./... && go vet ./...
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd fisherman/fisherman
git add cmd/fisherman/main.go
git commit -m "fix: correct totalSteps (9→8) and missing step++ after configure"
```

---

## Task 2: Add weight_pct/cumulative_pct to progress.Step()

**Files:**
- Modify: `fisherman/fisherman/internal/progress/progress.go`
- Modify: `fisherman/fisherman/internal/progress/progress_test.go`
- Modify: `fisherman/fisherman/cmd/fisherman/main.go` (all callers)

- [ ] **Step 1: Update stepEvent and Step() in progress.go**

Replace the existing `stepEvent` struct and `Step()` function:

```go
type stepEvent struct {
	Type          string `json:"type"`
	Step          int    `json:"step"`
	TotalSteps    int    `json:"total_steps"`
	StepName      string `json:"step_name"`
	WeightPct     int    `json:"weight_pct"`
	CumulativePct int    `json:"cumulative_pct"`
}

// Step emits a JSON step-progress line to stdout.
// cumulativePct is the bar position (0–100) at the start of this step.
// weightPct is the estimated share of total install time this step occupies.
func Step(step, total int, name string, cumulativePct, weightPct int) {
	write(stepEvent{
		Type:          "step",
		Step:          step,
		TotalSteps:    total,
		StepName:      name,
		WeightPct:     weightPct,
		CumulativePct: cumulativePct,
	})
}
```

- [ ] **Step 2: Update progress_test.go**

Replace the `TestStep` function and the `TestOutputIsNewlineTerminated` Step entry:

```go
func TestStep(t *testing.T) {
	out := captureStdout(t, func() {
		progress.Step(2, 8, "Formatting EFI partition", 0, 1)
	})

	var event map[string]interface{}
	if err := json.Unmarshal([]byte(out[:len(out)-1]), &event); err != nil {
		t.Fatalf("invalid JSON: %v\noutput: %q", err, out)
	}

	if event["type"] != "step" {
		t.Errorf("type = %v, want step", event["type"])
	}
	if event["step"] != float64(2) {
		t.Errorf("step = %v, want 2", event["step"])
	}
	if event["total_steps"] != float64(8) {
		t.Errorf("total_steps = %v, want 8", event["total_steps"])
	}
	if event["step_name"] != "Formatting EFI partition" {
		t.Errorf("step_name = %v, want 'Formatting EFI partition'", event["step_name"])
	}
	if event["weight_pct"] != float64(1) {
		t.Errorf("weight_pct = %v, want 1", event["weight_pct"])
	}
	if event["cumulative_pct"] != float64(0) {
		t.Errorf("cumulative_pct = %v, want 0", event["cumulative_pct"])
	}
}
```

Also update the `TestOutputIsNewlineTerminated` Step entry:
```go
{"Step", func() { progress.Step(1, 8, "x", 0, 0) }},
```

- [ ] **Step 3: Update all main.go callers with (0, 0) placeholders**

Every `progress.Step(step, totalSteps, "...")` call in `cmd/fisherman/main.go` gets two trailing zeroes added. These will be replaced with real values in Task 6. Find all calls and update them:

```go
progress.Step(step, totalSteps, "Partitioning disk", 0, 0)
// ... (repeat for every progress.Step call in main.go)
```

There are ~9 calls total (8 base + 1 conditional LUKS + 1 conditional TPM2). Update all of them.

- [ ] **Step 4: Run tests**

```bash
cd fisherman/fisherman && go test ./internal/progress/... -v
```

Expected: all tests PASS including `TestStep`, `TestOutputIsNewlineTerminated`.

- [ ] **Step 5: Verify full build**

```bash
cd fisherman/fisherman && go build ./... && go vet ./...
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd fisherman/fisherman
git add internal/progress/progress.go internal/progress/progress_test.go cmd/fisherman/main.go
git commit -m "feat: add weight_pct/cumulative_pct to step progress events"
```

---

## Task 3: Add CheckImage() and replace getLayerCount()

**Files:**
- Modify: `fisherman/fisherman/internal/install/bootc.go`
- Modify: `fisherman/fisherman/internal/install/bootc_test.go`

`CheckImage` determines whether a pull is needed and how many layers the image has, by comparing remote and local digests via `skopeo inspect`.

- [ ] **Step 1: Write failing tests for CheckImage**

Add to `fisherman/fisherman/internal/install/bootc_test.go`:

```go
import (
	"testing"

	"github.com/tuna-os/fisherman/internal/install"
)

func TestCheckImage_NeedsPullWhenNotCached(t *testing.T) {
	// Remote has digest A, local inspect fails (not present).
	install.SkopeoInspectFn = func(args ...string) ([]byte, error) {
		// First call: remote inspect (docker://...) → return manifest with digest+layers
		if len(args) > 0 && args[len(args)-1][:9] == "docker://" {
			return []byte(`{"Digest":"sha256:aaaa","Layers":["sha256:l1","sha256:l2"]}`), nil
		}
		// Second call: local inspect (containers-storage:...) → not found
		return nil, fmt.Errorf("image not known")
	}
	defer func() { install.SkopeoInspectFn = install.DefaultSkopeoInspect }()

	result := install.CheckImage("ghcr.io/tuna-os/yellowfin:gnome-hwe")
	if !result.NeedsPull {
		t.Error("NeedsPull should be true when image not in local storage")
	}
	if result.LayerCount != 2 {
		t.Errorf("LayerCount = %d, want 2", result.LayerCount)
	}
}

func TestCheckImage_NoPullWhenCachedAndCurrent(t *testing.T) {
	install.SkopeoInspectFn = func(args ...string) ([]byte, error) {
		// Both remote and local return same digest.
		return []byte(`{"Digest":"sha256:bbbb","Layers":["sha256:l1","sha256:l2","sha256:l3"]}`), nil
	}
	defer func() { install.SkopeoInspectFn = install.DefaultSkopeoInspect }()

	result := install.CheckImage("ghcr.io/tuna-os/yellowfin:gnome-hwe")
	if result.NeedsPull {
		t.Error("NeedsPull should be false when local digest matches remote")
	}
	if result.LayerCount != 3 {
		t.Errorf("LayerCount = %d, want 3", result.LayerCount)
	}
}

func TestCheckImage_NeedsPullWhenDigestDiffers(t *testing.T) {
	call := 0
	install.SkopeoInspectFn = func(args ...string) ([]byte, error) {
		call++
		if call == 1 {
			return []byte(`{"Digest":"sha256:remote","Layers":["sha256:l1"]}`), nil
		}
		return []byte(`{"Digest":"sha256:stale","Layers":["sha256:l1"]}`), nil
	}
	defer func() { install.SkopeoInspectFn = install.DefaultSkopeoInspect }()

	result := install.CheckImage("ghcr.io/tuna-os/yellowfin:gnome-hwe")
	if !result.NeedsPull {
		t.Error("NeedsPull should be true when remote digest differs from local")
	}
}

func TestCheckImage_NeedsPullOnNetworkError(t *testing.T) {
	install.SkopeoInspectFn = func(args ...string) ([]byte, error) {
		return nil, fmt.Errorf("network error")
	}
	defer func() { install.SkopeoInspectFn = install.DefaultSkopeoInspect }()

	result := install.CheckImage("ghcr.io/tuna-os/yellowfin:gnome-hwe")
	if !result.NeedsPull {
		t.Error("NeedsPull should be true on network error (safe fallback)")
	}
}
```

Also add `"fmt"` to imports in bootc_test.go.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd fisherman/fisherman && go test ./internal/install/... -run TestCheckImage -v
```

Expected: compilation error (SkopeoInspectFn, CheckImage not defined yet).

- [ ] **Step 3: Implement CheckImage in bootc.go**

Add to `fisherman/fisherman/internal/install/bootc.go`:

```go
// ImageCheck holds the result of a pre-flight image inspection.
type ImageCheck struct {
	NeedsPull  bool // true if the image is absent or stale in containers-storage
	LayerCount int  // number of layers in the remote image; 0 if unknown
}

// DefaultSkopeoInspect runs `skopeo inspect <args>` and returns stdout.
func DefaultSkopeoInspect(args ...string) ([]byte, error) {
	return exec.Command("skopeo", append([]string{"inspect"}, args...)...).Output()
}

// SkopeoInspectFn is the function used by CheckImage to call skopeo inspect.
// Replace in tests to avoid network calls.
var SkopeoInspectFn = DefaultSkopeoInspect

// CheckImage compares the remote and local (containers-storage) image digests
// to determine whether a pull is required. It also returns the remote layer count.
// On any error (network, auth, not cached), NeedsPull is true (safe fallback).
func CheckImage(image string) ImageCheck {
	type manifest struct {
		Digest string   `json:"Digest"`
		Layers []string `json:"Layers"`
	}

	// 1. Fetch remote normalized manifest (resolves fat/multi-arch manifests).
	remoteOut, err := SkopeoInspectFn("docker://" + image)
	if err != nil {
		return ImageCheck{NeedsPull: true}
	}
	var remote manifest
	if err := json.Unmarshal(remoteOut, &remote); err != nil {
		return ImageCheck{NeedsPull: true}
	}

	// 2. Fetch local digest from containers-storage.
	localOut, err := SkopeoInspectFn("containers-storage:" + image)
	if err != nil {
		// Image not present locally.
		return ImageCheck{NeedsPull: true, LayerCount: len(remote.Layers)}
	}
	var local manifest
	if err := json.Unmarshal(localOut, &local); err != nil {
		return ImageCheck{NeedsPull: true, LayerCount: len(remote.Layers)}
	}

	// 3. Compare digests.
	needsPull := remote.Digest == "" || remote.Digest != local.Digest
	return ImageCheck{NeedsPull: needsPull, LayerCount: len(remote.Layers)}
}
```

Also remove the old `getLayerCount` function entirely from bootc.go.

Make sure `"encoding/json"` is in the imports (it already is).

- [ ] **Step 4: Run tests**

```bash
cd fisherman/fisherman && go test ./internal/install/... -run TestCheckImage -v
```

Expected: all 4 `TestCheckImage_*` tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd fisherman/fisherman && go test ./... && go vet ./...
```

Expected: all tests PASS, no vet errors.

- [ ] **Step 6: Commit**

```bash
cd fisherman/fisherman
git add internal/install/bootc.go internal/install/bootc_test.go
git commit -m "feat: add CheckImage() with digest-based cache detection, replace getLayerCount"
```

---

## Task 4: Fix pullImage blob counting and skip pull when cached

**Files:**
- Modify: `fisherman/fisherman/internal/install/bootc.go`

Two changes: fix the blob counter (count start lines, not "done" lines), and skip the pull when `NeedsPull == false`. Layer count is now passed via `Options`.

- [ ] **Step 1: Add LayerCount and NeedsPull to Options**

In the `Options` struct in `bootc.go`, add two fields:

```go
type Options struct {
	SourceImgref     string
	TargetImgref     string
	SelinuxDisabled  bool
	UnifiedStorage   bool
	ComposeFsBackend bool
	Target           string
	// NeedsPull is the result of a pre-flight CheckImage call. When false,
	// the image pull is skipped (image already in containers-storage).
	NeedsPull bool
	// LayerCount is the number of image layers from CheckImage, used to
	// show "layer N/total" progress. 0 means unknown.
	LayerCount int
}
```

- [ ] **Step 2: Fix pullImage blob counting**

Replace the `pullImage` function. Key change: remove the `getLayerCount` call (now uses `layerCount` param) and count `"copying blob sha256:"` start lines instead of requiring `"done"` on the same line:

```go
// pullImage uses skopeo to download the container image into podman's storage.
func pullImage(image string, layerCount int) error {
	progress.Substep("Pulling container image")
	if layerCount > 0 {
		progress.Substep(fmt.Sprintf("Pulling image: %d layers to download", layerCount))
	}

	fmt.Fprintf(os.Stdout, "+ skopeo copy docker://%s containers-storage:%s\n", image, image)
	cmd := exec.Command("skopeo", "copy", "docker://"+image, "containers-storage:"+image)
	pr, pw := io.Pipe()
	cmd.Stdout = pw
	cmd.Stderr = pw

	if err := cmd.Start(); err != nil {
		pw.Close()
		return err
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		scanner := bufio.NewScanner(pr)
		scanner.Buffer(make([]byte, 0, 256*1024), 256*1024)
		layersDone := 0
		for scanner.Scan() {
			line := scanner.Text()
			fmt.Fprintln(os.Stdout, line)
			lower := strings.ToLower(line)

			// Count each blob start line — skopeo emits one per blob when piped
			// (no "done" suffix in non-TTY output).
			if strings.HasPrefix(lower, "copying blob sha256:") {
				layersDone++
				if layerCount > 0 {
					progress.Substep(fmt.Sprintf("Pulling image: layer %d/%d", layersDone, layerCount))
				} else {
					progress.Substep(fmt.Sprintf("Pulling image: layer %d", layersDone))
				}
			} else if strings.Contains(lower, "copying config") {
				progress.Substep("Pulling image: copying config")
			} else if strings.Contains(lower, "writing manifest") {
				progress.Substep("Pulling image: writing manifest")
			}
		}
	}()

	err := cmd.Wait()
	pw.Close()
	<-done

	if err != nil {
		return fmt.Errorf("skopeo copy %s: %w", image, err)
	}
	progress.Substep("Image pulled successfully")
	return nil
}
```

- [ ] **Step 3: Update bootcViaContainer to skip pull when cached**

In `bootcViaContainer`, replace the `pullImage` call block:

```go
func bootcViaContainer(opts Options) error {
	targetImgref := opts.TargetImgref
	if targetImgref == "" {
		targetImgref = opts.SourceImgref
	}

	if opts.NeedsPull {
		if err := pullImage(opts.SourceImgref, opts.LayerCount); err != nil {
			return fmt.Errorf("pulling image: %w", err)
		}
	} else {
		progress.Substep("Image already up to date, skipping pull")
	}

	bootcArgs := BuildBootcArgs(opts, targetImgref, "/target")
	// ... rest of function unchanged ...
```

- [ ] **Step 4: Verify build and tests**

```bash
cd fisherman/fisherman && go build ./... && go vet ./... && go test ./...
```

Expected: all pass. The existing `TestBuildBootcArgs_*` tests don't touch pullImage so they still pass.

- [ ] **Step 5: Commit**

```bash
cd fisherman/fisherman
git add internal/install/bootc.go
git commit -m "feat: fix skopeo blob counting, skip pull when image is current"
```

---

## Task 5: Add "layers needed" classifyLine pattern

**Files:**
- Modify: `fisherman/fisherman/internal/install/bootc.go`
- Modify: `fisherman/fisherman/internal/install/bootc_test.go`

The bootc output line `"layers already present: 0; layers needed: 64 (3.7 GB)"` currently has no substep. Add it.

- [ ] **Step 1: Write the failing test**

Add to `bootc_test.go`:

```go
func TestClassifyLine_LayersNeeded(t *testing.T) {
	line := "layers already present: 0; layers needed: 64 (3.7\u00a0GB)"
	got := install.ClassifyLine(line)
	if got != "Deploying: 64 (3.7\u00a0GB)" {
		t.Errorf("ClassifyLine(%q) = %q, want %q", line, got, "Deploying: 64 (3.7\u00a0GB)")
	}
}

func TestClassifyLine_LayersNeeded_AlreadyPresent(t *testing.T) {
	// When all layers are already present, it still should surface the info.
	line := "layers already present: 64; layers needed: 0"
	got := install.ClassifyLine(line)
	if got != "Deploying: 0" {
		t.Errorf("ClassifyLine(%q) = %q, want %q", line, got, "Deploying: 0")
	}
}
```

Note: `classifyLine` is currently unexported. Rename it to `ClassifyLine` (exported) in bootc.go so tests in the `install_test` package can access it. Update the one internal caller (`runWithSubsteps`) accordingly.

- [ ] **Step 2: Run to confirm failure**

```bash
cd fisherman/fisherman && go test ./internal/install/... -run TestClassifyLine -v
```

Expected: compilation error (ClassifyLine not exported yet).

- [ ] **Step 3: Export classifyLine → ClassifyLine and add the pattern**

In `bootc.go`, rename `classifyLine` to `ClassifyLine` and add the new case to the switch:

```go
// ClassifyLine maps a raw bootc/ostree/podman output line to a human-readable
// substep description, or "" if the line is not interesting.
func ClassifyLine(line string) string {
	lower := strings.ToLower(line)
	switch {
	case strings.Contains(lower, "installing image:"):
		return "Pulling container image"
	case strings.Contains(lower, "layers") && strings.Contains(lower, "needed"):
		// e.g. "layers already present: 0; layers needed: 64 (3.7 GB)"
		if i := strings.Index(lower, "layers needed:"); i >= 0 {
			rest := strings.TrimSpace(line[i+len("layers needed:"):])
			return "Deploying: " + rest
		}
		return "Downloading image layers"
	case strings.Contains(lower, "initializing ostree"):
		return "Initializing ostree layout"
	case strings.Contains(lower, "deploying container image"):
		return "Deploying OS (this may take a while)"
	case strings.Contains(lower, "bootloader:"):
		return "Detected bootloader"
	case strings.Contains(lower, "installing bootloader"):
		return "Installing bootloader"
	case strings.Contains(lower, "efibootmgr"):
		return "Configuring EFI boot entry"
	case strings.Contains(lower, "installed:") && strings.Contains(lower, "grub"):
		return "Configuring GRUB"
	case strings.Contains(lower, "installation complete"):
		return "bootc installation complete"
	case strings.Contains(lower, "selinux"):
		return "Configuring SELinux"
	case strings.Contains(lower, "generating initramfs") || strings.Contains(lower, "dracut"):
		return "Generating initramfs"
	}
	return ""
}
```

Update the internal caller in `runWithSubsteps`:
```go
if sub := ClassifyLine(line); sub != "" && sub != lastSubstep {
```

Note: the old `"layers" && "needed"` case that returned `"Downloading image layers"` is now superseded by the new more specific case above it. Keep the old fallback case removed — the new pattern handles both variants.

- [ ] **Step 4: Run tests**

```bash
cd fisherman/fisherman && go test ./internal/install/... -run TestClassifyLine -v
```

Expected: both `TestClassifyLine_LayersNeeded` tests PASS.

- [ ] **Step 5: Run full suite**

```bash
cd fisherman/fisherman && go test ./... && go vet ./...
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd fisherman/fisherman
git add internal/install/bootc.go internal/install/bootc_test.go
git commit -m "feat: export ClassifyLine, add 'layers needed' deploy substep"
```

---

## Task 6: Wire weight profiles in main.go

**Files:**
- Modify: `fisherman/fisherman/cmd/fisherman/main.go`

Replace the `(0, 0)` placeholder weight args with real values from empirically-tuned profiles. Call `CheckImage` before step 1 and use the result to pick the right profile and configure `Options`.

- [ ] **Step 1: Add buildProfile() and call CheckImage before step 1**

Add this function and the pre-flight check to `main.go`. Insert `buildProfile` before `main()`:

```go
type stepProfile struct {
	cumulativePct int
	weightPct     int
}

// buildProfile returns per-step weight profiles based on timing data from a
// yellowfin gnome-hwe loop-device install (264s uncached, ~111s cached).
// Weights sum to 100. cumulativePct is the bar position at step start.
func buildProfile(needsPull, hasLUKS, hasTPM2enrolment bool) []stepProfile {
	osWeight := 87
	flatpakWeight := 11
	if !needsPull {
		osWeight = 68
		flatpakWeight = 29
	}
	if hasLUKS {
		osWeight--
	}
	if hasTPM2enrolment {
		osWeight--
	}

	// Build weights in step order.
	weights := []int{0, 1} // partition, format EFI
	if hasLUKS {
		weights = append(weights, 1) // LUKS setup
	}
	weights = append(weights, 0, 0)    // format root, mount
	weights = append(weights, osWeight) // install OS
	if hasTPM2enrolment {
		weights = append(weights, 1) // TPM2 enrolment
	}
	weights = append(weights, flatpakWeight, 0) // flatpaks, configure
	// finalize gets whatever is left to sum to 100
	sum := 0
	for _, w := range weights {
		sum += w
	}
	weights = append(weights, 100-sum) // finalize

	profile := make([]stepProfile, len(weights))
	cumulative := 0
	for i, w := range weights {
		profile[i] = stepProfile{cumulative, w}
		cumulative += w
	}
	return profile
}
```

- [ ] **Step 2: Add pre-flight check and profile selection to main()**

At the top of `main()`, after `r.Validate()` and the `hasEncryption`/`hasTPM2` declarations, add:

```go
// ── Pre-flight: check image cache ──────────────────────────────────────────
// Only relevant in container mode (r.Image != ""). In live-ISO mode the
// image is already running so we treat it as cached.
var imageCheck install.ImageCheck
if r.Image != "" {
	progress.Info("Checking image cache...")
	imageCheck = install.CheckImage(r.Image)
	if imageCheck.NeedsPull {
		progress.Info(fmt.Sprintf("Image pull required (%d layers)", imageCheck.LayerCount))
	} else {
		progress.Info("Image already up to date in local cache")
	}
}

hasTPM2enrolment := r.Encryption.Type == "tpm2-luks-passphrase"
profile := buildProfile(imageCheck.NeedsPull, hasEncryption, hasTPM2enrolment)
pi := 0 // profile index, incremented at each progress.Step call
```

Note: `hasTPM2` is already declared in the original code. Rename it or reuse it — the original `hasTPM2` variable already covers this case. Use the existing variable name to avoid collision.

Replace this block (which already exists):
```go
hasTPM2 := r.Encryption.Type == "tpm2-luks" || r.Encryption.Type == "tpm2-luks-passphrase"
```
With:
```go
hasTPM2 := r.Encryption.Type == "tpm2-luks" || r.Encryption.Type == "tpm2-luks-passphrase"
hasTPM2enrolment := r.Encryption.Type == "tpm2-luks-passphrase"
```

And the `BootcInstall` call gains two new option fields:
```go
if err := install.BootcInstall(install.Options{
	SourceImgref:     r.Image,
	TargetImgref:     targetImgref,
	SelinuxDisabled:  r.SelinuxDisabled,
	UnifiedStorage:   r.UnifiedStorage,
	ComposeFsBackend: r.ComposeFsBackend,
	Target:           targetMount,
	NeedsPull:        imageCheck.NeedsPull,
	LayerCount:       imageCheck.LayerCount,
}); err != nil {
```

- [ ] **Step 3: Replace all progress.Step() (0, 0) calls with profile values**

Replace every `progress.Step(step, totalSteps, "...", 0, 0)` call to use `profile[pi]` and increment `pi` after each:

```go
// ── Step 1: Partition disk ────────────────────────────────────────────────────
progress.Step(step, totalSteps, "Partitioning disk", profile[pi].cumulativePct, profile[pi].weightPct)
pi++
step++
```

Do this for every step in the same pattern. For conditional steps (LUKS, TPM2), `pi` increments only when that step fires (which is exactly when `buildProfile` included it):

```go
// ── Step 3: Disk encryption (optional) ───────────────────────────────────────
if hasEncryption {
    progress.Step(step, totalSteps, "Setting up disk encryption", profile[pi].cumulativePct, profile[pi].weightPct)
    pi++
    step++
    // ... LUKS logic ...
}
```

```go
if r.Encryption.Type == "tpm2-luks-passphrase" {
    progress.Step(step, totalSteps, "Enrolling TPM2 auto-unlock", profile[pi].cumulativePct, profile[pi].weightPct)
    pi++
    step++
    // ... TPM2 logic ...
}
```

- [ ] **Step 4: Build and vet**

```bash
cd fisherman/fisherman && go build ./... && go vet ./...
```

Expected: no errors.

- [ ] **Step 5: Quick smoke test — check JSON output format**

```bash
cd fisherman/fisherman
go build -o /tmp/fisherman ./cmd/fisherman/
echo '{"disk":"/dev/null","filesystem":"xfs","encryption":{"type":"none"},"hostname":"test","flatpaks":[]}' > /tmp/test-recipe.json
# This will fail at partition (no real disk) but we just want to see the first JSON event:
sudo /tmp/fisherman /tmp/test-recipe.json 2>/dev/null | head -1 | python3 -c "import sys,json; e=json.load(sys.stdin); print(e.get('weight_pct'), e.get('cumulative_pct'))"
```

Expected output (with a real image in cache it would be 0 0, without it would be 0 0 for partition either way):
```
0 0
```

The key is that `weight_pct` and `cumulative_pct` are present in the output.

- [ ] **Step 6: Commit**

```bash
cd fisherman/fisherman
git add cmd/fisherman/main.go
git commit -m "feat: wire weight profiles and CheckImage pre-flight into main install loop"
```

---

## Task 7: Update Python GUI progress bar

**Files:**
- Modify: `tuna_installer/views/progress.py`

One logical change: use `cumulative_pct` from the step event for bar position instead of `step/total_steps`.

- [ ] **Step 1: Update the step handler in __on_vte_contents_changed**

In `tuna_installer/views/progress.py`, find the `event_type == "step"` branch (around line 327). Replace the fraction calculation:

```python
# Before:
fraction = step / max(total, 1)

# After:
cumulative_pct = event.get("cumulative_pct", 0)
self.__current_weight_pct = event.get("weight_pct", 0)
fraction = cumulative_pct / 100.0
```

Also add `self.__current_weight_pct = 0` to `__init__` alongside the other `self.__current_*` initialisations (around line 113):

```python
self.__current_weight_pct = 0
```

- [ ] **Step 2: Verify the file looks right**

```bash
python3 -c "import ast; ast.parse(open('tuna_installer/views/progress.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add tuna_installer/views/progress.py
git commit -m "feat: use cumulative_pct for proportional progress bar in GUI"
```

---

## Task 8: Final integration — push fisherman and update submodule pointer

**Files:**
- `fisherman/fisherman/` (submodule)
- `fisherman/` (parent repo submodule pointer)

Per the CLAUDE.md workflow: fisherman changes must be committed in the submodule and pushed, then the parent repo's submodule pointer updated.

- [ ] **Step 1: Push fisherman submodule**

```bash
cd fisherman/fisherman
git log --oneline -6   # confirm all 6 commits are present
git push
```

Expected: pushes to `tuna-os/fisherman` remote.

- [ ] **Step 2: Update submodule pointer in parent repo**

```bash
cd /var/home/james/dev/tuna-installer
git add fisherman
git commit -m "chore: update fisherman submodule (proportional progress tracking)"
git push
```

- [ ] **Step 3: Verify CI**

Check that the GitHub Actions Go test suite passes:
```bash
gh run list --repo tuna-os/fisherman --limit 3
```

Wait for the run triggered by the push to complete with status `completed` / `success`.

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| Pre-flight CheckImage (digest compare + layer count) | Task 3 |
| Weighted step events (weight_pct, cumulative_pct) | Task 2 |
| Two weight profiles (cached/uncached) | Task 6 |
| Optional LUKS/TPM2 step weights | Task 6 `buildProfile` |
| Step counter fix (totalSteps 9→8, missing step++) | Task 1 |
| Skopeo blob counting fix (start lines, not "done") | Task 4 |
| getLayerCount replacement | Task 3 |
| pullImage receives LayerCount via Options | Task 4 |
| Skip pull when NeedsPull==false | Task 4 |
| classifyLine "layers needed" pattern | Task 5 |
| Python GUI cumulative_pct bar | Task 7 |
| Live-ISO mode treated as cached (NeedsPull=false) | Task 6 (imageCheck zero value → NeedsPull=false) |

**Type consistency:**
- `ImageCheck.NeedsPull` / `ImageCheck.LayerCount` — used consistently in Tasks 3, 4, 6
- `Options.NeedsPull` / `Options.LayerCount` — added in Task 4, consumed in `bootcViaContainer`, set in Task 6
- `stepProfile.cumulativePct` / `stepProfile.weightPct` — defined and used in Task 6
- `SkopeoInspectFn` / `DefaultSkopeoInspect` — exported in Task 3, used in tests
- `ClassifyLine` (exported, was `classifyLine`) — exported in Task 5, caller updated

**Placeholder scan:** No TBDs, TODOs, or vague steps found. All code blocks are complete.
