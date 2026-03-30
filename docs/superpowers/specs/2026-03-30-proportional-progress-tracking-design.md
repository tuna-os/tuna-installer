# Proportional Progress Tracking Design

**Date:** 2026-03-30
**Scope:** fisherman (Go) + tuna-installer Python GUI
**Empirical basis:** Loop-device install of `ghcr.io/tuna-os/yellowfin:gnome-hwe` (264.7s total)

## Background

The install has 8 steps of wildly unequal duration. The current equal-weight `step/total_steps` progress bar is misleading: step 5 ("Installing OS") takes 87% of total time but only occupies 1/8 of the bar. This design makes the bar proportional to actual wall-clock time and adds granular sub-step tracking within the longest steps.

### Empirical timing (uncached image)

| Step | Duration | % of total |
|------|----------|------------|
| 1–4 (partition, format, mount) | ~0.6s | 0.2% |
| 5 Installing OS — skopeo pull | ~152s | 57% |
| 5 Installing OS — bootc deploy | ~77s | 29% |
| 6 Copying Flatpaks | ~33s | 12% |
| 7–8 (configure, finalize) | ~2s | 0.8% |

### Root causes of current tracking gaps

1. **Skopeo blob counter never fires**: the counter requires `"done"` on the same line as `"Copying blob"`, but skopeo emits start-only lines (`Copying blob sha256:...`) when writing to a pipe. 152 seconds of silence.
2. **`getLayerCount` returns 0 for multi-arch images**: `skopeo inspect --raw` returns a manifest list (with `manifests[]`), not an image manifest (with `layers[]`). So total-layer count is always unknown for fat-manifest images like yellowfin.
3. **No distinction between cached and uncached paths**: a locally-cached image takes ~111s total vs ~265s uncached. Equal-weight steps are wrong in both cases, but wrong in different ways.
4. **Step counter bug**: `step++` is missing after "Configuring installed system", so both that step and "Finalizing installation" emit `step: 7`. Also `totalSteps` is hardcoded to `9` but the base step count is `8`.

---

## Design

### 1. Pre-flight image check (`install.CheckImage`)

A new exported function in `internal/install/bootc.go` runs before step 1, **only when `r.Image != ""`** (container mode). In live-ISO mode (`r.Image == ""`), `bootcDirect` is used and the image is already running — no pull check needed. In that case, treat it as cached with `NeedsPull = false, LayerCount = 0` and use the cached weight profile.

```go
type ImageCheck struct {
    NeedsPull  bool
    LayerCount int // 0 if unknown
}

func CheckImage(image string) ImageCheck
```

**Implementation:**

1. Call `skopeo inspect docker://<image>` (without `--raw`) to get the remote normalized manifest. This auto-resolves fat manifests to the current platform. Parse `Digest` and `len(Layers)`.
2. Call `skopeo inspect containers-storage:<image>` to get the local digest. If the command fails (image absent), `NeedsPull = true`.
3. If local digest == remote digest → `NeedsPull = false` (up to date). Otherwise `NeedsPull = true`.
4. Return `LayerCount` from the remote inspect regardless of cache status (used for pull progress labelling).

This replaces `getLayerCount` entirely. The network call is the same cost as before (one `skopeo inspect`), but now it does double duty: freshness check + layer count in one shot.

If `skopeo inspect docker://` fails (network error, auth failure), `CheckImage` returns `NeedsPull = true, LayerCount = 0` — a safe fallback that triggers a pull attempt.

### 2. Weighted step events (progress event schema)

Two fields are added to every `step` event:

| Field | Type | Meaning |
|-------|------|---------|
| `weight_pct` | int | Estimated % of total install time this step occupies |
| `cumulative_pct` | int | Bar position (0–100) at the START of this step |

Example:
```json
{
  "type": "step", "step": 5, "total_steps": 8,
  "step_name": "Installing OS",
  "weight_pct": 87, "cumulative_pct": 1,
  "elapsed_ms": 593, "timestamp": "..."
}
```

`progress.Step()` signature change in `internal/progress/progress.go`:
```go
func Step(step, total int, name string, cumulativePct, weightPct int)
```

### 3. Weight profiles (`cmd/fisherman/main.go`)

Two profiles are chosen based on `CheckImage.NeedsPull`:

#### Base steps (no encryption)

