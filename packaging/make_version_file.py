"""Writes the PyInstaller ``--version-file`` resource for the Windows builds.

The version is read from the single authoritative source
(``android_task_manager.__version__``, i.e. ``src/android_task_manager/__init__.py``).
The rendered VSVersionInfo literal is written to
``packaging/build/version_info.txt``, which ``packaging/build_windows.ps1``
passes to PyInstaller for both the windowed and the debug build.

Run from the repository root (the package is already installed in the build
venv, or ``src`` is added to ``sys.path`` here for standalone use):

    python packaging/make_version_file.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from android_task_manager import __version__  # noqa: E402


def _parts(version: str) -> tuple[int, int, int, int]:
    nums = [int(part) for part in version.split(".")]
    nums.extend([0] * (4 - len(nums)))
    return tuple(nums[:4])  # type: ignore[return-value]


def main() -> None:
    out = ROOT / "packaging" / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)

    filevers = _parts(__version__)
    file_version = ", ".join(str(n) for n in filevers)

    content = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers=({file_version}),\n"
        f"    prodvers=({file_version}),\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        '        u"040904B0",\n'
        "        [StringStruct(u'CompanyName', u'Android Task Manager project'),\n"
        "         StringStruct(\n"
        "             u'FileDescription',\n"
        "             u'Android Task Manager - Android system monitor for Windows'),\n"
        f"         StringStruct(u'FileVersion', u'{file_version}'),\n"
        "         StringStruct(u'InternalName', u'AndroidTaskManager'),\n"
        "         StringStruct(u'LegalCopyright', u'MIT License'),\n"
        "         StringStruct(u'OriginalFilename', u'AndroidTaskManager.exe'),\n"
        "         StringStruct(u'ProductName', u'Android Task Manager'),\n"
        f"         StringStruct(u'ProductVersion', u'{__version__}'),\n"
        "         StringStruct(\n"
        "             u'Comments',\n"
        "             u'Monitoring via ADB; device actions: Open App, App Info, Force Stop')])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )
    out.write_text(content, encoding="utf-8")
    print(f"Wrote {out} (version {__version__})")


if __name__ == "__main__":
    main()