"""Test that every .py file in each tuna_installer subpackage is listed in
its meson.build sources array.

This catches the class of bug where a new .py file is added but forgotten
in meson.build, causing ModuleNotFoundError only after the Flatpak is
built and installed (invisible when running from source).
"""

import os
import re
import sys
from pathlib import Path

import pytest

# Repo root is three levels up from tests/unit/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PKG_ROOT = _REPO_ROOT / "tuna_installer"


def _meson_sources(meson_build_path: Path) -> set[str]:
    """Parse the `sources = [...]` block from a meson.build file."""
    text = meson_build_path.read_text()
    m = re.search(r"sources\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return set()
    items = re.findall(r"'([^']+)'", m.group(1))
    return set(items)


def _py_files_in(directory: Path) -> set[str]:
    """Return the set of .py filenames directly in ``directory`` (non-recursive)."""
    return {f.name for f in directory.iterdir() if f.is_file() and f.suffix == ".py"}


def _find_meson_dirs() -> list[tuple[Path, Path]]:
    """Return (directory, meson.build path) pairs for all subpackages."""
    pairs = []
    for meson_path in _PKG_ROOT.rglob("meson.build"):
        pairs.append((meson_path.parent, meson_path))
    return pairs


@pytest.mark.parametrize("directory,meson_path", _find_meson_dirs(),
                         ids=lambda p: str(p.relative_to(_REPO_ROOT)) if isinstance(p, Path) else str(p))
def test_meson_build_lists_all_py_files(directory, meson_path):
    """Every .py file in the directory must appear in the meson.build sources."""
    actual_files = _py_files_in(directory)
    if not actual_files:
        pytest.skip("No .py files in directory")

    meson_sources = _meson_sources(meson_path)
    if not meson_sources:
        pytest.skip("No sources list found in meson.build")

    missing = actual_files - meson_sources
    assert not missing, (
        f"{meson_path.relative_to(_REPO_ROOT)} is missing these .py files:\n"
        + "\n".join(f"  {f}" for f in sorted(missing))
        + "\nAdd them to the sources list."
    )
