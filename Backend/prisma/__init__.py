"""Compatibility package exposing ``src.prisma`` as top-level ``prisma``."""

from pathlib import Path

_SRC_PRISMA = Path(__file__).resolve().parent.parent / "src" / "prisma"

# Reuse the real package directory so imports like ``prisma.engine`` keep working.
__path__ = [str(_SRC_PRISMA)]
