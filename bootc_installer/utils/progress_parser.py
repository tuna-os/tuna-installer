"""progress_parser.py — Pure fisherman progress-event parser (no GTK).

Provides apply_progress_event() and _new_progress_state() for use by
VanillaProgress and for unit tests.
"""

import json
import re

# Matches "Pulling image: layer 23/71" substep messages from fisherman.
_RE_LAYER_PROGRESS = re.compile(r"Pulling image: layer (\d+)/(\d+)")


def new_progress_state() -> dict:
    """Return a fresh progress state dict (no GTK types)."""
    return {
        "pulse_active": True,
        "current_step": 0,
        "current_total": 0,
        "current_step_name": "",
        "current_weight_pct": 0,
        "current_cumulative_pct": 0,
        "seen_substeps": set(),
        "boot_id": "",
    }


def apply_progress_event(line: str, state: dict) -> dict | None:
    """Parse one fisherman log line and return a UI-update dict, or None.

    Pure function — no GTK, no I/O.  The returned dict has:
      "fraction"  — float 0-1 for progressbar.set_fraction()
      "label"     — str for progressbar_text.set_label() (None = no change)
      "pulse"     — bool; True means switch bar to pulse mode
      "complete"  — bool; True means install finished
    ``state`` is mutated in-place to track multi-line context.
    Returns None for non-JSON lines or events that require no UI change.
    """
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    event_type = event.get("type", "")

    if event_type == "step":
        step = event.get("step", 0)
        total = event.get("total_steps", 1)
        name = event.get("step_name", "Installing")
        if step <= state["current_step"] and state["current_step"] > 0:
            return None
        cumulative_pct = event.get("cumulative_pct", 0)
        state["current_weight_pct"] = event.get("weight_pct", 0)
        state["current_cumulative_pct"] = cumulative_pct
        state["current_step"] = step
        state["current_total"] = total
        state["current_step_name"] = name
        state["seen_substeps"].clear()
        state["pulse_active"] = False
        return {
            "fraction": cumulative_pct / 100.0,
            "label": "Step %d/%d: %s" % (step, total, name),
            "pulse": False,
            "complete": False,
        }

    if event_type == "substep":
        msg = event.get("message", "")
        if not msg:
            return None
        fraction = None
        m = _RE_LAYER_PROGRESS.match(msg)
        if m and state["current_weight_pct"] > 0:
            done = int(m.group(1))
            total_layers = int(m.group(2))
            sub_frac = done / total_layers
            fraction = min(
                (state["current_cumulative_pct"] + sub_frac * state["current_weight_pct"]) / 100.0,
                1.0,
            )
        if msg in state["seen_substeps"]:
            # Still update fraction even for duplicate substep messages.
            if fraction is not None:
                return {"fraction": fraction, "label": None, "pulse": False, "complete": False}
            return None
        state["seen_substeps"].add(msg)
        label = None
        if state["current_step"]:
            label = "Step %d/%d: %s — %s" % (
                state["current_step"],
                state["current_total"],
                state["current_step_name"],
                msg,
            )
        return {"fraction": fraction, "label": label, "pulse": False, "complete": False}

    if event_type == "complete":
        state["pulse_active"] = False
        state["boot_id"] = event.get("boot_id", "")
        return {"fraction": 1.0, "label": "Installation complete!", "pulse": False, "complete": True}

    return None
