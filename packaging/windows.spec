from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
data = collect_data_files("rigora", includes=["resources/**/*", "puppet/FORMAT.md"])
data += collect_data_files("imageio_ffmpeg")
data += copy_metadata("rigora")
a = Analysis(
    [str(root / "packaging" / "windows_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=data,
    hiddenimports=["OpenGL.platform.win32", "OpenGL.arrays.numpymodule"],
    excludes=["cv2", "mediapipe", "sounddevice", "pyvirtualcam", "NDIlib", "pynput"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Rigora",
    debug=False, strip=False, upx=False, console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Rigora")
