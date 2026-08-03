"""Compatibility launcher for the installed, self-contained demo command."""

import sys

from avialsync.__main__ import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "demo"]
    main()
