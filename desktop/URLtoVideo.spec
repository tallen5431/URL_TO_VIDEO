# PyInstaller spec for the desktop app. Build with desktop/build_windows.ps1,
# which first downloads yt-dlp and ffmpeg into desktop/bin.
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "web" / "templates"), "web/templates"),
        (str(ROOT / "desktop" / "bin"), "bin"),
        (str(ROOT / "desktop" / "THIRD_PARTY_NOTICES.txt"), "."),
    ],
    hiddenimports=["desktop.smoke_test"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="URLtoVideo",
    console=False,
    upx=False,  # UPX-packed exes trip antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="URLtoVideo", upx=False)
