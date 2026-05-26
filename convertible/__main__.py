"""Entry point for ``python -m convertible``."""

from __future__ import annotations

import sys

from convertible.cli import main

if __name__ == "__main__":
    sys.exit(main())
