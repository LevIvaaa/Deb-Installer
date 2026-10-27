#!/usr/bin/python3 -I
"""Run the window from the source tree (installing still needs the packaged helper)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from debinstaller.app import main  # noqa: E402

sys.exit(main(sys.argv))
