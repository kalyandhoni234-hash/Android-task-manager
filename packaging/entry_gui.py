"""PyInstaller entry point for the windowed (normal-user) build."""

import sys

from android_task_manager.gui.app import main

if __name__ == "__main__":
    sys.exit(main())