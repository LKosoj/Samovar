"""
Use "python -m cppcheck" to make the package executable.
"""

from __future__ import annotations

from cppcheck import cppcheck

if __name__ == "__main__":
    cppcheck()
