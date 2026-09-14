"""Tiny, dependency-free path helpers shared by both preprocess scripts.

Deliberately has no scipy/pandas/skimage imports: viz_preprocess_lite.py runs
under Blender's bundled Python, which lacks those packages, so anything it
imports (directly or transitively) must stay minimal.
"""

from __future__ import annotations

import os
from pathlib import Path


def manifest_relpath(target: Path, base: Path) -> str:
    """Path to ``target`` relative to ``base``, or absolute across Windows drives."""
    try:
        return os.path.relpath(target, base).replace(os.sep, "/")
    except ValueError:
        return str(target).replace(os.sep, "/")
