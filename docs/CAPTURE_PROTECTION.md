# Capture protection

Voice Loop 0.4.1 adds **Preferences → Screen privacy → Hide Voice Loop from screen
capture**. It is an opt-in, saved preference. It applies immediately, including
to already-open windows, and turning it off restores normal capture. It does
not change audio recording, transcription, playback, or browser call detection.

The main window, floating controls, their app-owned dialogs and dropdowns use
the same setting. Protection is reapplied when a window opens or Qt replaces
its native handle. The status below the setting reports native API failures;
a checked box alone is not proof that the OS applied protection.

## Platform behavior

| Platform | Behavior |
| --- | --- |
| Windows 10 2004+ / Windows 11 | Uses `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`. Supported OS capture paths omit the window. |
| Older Windows | The OS can substitute a black rectangle. These Windows versions are outside the current app's tested support. |
| macOS | Sets `NSWindow.sharingType` to `NSWindowSharingNone`, matching Electron's legacy behavior. Modern ScreenCaptureKit capture ignores it; the UI explicitly reports this limitation. |
| Linux / non-native Qt sessions | Unavailable; no protection is claimed. |

This is **not an absolute security guarantee**. Microsoft limits the API to a
set of public capture mechanisms, and Electron documents the macOS exception.
It cannot prevent a camera filming the display, privileged/custom capture paths,
accessibility text access, or access to saved audio/transcript files. System-owned
dialogs, browser windows and transcript HTML opened in another app are not covered.

Sources: [Microsoft's display-affinity API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity),
[Electron content protection](https://www.electronjs.org/docs/latest/api/browser-window#winsetcontentprotectionenable-macos-windows),
[Qt native window types](https://doc.qt.io/qt-6/qtdoc-demos-windowembedding-example.html).

## Verification

Unit tests cover live toggles, application ownership, new dialogs, recreated
handles, hide/show, native failure reporting and recovery, unsupported sessions,
typed persisted settings, and the actual Preferences control.

The native diagnostic uses only synthetic UI and temporary local data. It opens
no audio, makes no network requests, and changes no personal settings. It checks
the actual native setting on the main window, floating controls, dialogs, and
completion/mode popups, then verifies disable and hide/resize behavior.

```powershell
$env:QT_QPA_PLATFORM = 'windows'
python -m voiceloop check-capture --pixels --output artifacts/capture.json
# After building the Windows bundle:
powershell -NoProfile -File scripts/smoke_packaged.ps1 -Check check-capture -Pixels
```

The optional Windows pixel test takes actual desktop screenshots over a solid
test background. With protection off, app pixels appear; with it on, only the
background appears; turning it off restores the app pixels. It does not use
`QWidget.grab()`, which renders the widget directly and cannot prove OS exclusion.
Keep the synthetic test windows unobstructed while this short check runs.

On macOS, use a native Cocoa session:

```sh
QT_QPA_PLATFORM=cocoa python -m voiceloop check-capture --output artifacts/capture.json
```

This checks the legacy native flag only and does not claim ScreenCaptureKit
exclusion. Installer CI runs native flag checks against all three frozen apps.
Local Windows checks additionally exercise real desktop pixels and Windows
Graphics Capture. See [the verification record](TESTING.md) for observed results.
