#!/usr/bin/env python3
"""Compatibility entry point for the dependency-free Code Linter."""

from __future__ import annotations

import sys

from code_linter import *  # noqa: F403


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))  # noqa: F405
