# Third-party notices

Voice Loop's own source is MIT licensed. Dependencies retain their own licenses:

| Component | License / upstream |
| --- | --- |
| Python | [PSF and bundled component licenses](https://docs.python.org/3/license.html) |
| PySide6 Essentials / Shiboken / Qt | [LGPLv3 / upstream license details](https://doc.qt.io/qtforpython-6/licenses.html) |
| NumPy | [BSD 3-Clause and bundled library notices](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| SoundCard | [BSD 3-Clause](https://github.com/bastibe/SoundCard) |
| CFFI | [MIT](https://cffi.readthedocs.io/en/latest/) |
| pycparser | [BSD 3-Clause](https://github.com/eliben/pycparser) |
| keyring and jaraco helpers | [MIT](https://github.com/jaraco/keyring) |
| OpenAI Python SDK | [Apache 2.0](https://github.com/openai/openai-python) |
| Model Context Protocol Python SDK | [MIT](https://github.com/modelcontextprotocol/python-sdk) |
| Python tzdata package | [Apache 2.0; bundled time-zone notices also apply](https://github.com/python/tzdata) |
| more-itertools | [MIT](https://github.com/more-itertools/more-itertools) |
| pywin32-ctypes (Windows) | [BSD 3-Clause](https://github.com/enthought/pywin32-ctypes) |
| PyInstaller bootloader | [GPL with distribution exception](https://pyinstaller.org/en/stable/license.html) |

The packaging specification copies installed dependency license files into the
application's `licenses` data directory. NumPy's notices cover its bundled numerical
libraries. Review notices for the exact artifacts you redistribute.

The OpenAI and MCP SDKs bring their own HTTP, WebSocket, validation, and protocol
dependencies. The packaging specification includes installed license files for
those packages alongside the SDK and tzdata notices. The bundled VoiceLoopMCP
executable shares the app runtime and those notices. API access and cloud model
services are separate from the SDK's open-source license.

Qt, PySide6 and Shiboken are used under LGPLv3. They are dynamically linked in
the onedir app and can be replaced with compatible modified builds. Reverse
engineering for debugging modifications to those libraries is permitted. License
texts are included under `licenses/qt`; the application source and build recipes
are available in this repository. No Qt libraries have been modified.

Upstream corresponding source for the current build (6.11.2):
[Qt base](https://github.com/qt/qtbase/tree/v6.11.2),
[Qt SVG](https://github.com/qt/qtsvg/tree/v6.11.2),
[Qt for Python / Shiboken](https://github.com/qtproject/pyside-pyside-setup/tree/v6.11.2).
Qt's own third-party attribution lists are available in its source tree and
[module documentation](https://doc.qt.io/qt-6/licenses-used-in-qt.html).
Keep equivalent corresponding-source access alongside binaries when distributing releases.

The optional faster-whisper adapter uses separately installed packages and model
files; those are not included in the desktop binary.

Windows installers include the original VB-CABLE package under VB-Audio's
[distribution terms](https://vb-audio.com/Services/licensing.htm). Hi-Fi Cable is
downloaded directly from VB-Audio during setup. Both are VB-Audio donationware;
contributions are welcome. macOS installers include separate BlackHole 2ch/16ch
packages, GPLv3; [source and license](https://github.com/ExistentialAudio/BlackHole).
See `DRIVER-NOTICE.txt` in the app. Driver/model licenses are separate from MIT.
