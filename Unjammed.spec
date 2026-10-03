# PyInstaller build: one folder with Unjammed.exe (window + background/admin roles) and unjammed-cli.exe (terminal).
# Build with build.ps1 (clean venv from the hash-pinned requirements.lock), not by hand.
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

VERSION = re.search(r'__version__ = "([\d.]+)"', Path("storemgr/__init__.py").read_text(encoding="utf-8")).group(1)
NUMS = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])


def version_info(description, name):
    strings = [("CompanyName", "Unjammed contributors"), ("FileDescription", description), ("FileVersion", VERSION),
               ("InternalName", name), ("OriginalFilename", f"{name}.exe"), ("ProductName", "Unjammed"),
               ("ProductVersion", VERSION), ("LegalCopyright", "MIT licence")]
    return VSVersionInfo(ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
                         kids=[StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings])]),
                               VarFileInfo([VarStruct("Translation", [1033, 1200])])])


common = dict(pathex=["."], datas=[("assets", "assets")], excludes=["tkinter", "PIL", "pytest", "PyInstaller"])
gui = Analysis(["main.py"], **common)
cli = Analysis(["cli.py"], **common)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="Unjammed", console=False,
              icon="assets/icon.ico", version=version_info("Unjammed", "Unjammed"))
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="unjammed-cli", console=True,
              icon="assets/icon.ico", version=version_info("Unjammed command line", "unjammed-cli"))

COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="Unjammed")
