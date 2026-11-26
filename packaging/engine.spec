# PyInstaller spec: one-folder build of the engine. Run from the repo root.
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], [
    "pynput.keyboard._win32", "pynput.mouse._win32", "comtypes.stream",
]
for pkg in ("faster_whisper", "ctranslate2", "soundcard", "_soundfile_data", "soxr", "pycaw", "comtypes",
            "pynput"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(["engine_entry.py"], pathex=[os.path.dirname(SPECPATH)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="teams-listener-engine", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="teams-listener-engine")
