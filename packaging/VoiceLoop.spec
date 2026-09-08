# Build on each target OS: python -m PyInstaller packaging/VoiceLoop.spec
import sys
import importlib.metadata
import os
from pathlib import Path

root = Path(SPECPATH).parent
notices = [(str(root / "THIRD_PARTY.md"), "."), (str(root / "packaging/licenses"), "licenses")]
for package in ("numpy", "soundcard", "cffi", "pycparser", "pyinstaller", "setuptools", "packaging", "PySide6-Essentials", "shiboken6", "keyring", "jaraco.classes", "jaraco.context", "jaraco.functools", "more-itertools", *( ["pywin32-ctypes"] if sys.platform == "win32" else [] )):
    distribution = importlib.metadata.distribution(package)
    for file in distribution.files or []:
        if any(marker in str(file).lower() for marker in ("license", "copying", "copyright")):
            path = distribution.locate_file(file)
            if path.is_file():
                notices.append((str(path), f"licenses/{package}/{Path(file).parent.name}"))
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    notices.append((str(python_license), "licenses/python"))
resources = root / "src/voiceloop/resources"
extra_binaries = []
if sys.platform == "darwin":
    extra_binaries.append((str(resources / "voiceloop-audio-setup"), "voiceloop/resources"))
if sys.platform == "win32":
    # A build shell may put unrelated programs' ICU/OpenSSL DLLs on PATH. Qt uses
    # Windows' ICU; never resolve dependencies through those unrelated programs.
    os.environ["PATH"] = os.pathsep.join((
        str(Path(sys.executable).parent), sys.base_prefix,
        str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"],
    ))
a = Analysis(
    [str(root / "packaging/entry.py")],
    pathex=[str(root / "src")],
    datas=[(str(root / "LICENSE"), "."), (str(root / "README.md"), "."),
           (str(root / "packaging/DRIVER-NOTICE.txt"), "."),
           *[(str(p), "voiceloop/resources") for p in resources.iterdir() if p.suffix], *notices],
    binaries=extra_binaries,
    hiddenimports=["soundcard", "numpy", "_cffi_backend"],
    excludes=["pytest", "faster_whisper", "tkinter"],
)
if sys.platform == "win32":
    # Windows ICU is an OS component, not the incompatible ICU shipped by tools
    # such as Poppler. This also protects builds using a pre-existing analysis cache.
    a.binaries = [entry for entry in a.binaries
                  if not Path(entry[0]).name.lower().startswith("icu")]
    # Python may bundle an older VC runtime than Qt. The loader resolves the root
    # copy first, so ship Qt's compatible newer runtime at that location as well.
    import PySide6
    qt_directory = Path(PySide6.__file__).parent
    for runtime in qt_directory.glob("*140*.dll"):
        a.binaries = [entry for entry in a.binaries if entry[0].lower() != runtime.name.lower()]
        a.binaries.append((runtime.name, str(runtime), "BINARY"))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VoiceLoop",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VoiceLoop")
if sys.platform == "darwin":
    app = BUNDLE(collection, name="VoiceLoop.app", bundle_identifier="org.voiceloop.desktop",
                 info_plist={
                     "NSMicrophoneUsageDescription": "Voice Loop routes your microphone and saves it only when you choose Record session.",
                     "NSHighResolutionCapable": True,
                 })
