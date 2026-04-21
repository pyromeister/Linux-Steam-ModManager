#!/usr/bin/env python3
"""GUI entry point for Linux Steam ModManager."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gui.app import main

if __name__ == "__main__":
    main()
