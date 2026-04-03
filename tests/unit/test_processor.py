"""Unit tests for utils/processor.py — pure Python, no GTK required."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer.utils.processor import Processor

# A minimal system recipe (the tuna recipe.json, NOT the fisherman recipe).
_SYS_RECIPE = {}


def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Auto-disk helpers ──────────────────────────────────────────────────────────

def _auto_finals(disk="/dev/vda", fs="xfs", image="ghcr.io/tuna-os/yellowfin:gnome",
                 hostname="testhost", encryption=None, user=None, flatpaks=None,
                 composefs=False, image_type="bootc"):
    d = {
        "disk": {"auto": {"disk": disk, "pretty_size": "100 GB", "size": 100_000_000_000}},
        "selected_image": image,
        "hostname": hostname,
        "flatpaks": flatpaks or [],
        "composefs_backend": composefs,
        "image_type": image_type,
    }
    if encryption:
        d["encryption"] = encryption
    else:
        d["encryption"] = {"use_encryption": False}
    if user:
        d["user"] = user
    return [d]


# ── Auto-disk tests ────────────────────────────────────────────────────────────

class TestAutoDisk:
    def test_basic_xfs(self, tmp_path):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/vda"
        assert r["filesystem"] == "xfs"
        assert "customMounts" not in r or r.get("customMounts") == []

    def test_selects_disk(self, tmp_path):
        path = Processor.gen_install_recipe("log", _auto_finals(disk="/dev/nvme0n1"), _SYS_RECIPE)
        r = _load(path)
        assert r["disk"] == "/dev/nvme0n1"

    def test_image_propagated(self):
        img = "ghcr.io/ublue-os/bluefin:stable"
        path = Processor.gen_install_recipe("log", _auto_finals(image=img), _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == img

    def test_hostname_propagated(self):
        path = Processor.gen_install_recipe("log", _auto_finals(hostname="mybox"), _SYS_RECIPE)
        r = _load(path)
        assert r["hostname"] == "mybox"

    def test_flatpaks_propagated(self):
        flatpaks = ["org.mozilla.firefox", "org.gnome.Fractal"]
        path = Processor.gen_install_recipe("log", _auto_finals(flatpaks=flatpaks), _SYS_RECIPE)
        r = _load(path)
        assert r["flatpaks"] == flatpaks

    def test_fallback_hostname_from_sys_recipe(self):
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "selected_image": "ghcr.io/x:y",
                   "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, {"hostname": "fallback-host"})
        r = _load(path)
        assert r["hostname"] == "fallback-host"

    def test_fallback_hostname_default(self):
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "selected_image": "ghcr.io/x:y",
                   "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["hostname"] == "tunaos"


# ── Encryption tests ───────────────────────────────────────────────────────────

class TestEncryption:
    def test_no_encryption(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(encryption={"use_encryption": False}), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "none"
        assert r["encryption"]["passphrase"] == ""

    def test_luks_passphrase(self):
        enc = {"use_encryption": True, "type": "luks-passphrase", "encryption_key": "s3cr3t"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "luks-passphrase"
        assert r["encryption"]["passphrase"] == "s3cr3t"

    def test_tpm2_luks(self):
        enc = {"use_encryption": True, "type": "tpm2-luks"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks"

    def test_tpm2_luks_passphrase(self):
        enc = {"use_encryption": True, "type": "tpm2-luks-passphrase", "encryption_key": "pw"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks-passphrase"
        assert r["encryption"]["passphrase"] == "pw"

    def test_key_without_explicit_type_defaults_to_luks_passphrase(self):
        enc = {"use_encryption": True, "encryption_key": "mykey"}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "luks-passphrase"
        assert r["encryption"]["passphrase"] == "mykey"

    def test_no_key_and_no_type_defaults_to_tpm2(self):
        enc = {"use_encryption": True}
        path = Processor.gen_install_recipe("log", _auto_finals(encryption=enc), _SYS_RECIPE)
        r = _load(path)
        assert r["encryption"]["type"] == "tpm2-luks"


# ── Manual partitioning tests ──────────────────────────────────────────────────

class TestManualDisk:
    def _manual_finals(self, partitions: dict):
        return [{
            "disk": partitions,
            "selected_image": "ghcr.io/x:y",
            "hostname": "manualhost",
            "flatpaks": [],
            "encryption": {"use_encryption": False},
        }]

    def test_basic_manual_layout(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "ext4",  "mp": "/boot"},
            "/dev/sda3": {"fs": "xfs",   "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" in r
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert mounts["/"]["partition"] == "/dev/sda3"
        assert mounts["/"]["fstype"] == "xfs"
        assert mounts["/boot/efi"]["partition"] == "/dev/sda1"
        assert mounts["/boot/efi"]["fstype"] == "fat32"
        assert mounts["/boot"]["partition"] == "/dev/sda2"
        assert mounts["/boot"]["fstype"] == "ext4"

    def test_manual_does_not_set_disk_field(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",   "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        assert r.get("disk", "") == ""

    def test_unformatted_partition(self):
        partitions = {
            "/dev/sda1": {"fs": "unformatted", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",         "mp": "/"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert mounts["/boot/efi"]["fstype"] == "unformatted"

    def test_swap_partition_included(self):
        partitions = {
            "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
            "/dev/sda2": {"fs": "xfs",   "mp": "/"},
            "/dev/sda3": {"fs": "swap",  "mp": "swap"},
        }
        path = Processor.gen_install_recipe("log", self._manual_finals(partitions), _SYS_RECIPE)
        r = _load(path)
        mounts = {m["target"]: m for m in r["customMounts"]}
        assert "swap" in mounts
        assert mounts["swap"]["partition"] == "/dev/sda3"

    def test_auto_takes_precedence_over_manual_check(self):
        """auto key means auto-partition, not manual."""
        finals = [{"disk": {"auto": {"disk": "/dev/sda"}}, "selected_image": "ghcr.io/x:y",
                   "hostname": "h", "encryption": {"use_encryption": False}}]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert "customMounts" not in r or not r.get("customMounts")
        assert r["disk"] == "/dev/sda"


# ── User spec tests ────────────────────────────────────────────────────────────

class TestUserSpec:
    def test_user_propagated(self):
        user = {"username": "alice", "fullname": "Alice Smith", "password": "pass1",
                "groups": ["wheel"]}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["username"] == "alice"
        assert r["user"]["fullname"] == "Alice Smith"
        assert r["user"]["password"] == "pass1"
        assert r["user"]["groups"] == ["wheel"]

    def test_empty_user_when_not_provided(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["username"] == ""

    def test_user_groups_default_empty(self):
        user = {"username": "bob", "password": "p"}
        path = Processor.gen_install_recipe("log", _auto_finals(user=user), _SYS_RECIPE)
        r = _load(path)
        assert r["user"]["groups"] == []


# ── composefs + image_type tests ──────────────────────────────────────────────

class TestComposefs:
    def test_composefs_false_by_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        assert r.get("composeFsBackend", False) is False

    def test_composefs_true_when_set(self):
        path = Processor.gen_install_recipe("log", _auto_finals(composefs=True), _SYS_RECIPE)
        r = _load(path)
        assert r["composeFsBackend"] is True

    def test_image_type_bootc_default(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        r = _load(path)
        # bootc is the default — field may be omitted or set to "bootc"
        assert r.get("imageType", "bootc") == "bootc"

    def test_image_type_ostree(self):
        path = Processor.gen_install_recipe(
            "log", _auto_finals(image_type="ostree"), _SYS_RECIPE)
        r = _load(path)
        assert r.get("imageType") == "ostree"


# ── Misc / edge cases ──────────────────────────────────────────────────────────

class TestMisc:
    def test_returns_path_to_existing_file(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        assert os.path.exists(path)
        assert path.endswith(".json")

    def test_recipe_is_valid_json(self):
        path = Processor.gen_install_recipe("log", _auto_finals(), _SYS_RECIPE)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_multiple_finals_dicts_merged(self):
        finals = [
            {"selected_image": "ghcr.io/x:y"},
            {"hostname": "mergedhost"},
            {"disk": {"auto": {"disk": "/dev/vda"}}},
            {"encryption": {"use_encryption": False}},
        ]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/x:y"
        assert r["hostname"] == "mergedhost"
        assert r["disk"] == "/dev/vda"

    def test_custom_image_url_overrides_selected(self):
        finals = [{
            "custom_image": "ghcr.io/custom/image:tag",
            "selected_image": "ghcr.io/x:y",
            "disk": {"auto": {"disk": "/dev/vda"}},
            "hostname": "h",
            "encryption": {"use_encryption": False},
        }]
        path = Processor.gen_install_recipe("log", finals, _SYS_RECIPE)
        r = _load(path)
        assert r["image"] == "ghcr.io/custom/image:tag"

    def test_sys_recipe_fallback_image(self):
        finals = [{"disk": {"auto": {"disk": "/dev/vda"}}, "hostname": "h",
                   "encryption": {"use_encryption": False}}]
        sys_recipe = {"imgref": "ghcr.io/sys/image:tag"}
        path = Processor.gen_install_recipe("log", finals, sys_recipe)
        r = _load(path)
        assert r["image"] == "ghcr.io/sys/image:tag"