| # | Step name | Cached % | Uncached % |
|---|-----------|----------|------------|
| 1 | Partitioning disk | 0 | 0 |
| 2 | Formatting EFI partition | 1 | 1 |
| 3 | Formatting root filesystem | 0 | 0 |
| 4 | Mounting filesystem | 0 | 0 |
| 5 | Installing OS | 68 | 87 |
| 6 | Copying system Flatpaks | 29 | 11 |
| 7 | Configuring installed system | 0 | 0 |
| 8 | Finalizing installation | 2 | 1 |

`cumulative_pct` for each step is the running sum of all prior `weight_pct` values.

#### Optional steps (encryption/TPM2)

When LUKS is present, a "Setting up disk encryption" step (~3s) is inserted at position 3 with `weight_pct: 1`, taking 1 point from the OS install step. When TPM2 enrolment is present, an "Enrolling TPM2 auto-unlock" step (~5s) is inserted after OS install with `weight_pct: 1`, again taking 1 from OS install. These are rough estimates; the profiles can be tuned empirically over time.

### 4. Step counter fix (`cmd/fisherman/main.go`)

Two changes:
- `totalSteps := 9` → `totalSteps := 8` (correct base count)
- Add `step++` after `progress.Step(step, totalSteps, "Configuring installed system", ...)`

### 5. Skopeo blob counting fix (`internal/install/bootc.go`)

In `pullImage`, change the scanner to count each `"Copying blob sha256:"` line (one per blob, fires when the blob starts). Remove the `"done"/"skipped"/"already exists"` filter that was preventing any events from firing.

```go
if strings.HasPrefix(lower, "copying blob sha256:") {
    layersDone++
    if totalLayers > 0 {
        progress.Substep(fmt.Sprintf("Pulling image: layer %d/%d", layersDone, totalLayers))
    } else {
        progress.Substep(fmt.Sprintf("Pulling image: layer %d", layersDone))
    }
}
```

`getLayerCount` is removed. `pullImage` gains a `layerCount int` parameter, populated from `CheckImage.LayerCount` by the caller (`bootcViaContainer`). This makes the data flow explicit: `main.go` calls `CheckImage`, passes the result to `BootcInstall` via a new field on `Options`, and `bootcViaContainer` forwards `LayerCount` to `pullImage`.

When `CheckImage.NeedsPull == false`, `pullImage` is skipped entirely. `bootcViaContainer` proceeds directly to `podman run` (which uses the already-cached image).

### 6. bootc deploy substep (`internal/install/bootc.go`)

Add a pattern in `classifyLine` for the bootc line `"layers already present: N; layers needed: M (X GB)"`:

```go
case strings.Contains(lower, "layers needed:"):
    // e.g. "layers already present: 0; layers needed: 64 (3.7 GB)"
    // Extract and emit: "Deploying: 64 layers (3.7 GB)"
    if i := strings.Index(lower, "layers needed:"); i >= 0 {
        rest := strings.TrimSpace(line[i+len("layers needed:"):])
        return "Deploying: " + rest
    }
```

This gives users context for the 75-second ostree deploy window that currently shows no progress.

### 7. Python GUI (`tuna_installer/views/progress.py`)

One change in `__on_vte_contents_changed` under the `"step"` branch:

```python
# Before:
fraction = step / max(total, 1)

# After:
cumulative_pct = event.get("cumulative_pct", 0)
fraction = cumulative_pct / 100.0
```

The `weight_pct` field is stored on `self` for potential future use (smooth interpolation within a step), but is not used for bar positioning in this iteration — substeps affect only the text label, not the bar position.

---

## Files changed

| File | Change |
|------|--------|
| `fisherman/fisherman/internal/progress/progress.go` | Add `weight_pct`, `cumulative_pct` to `stepEvent`; update `Step()` signature |
| `fisherman/fisherman/internal/install/bootc.go` | Add `CheckImage()`; replace `getLayerCount()`; fix blob counting; add `classifyLine` pattern; skip pull when cached |
| `fisherman/fisherman/cmd/fisherman/main.go` | Call `CheckImage` pre-flight; define weight profiles; pass weights to `progress.Step()`; fix `totalSteps` and missing `step++` |
| `tuna_installer/views/progress.py` | Use `cumulative_pct / 100` for bar fraction |

## Out of scope

- Smooth within-step bar interpolation (bar stays at `cumulative_pct` during a step, jumps to next step boundary when it completes)
- Tuning weight profiles for LUKS/TPM2/btrfs variants (use rough estimates for now)
- Fixing the "no space left on device" flatpak copy failure (separate issue from disk sizing)
