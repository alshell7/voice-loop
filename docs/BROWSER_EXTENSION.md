# Chrome call companion

Voice Loop 0.4 adds an optional Chrome extension for Zoho Cliq and Google Meet.
It detects call state and sends meeting details to the desktop app on the same
computer. It does not join meetings, capture browser audio, or send data to a
Voice Loop service. Audio still goes through the desktop app's selected devices.

## Install and pair

1. Install or run the desktop version matching your extension (0.5.3 or newer). Select your physical microphone and
   speaker in Session and check the meeting app's audio device settings.
2. Open **Preferences → Browser calls** and enable **Detect calls from the paired
   Chrome extension**. Leave **Automatically record connected calls** off initially.
3. Get `VoiceLoop-<version>-chrome.zip` from the same GitHub release and extract it
   to a permanent folder. From a source checkout, use `extension/chrome` directly.
4. Open Chrome's **Extensions → Manage extensions** (`chrome://extensions`), enable
   **Developer mode**, select **Load unpacked**, and choose the folder containing
   `manifest.json`. In the ZIP this folder is named `voice-loop-chrome`.
5. Open the Voice Loop extension from Chrome's toolbar. In the desktop preferences,
   click **Copy code**, paste it into the extension's pairing field, and connect.
   The pairing code is local to this computer; it is not an OpenAI API key.
6. Reload existing Cliq and Meet tabs once, while no call is active. Keep the
   desktop app running; minimizing it to the tray is fine.

Chrome remembers the unpacked folder, so keep it in place. After updating its
files, click **Reload** on its extension card and reload the meeting tabs. A
managed browser may require your administrator to allow developer extensions.
The extension has not been published to the Chrome Web Store.

Pairing immediately registers this Chrome profile in **AI Assistant**, even with
no meeting tabs open. Opening the extension popup checks and refreshes its
registration; this does not start a call. Background heartbeats keep the profile
active while Chrome and the desktop app are running. Profiles disappear after
45 seconds without a heartbeat, and return after communication resumes. If the
profile is missing, open the extension popup to refresh its status. Update both
the desktop app and extension together: an older desktop app cannot accept the
new registration protocol.

Chrome's official [unpacked-extension instructions](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked)
describe this installation flow. Windows and macOS use the same extension folder.

## What starts a recording

| Browser event | Voice Loop behavior |
| --- | --- |
| Incoming Cliq call is ringing | Floating status shows the caller; no recording. |
| Outgoing Cliq call is dialing/ringing | Floating status shows the contact being called; no recording. |
| Cliq call is answered | Prompt to record, or record automatically if that preference is enabled. |
| Google Meet preview/waiting room | No recording. |
| Google Meet is joined | Prompt to record, or record automatically if enabled. |
| A detected call ends or its tab closes | Save and finish the recording that this call started. |
| A manual session is already active | Show the detected call status; keep the manual session under your control. |

Choose **Record call** or **Not this call** in the popup. Ignoring the popup does
not start capture. Turning a recording off manually suppresses another prompt or
automatic restart for that same call. The prompt closes if the call ends before
you respond. A later call can prompt again.

The extension reports the caller/contact name for Cliq, the direction when it is
known, and the Meet title. An unscheduled Meet may expose only its meeting code,
which becomes the title. Names come from the call interface; the extension does
not search chat history or address books. Missing details are left blank rather
than guessed. Session manifests preserve the received details, including a
contact email if a detector provides one; the built-in detector primarily uses
display names. Contact names are also saved in Voice Loop's local contact list.

Supported Cliq regions are `.com`, `.eu`, `.in`, `.com.au`, `.jp`, `.ca`, `.com.cn`,
and `.sa`. Teams, Zoom, native Cliq applications, and other browsers are not yet
covered. Current call labels target the English interfaces; providers can change
their DOM, so check behavior after their UI updates.

## Audio and recording preferences

Call detection decides when to start the existing desktop recorder. It cannot
select meeting-app audio devices for you. In Direct capture the meeting app uses
your physical devices. In Virtual bridge it uses **VoiceLoop Mic** and
**VoiceLoop Speaker**. Those virtual paths carry audio only while Voice Loop is
on. If you need routing before answering, turn on **Route only** manually; that
manual session remains under your control, including the decision to record.

Automatic recording and automatic OpenAI transcription are independent. Enabling
the former saves local audio; if you have also enabled automatic transcription,
the finished recording follows that separate upload preference. The extension
has no access to your transcription key or recording files.

## Local transport and failure behavior

When enabled, the desktop listens only on `127.0.0.1:49321`. The extension service
worker sends authenticated requests, consistent with Chrome's
[extension network-request model](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests).
It stores the pairing code in local extension storage, not Chrome sync or a web
page. The desktop stores it as `browser-pairing-token` in its per-user data folder.
Do not share or commit this file. Turn off detection, quit Voice Loop, remove that
file, and enable detection again to generate a new code and revoke old pairings.

Only call events and an authenticated health check are exposed. There is no
remote playback, file-download, transcription, or API-key endpoint. Requests are
bounded and validate the host, origin, token, provider, timestamp, and event shape.
Contact details and tokens are not written to HTTP logs.

Active calls send heartbeats. If the browser disappears and no heartbeat arrives
for 45 seconds, Voice Loop finishes its call-owned recording and reports the
lost connection. Pending prompts are dismissed. This may also occur if Chrome
suspends a tab for an extended period. Duplicate or old events do not restart a
recording. Calls from multiple tabs cannot take over an existing recording.

If the extension cannot connect, confirm the desktop is running and detection is
enabled, then check the pairing code. A port-in-use error is shown in Preferences;
close another Voice Loop instance or the conflicting local program. There is no
fallback to a remote server. Do not change firewall or browser security settings
to work around connection errors.

## Development and verification

Use Python 3.11+ and Node 24.15+ for the development checks. `jsdom` is a
test-only dependency for parsing sanitized provider HTML; the extension itself
has no runtime dependencies.

```sh
python -m pytest tests/test_browser_bridge.py tests/test_call_detection.py tests/test_browser_ui.py
npm ci --ignore-scripts --prefix extension/chrome
node --test extension/chrome/tests/*.test.mjs
python scripts/smoke_browser.py
python scripts/build_extension.py
```

The build script checks desktop/extension version agreement and archives an
explicit list of runtime files, the README, and MIT license. It excludes tests,
local tokens, dependencies, and recordings. GitHub main releases attach the ZIP
and its SHA-256 sidecar alongside the native installers.

The protocol is documented in the [extension README](../extension/chrome/README.md).
See [TESTING.md](TESTING.md) for the distinction between automated coverage and
live browser/audio verification. A detector fixture is not proof of a real
attended call; verify both the browser's call state and the saved desktop session.
