# recipe.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
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
import subprocess
import sys
from gettext import gettext as _

logger = logging.getLogger("Installer::RecipeLoader")


class RecipeLoader:
    recipe_paths = [
        "/etc/tunaos-installer/recipe.json",
        "/etc/vanilla-installer/recipe.json",
        "/app/share/bootc-installer/recipe.json",
    ]
    recipe_path = None

    def __init__(self):
        self.__recipe = {}
        self.__load()

    def __load(self):
        if "VANILLA_CUSTOM_RECIPE" in os.environ:
            self.recipe_paths = [os.environ["VANILLA_CUSTOM_RECIPE"]]

        for path in self.recipe_paths:
            if os.path.exists(path):
                self.recipe_path = path
                with open(path, "r") as f:
                    self.__recipe = json.load(f)
                if self.__validate():
                    self.__enrich()
                    return
                logger.warning(f"Recipe at {path} failed validation, trying next...")

        logger.error(f"No valid recipe found. Tried: {self.recipe_paths}")
        sys.exit(1)

    def __enrich(self):
        """Post-load enrichment: detect live ISO mode and inject local bootc image."""
        in_flatpak = os.path.exists("/.flatpak-info")
        is_ostree_booted = os.path.exists("/run/ostree-booted")
        live_iso_mode = not in_flatpak and is_ostree_booted

        if live_iso_mode:
            imgref = self.__recipe.get("imgref", "") or self.__detect_local_bootc_image()
            if imgref:
                logger.info(f"Live ISO mode: using local bootc image {imgref}")
                self.__recipe["imgref"] = imgref
            else:
                logger.warning("Live ISO mode: could not detect local bootc image")

            # Remove the image selection step — use the local image silently
            self.__recipe["steps"].pop("image", None)
            logger.info("Live ISO mode: image selection step removed")
        else:
            logger.info("Flatpak/normal mode: image selection enabled")

    def __detect_local_bootc_image(self) -> str:
        """Run bootc status to find the currently booted image reference."""
        try:
            result = subprocess.run(
                ["bootc", "status", "--format", "json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # bootc status JSON: .status.booted.image.image.image
                imgref = (
                    data.get("status", {})
                        .get("booted", {})
                        .get("image", {})
                        .get("image", {})
                        .get("image", "")
                )
                if imgref:
                    logger.info(f"Detected local bootc image via bootc status: {imgref}")
                    return imgref
        except Exception as e:
            logger.warning(f"bootc status failed: {e}")
        return ""

        logger.error(f"No valid recipe found. Tried: {self.recipe_paths}")
        sys.exit(1)

    def __validate(self):
        essential_keys = ["log_file", "distro_name", "distro_logo", "steps"]
        if not isinstance(self.__recipe, dict):
            logger.error(_("Recipe is not a dictionary"))
            return False

        for key in essential_keys:
            if key not in self.__recipe:
                logger.error(_(f"Recipe is missing the '{key}' key"))
                return False

        if not isinstance(self.__recipe["steps"], dict):
            logger.error(_("Recipe steps is not a dictionary"))
            return False

        for step_key, step in self.__recipe["steps"].items():
            if not isinstance(step, dict):
                logger.error(_(f"Step {step_key} is not a dictionary"))
                return False

        return True

    @property
    def raw(self):
        return self.__recipe
