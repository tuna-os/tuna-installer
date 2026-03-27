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
        disk_info = merged.get("disk", {})
        disk_device = ""
        filesystem = "xfs"
        btrfs_subvolumes = False

        if isinstance(disk_info, dict):
            if "disk" in disk_info:
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
                if key:
                    encryption_type = "luks-passphrase"
                    encryption_passphrase = key
                else:
                    encryption_type = "tpm2-luks"
            if "type" in enc_info:
                encryption_type = enc_info["type"]
            if "passphrase" in enc_info:
                encryption_passphrase = enc_info["passphrase"]

        # --- Image / OCI ref ---
        image = merged.get("custom_image", "")
        if not image:
            image = sys_recipe.get("imgref", "")
        if not image:
            image = sys_recipe.get("image", "")
        if not image:
            logger.warning("No image/imgref found in finals or sys_recipe!")

        target_imgref = sys_recipe.get("targetImgref", "")

        # --- Hostname ---
        hostname = merged.get("hostname", sys_recipe.get("hostname", "tunaos"))

        # --- SELinux / unified storage ---
        selinux_disabled = sys_recipe.get("selinuxDisabled", False)
        unified_storage = sys_recipe.get("unifiedStorage", False)

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
        }

        logger.info(f"Generated fisherman recipe: disk={disk_device}, image={image}, encryption={encryption_type}")

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="tuna-recipe-",
            delete=False,
        ) as f:
            json.dump(recipe, f, indent=2)
            recipe_path = f.name

        logger.info(f"Fisherman recipe written to {recipe_path}")
        return recipe_path
