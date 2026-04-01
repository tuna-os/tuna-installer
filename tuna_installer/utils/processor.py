# processor.py
#
# Copyright 2024 TunaOS contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation at version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import os
import tempfile

logger = logging.getLogger("Installer::Processor")


class Processor:
    @staticmethod
    def gen_install_recipe(log_path: str, finals: list, sys_recipe: dict) -> str:
        """Generate a fisherman recipe JSON from the UI's collected finals.

        Args:
            log_path: path for the installation log (unused by fisherman, kept for API compat)
            finals: list of dicts collected from each installer step's get_finals()
            sys_recipe: the loaded system recipe (from /etc/tunaos-installer/recipe.json)

        Returns:
            Path to a temporary JSON file containing the fisherman recipe.
        """
        # Merge all finals dicts into one flat dict
        merged = {}
        for step_finals in finals:
            if isinstance(step_finals, dict):
                merged.update(step_finals)

        logger.info(f"Building fisherman recipe from finals: {list(merged.keys())}")

        # --- Disk ---
        # disk_info comes from VanillaDefaultDisk.get_finals() as one of:
        #   Auto:   {"auto": {"disk": "/dev/vda", ...}}
        #   Manual: {"/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"}, "/dev/sda2": {...}, ...}
        disk_info = merged.get("disk", {})
        disk_device = ""
        filesystem = "xfs"
        btrfs_subvolumes = False
        custom_mounts = []

        is_manual = (
            isinstance(disk_info, dict)
            and disk_info
            and all(k.startswith("/dev/") for k in disk_info)
        )

        if is_manual:
            for partition, spec in disk_info.items():
                fstype = spec.get("fs", "unformatted") or "unformatted"
                mountpoint = spec.get("mp", "")
                if not mountpoint:
                    continue
                custom_mounts.append({
                    "partition": partition,
                    "target": mountpoint,
                    "fstype": fstype,
                })
            logger.info(f"Manual partition layout: {len(custom_mounts)} mounts")
        elif isinstance(disk_info, dict):
            if "auto" in disk_info:
                disk_device = disk_info["auto"].get("disk", "")
            elif "disk" in disk_info:
                disk_device = disk_info["disk"]
            elif "device" in disk_info:
                disk_device = disk_info["device"]
            fs = disk_info.get("filesystem", "xfs")
            if fs in ("xfs", "btrfs"):
                filesystem = fs
            if filesystem == "btrfs":
                btrfs_subvolumes = disk_info.get("btrfsSubvolumes", False)
        elif isinstance(disk_info, str):
            disk_device = disk_info

        logger.info(f"Selected disk: {disk_device}, filesystem: {filesystem}")

        # --- Encryption ---
        enc_info = merged.get("encryption", {})
        encryption_type = "none"
        encryption_passphrase = ""

        if isinstance(enc_info, dict):
            use_enc = enc_info.get("use_encryption", False)
            if use_enc:
                key = enc_info.get("encryption_key", "")
                explicit_type = enc_info.get("type", "")
                if explicit_type in ("luks-passphrase", "tpm2-luks-passphrase", "tpm2-luks"):
                    encryption_type = explicit_type
                    encryption_passphrase = key
                elif key:
                    encryption_type = "luks-passphrase"
                    encryption_passphrase = key
                else:
                    encryption_type = "tpm2-luks"

        # --- Image / OCI ref ---
        # In Flatpak mode: finals contain "selected_image" or "custom_image" from the UI.
        # In live ISO mode: the image step is skipped; recipe["imgref"] holds the local image.
        image = merged.get("custom_image", "") or merged.get("selected_image", "")
        if not image:
            image = sys_recipe.get("imgref", "")
        if not image:
            # Fall back to first default-marked image in the recipe images list
            for img in sys_recipe.get("images", []):
                if img.get("default", False):
                    image = img.get("imgref", "")
                    break
        if not image and sys_recipe.get("images"):
            image = sys_recipe["images"][0].get("imgref", "")
        if not image:
            logger.warning("No image/imgref found in finals or sys_recipe!")

        target_imgref = f"docker://{image}" if image else ""

        # --- Hostname ---
        hostname = merged.get("hostname", sys_recipe.get("hostname", "tunaos"))

        # --- Flatpaks ---
        flatpaks = merged.get("flatpaks", [])

        # --- SELinux / unified storage ---
        selinux_disabled = sys_recipe.get("selinuxDisabled", False)
        unified_storage = sys_recipe.get("unifiedStorage", False)

        # --- User account ---
        user_info = merged.get("user", {})
        user_username = user_info.get("username", "")
        user_fullname = user_info.get("fullname", "")
        user_password = user_info.get("password", "")
        user_groups   = user_info.get("groups", [])

        # Build the fisherman recipe
        recipe = {
            "disk": disk_device,
            "filesystem": filesystem,
            "btrfsSubvolumes": btrfs_subvolumes,
            "encryption": {
                "type": encryption_type,
                "passphrase": encryption_passphrase,
            },
            "image": image,
            "targetImgref": target_imgref,
            "selinuxDisabled": selinux_disabled,
            "unifiedStorage": unified_storage,
            "hostname": hostname,
            "flatpaks": flatpaks,
            "user": {
                "username": user_username,
                "fullname": user_fullname,
                "password": user_password,
                "groups": user_groups,
            },
        }
        if custom_mounts:
            recipe["customMounts"] = custom_mounts

        logger.info(f"Generated fisherman recipe: disk={disk_device}, image={image}, encryption={encryption_type}")

        # In a Flatpak sandbox /tmp and /run/user/ are private and not visible on the host.
        # With --filesystem=host, $HOME is shared. Use ~/.cache/tuna-installer/ so that
        # flatpak-spawn --host can read the recipe file from the host side.
        in_flatpak = os.path.exists("/.flatpak-info")
        if in_flatpak:
            cache_dir = os.path.join(os.environ.get("HOME", "/root"), ".cache", "tuna-installer")
            os.makedirs(cache_dir, exist_ok=True)
            tmp_dir = cache_dir
        else:
            tmp_dir = None

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="tuna-recipe-",
            dir=tmp_dir,
            delete=False,
        ) as f:
            json.dump(recipe, f, indent=2)
            recipe_path = f.name

        logger.info(f"Fisherman recipe written to {recipe_path}")
        return recipe_path
