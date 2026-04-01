"""Unit tests for the pure fisherman progress-event parser.

apply_progress_event() and new_progress_state() have no GTK dependency,
so these tests run without a display server.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tuna_installer.utils.progress_parser import apply_progress_event, new_progress_state


def _step(step=1, total=8, name="Partitioning disk", cumulative_pct=0, weight_pct=1):
    return json.dumps({
        "type": "step", "step": step, "total_steps": total,
        "step_name": name, "cumulative_pct": cumulative_pct, "weight_pct": weight_pct,
    })


def _substep(msg):
    return json.dumps({"type": "substep", "message": msg})


def _complete(boot_id=""):
    return json.dumps({"type": "complete", "message": "Installation complete!", "boot_id": boot_id})


# ── Non-JSON lines ─────────────────────────────────────────────────────────────

class TestNonJson:
    def test_empty_line(self):
        assert apply_progress_event("", new_progress_state()) is None

    def test_plain_text(self):
        assert apply_progress_event("Copying blob sha256:abc", new_progress_state()) is None

    def test_invalid_json(self):
        assert apply_progress_event("{bad json}", new_progress_state()) is None


# ── Step events ────────────────────────────────────────────────────────────────

class TestStepEvent:
    def test_step_stops_pulse(self):
        state = new_progress_state()
        update = apply_progress_event(_step(), state)
        assert update is not None
        assert update["pulse"] is False
        assert state["pulse_active"] is False

    def test_step_sets_fraction(self):
        state = new_progress_state()
        update = apply_progress_event(_step(cumulative_pct=10), state)
        assert update["fraction"] == pytest.approx(0.10)

    def test_step_sets_label(self):
        state = new_progress_state()
        update = apply_progress_event(_step(step=3, total=8, name="Mounting filesystem"), state)
        assert "Step 3/8" in update["label"]
        assert "Mounting filesystem" in update["label"]

    def test_step_advances_state(self):
        state = new_progress_state()
        apply_progress_event(_step(step=1), state)
        assert state["current_step"] == 1

    def test_duplicate_step_ignored(self):
        state = new_progress_state()
        apply_progress_event(_step(step=2), state)
        update = apply_progress_event(_step(step=2), state)
        assert update is None

    def test_backward_step_ignored(self):
        state = new_progress_state()
        apply_progress_event(_step(step=5), state)
        update = apply_progress_event(_step(step=3), state)
        assert update is None

    def test_step_clears_seen_substeps(self):
        state = new_progress_state()
        apply_progress_event(_step(step=1), state)
        apply_progress_event(_substep("Some substep"), state)
        assert "Some substep" in state["seen_substeps"]
        apply_progress_event(_step(step=2), state)
        assert len(state["seen_substeps"]) == 0


# ── Substep events ─────────────────────────────────────────────────────────────

class TestSubstepEvent:
    def test_substep_sets_label(self):
        state = new_progress_state()
        apply_progress_event(_step(step=5, name="Installing OS", cumulative_pct=1, weight_pct=87), state)
        update = apply_progress_event(_substep("Pulling container image"), state)
        assert update is not None
        assert "Pulling container image" in update["label"]

    def test_duplicate_substep_no_label(self):
        state = new_progress_state()
        apply_progress_event(_step(step=1), state)
        apply_progress_event(_substep("Some msg"), state)
        update = apply_progress_event(_substep("Some msg"), state)
        # Duplicate: no label update (None)
        assert update is None or update.get("label") is None

    def test_layer_progress_fraction(self):
        state = new_progress_state()
        # Step 5: cumulative=1%, weight=87%
        apply_progress_event(_step(step=5, cumulative_pct=1, weight_pct=87), state)
        update = apply_progress_event(_substep("Pulling image: layer 32/64"), state)
        assert update is not None
        assert update["fraction"] is not None
        # 1% + (32/64)*87% = 1% + 43.5% = 44.5%
        assert update["fraction"] == pytest.approx(0.445, abs=0.01)

    def test_layer_progress_clamped_to_1(self):
        state = new_progress_state()
        apply_progress_event(_step(step=5, cumulative_pct=50, weight_pct=87), state)
        update = apply_progress_event(_substep("Pulling image: layer 64/64"), state)
        assert update["fraction"] <= 1.0

    def test_substep_no_fraction_without_layer_match(self):
        state = new_progress_state()
        apply_progress_event(_step(step=1, weight_pct=5), state)
        update = apply_progress_event(_substep("Pulling container image"), state)
        assert update is not None
        assert update["fraction"] is None

    def test_substep_before_any_step_no_label(self):
        state = new_progress_state()
        update = apply_progress_event(_substep("Early message"), state)
        # current_step is 0, so no label
        assert update is None or update.get("label") is None


# ── Complete event ─────────────────────────────────────────────────────────────

class TestCompleteEvent:
    def test_complete_sets_fraction_1(self):
        state = new_progress_state()
        update = apply_progress_event(_complete(), state)
        assert update["fraction"] == 1.0

    def test_complete_sets_label(self):
        state = new_progress_state()
        update = apply_progress_event(_complete(), state)
        assert "complete" in update["label"].lower() or "Installation" in update["label"]

    def test_complete_flag(self):
        state = new_progress_state()
        update = apply_progress_event(_complete(), state)
        assert update["complete"] is True

    def test_complete_stores_boot_id(self):
        state = new_progress_state()
        apply_progress_event(_complete(boot_id="0007"), state)
        assert state["boot_id"] == "0007"


# ── Info events (no UI update) ─────────────────────────────────────────────────

class TestInfoEvent:
    def test_info_returns_none(self):
        line = json.dumps({"type": "info", "message": "Image pull required"})
        assert apply_progress_event(line, new_progress_state()) is None


# ── Full sequence ──────────────────────────────────────────────────────────────

class TestFullSequence:
    def test_real_log_sequence(self):
        """Replay a realistic fisherman log and check final state."""
        log_lines = [
            json.dumps({"type": "info", "message": "Image pull required (64 layers)"}),
            _step(step=1, total=8, name="Partitioning disk",     cumulative_pct=0,  weight_pct=1),
            _step(step=2, total=8, name="Formatting EFI",        cumulative_pct=1,  weight_pct=1),
            _step(step=3, total=8, name="Formatting root",       cumulative_pct=2,  weight_pct=0),
            _step(step=4, total=8, name="Mounting filesystem",   cumulative_pct=2,  weight_pct=0),
            _step(step=5, total=8, name="Installing OS",         cumulative_pct=2,  weight_pct=87),
            _substep("Pulling container image"),
            _substep("Pulling image: 64 layers to download"),
            _substep("Pulling image: layer 1/64"),
            _substep("Pulling image: layer 32/64"),
            _substep("Pulling image: layer 64/64"),
            _substep("Image pulled successfully"),
            _step(step=6, total=8, name="Writing hostname",      cumulative_pct=89, weight_pct=1),
            _step(step=7, total=8, name="Copying Flatpaks",      cumulative_pct=90, weight_pct=5),
            _step(step=8, total=8, name="Finalizing",            cumulative_pct=95, weight_pct=5),
            _complete(boot_id="0003"),
        ]
        state = new_progress_state()
        updates = [apply_progress_event(l, state) for l in log_lines]
        non_none = [u for u in updates if u is not None]

        # Must reach completion
        assert non_none[-1]["complete"] is True
        assert state["boot_id"] == "0003"
        # Final step should be 8
        assert state["current_step"] == 8
        # Bar at 100% at end
        assert non_none[-1]["fraction"] == 1.0
