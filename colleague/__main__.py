"""Entry point for ``python -m colleague``."""

from __future__ import annotations

import sys

from colleague.cli import main

if __name__ == "__main__":
    sys.exit(main())
