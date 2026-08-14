"""PyInstaller entry point for the console (diagnostics) build.

Identical to the windowed build, but runs with a visible console and
``ATMAN_DEBUG=1`` so connection-state transitions are echoed to stdout. Meant
for troubleshooting the packaged app; normal users use ``AndroidTaskManager``.
"""

import os
import sys

os.environ.setdefault("ATMAN_DEBUG", "1")

from android_task_manager.gui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())