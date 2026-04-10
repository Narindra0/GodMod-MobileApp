"""Compatibility package exposing ``src.core`` as top-level ``core``."""

from pathlib import Path

_SRC_CORE = Path(__file__).resolve().parent.parent / "src" / "core"

# Reuse the real package directory so imports like ``core.database`` keep working.
__path__ = [str(_SRC_CORE)]

