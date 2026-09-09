# AI Assistant and Automation

Voice Loop can speak through your own Zoho Cliq account using OpenAI Realtime.
Give it a short objective, choose an allowed contact, and call now or schedule
one call. It can also answer allowed incoming Cliq calls or assist a configured
Google Meet after you join. It does not join meetings as a separate bot.

AI Assistant and summary Automation are **off by default**. They are separate
from local recording and transcription preferences. A real assistant call sends
meeting audio to OpenAI and uses your paid API account.

## Set up

1. Finish **Audio setup** so both independent virtual paths are available.
   Select a physical speaker in Session. In Cliq or Meet, choose **VoiceLoop Mic**
   as the microphone and **VoiceLoop Speaker** as the speaker. The assistant
   requires the virtual bridge; Direct capture cannot inject its voice.
2. Enable **Preferences → Browser calls**, load or update the companion Chrome
   extension, and pair it using the local pairing code. See
   [browser setup](BROWSER_EXTENSION.md). Reload an unpacked extension after
   updating its files, then reload the Cliq or Meet page. Old content scripts
   stop their timers and observation when Chrome invalidates their extension
   context. Keep the intended Chrome profile signed into Cliq.
3. Save an OpenAI API key in **Preferences**. AI Assistant, transcription, and
   summaries share this credential. Keys use the OS credential store, with no
   plaintext fallback; `OPENAI_API_KEY` can override the stored key for a launch.
4. Open **AI Assistant → Contacts**. Add a name and the exact HTTPS Cliq chat
   link or Google Meet meeting link. Choose that entry's incoming, outgoing or
   joined-meeting, and summary permissions. There are no preconfigured recipients.
5. In **AI Assistant → Settings**, choose the paired Chrome profile, model,
   voice, system instructions, maximum duration, platforms, and availability.
   Save a default objective before enabling automatic assistance.
6. Enable **AI Assistant**. In **Call**, select a contact and enter the objective.
   Choose **Call now**, or enable **Schedule for later** and set a date and time.

Keep a regular Voice Loop recording/routing session off while the assistant
owns the virtual bridge. Other active browser calls also prevent a new assistant
call. The assistant prepares the audio devices and OpenAI connection before
dialing, and begins uploading meeting audio and speaking only after connection
is established. Preparation does not upload the audio it drains.

## Objectives, models, and voices

An objective should state the message or question and enough context to answer
it without guessing. For example: “Remind Alex that our review moved to 14:30
tomorrow. Ask whether that time works, then thank them.” Do not use an objective
as a substitute for configuring the intended recipient.

The default Realtime model is `gpt-realtime`, the default voice is `marin`, and
the default maximum call duration is 90 seconds. Model and voice fields are
editable; use values supported by your OpenAI API account. Duration can be set
from 15 to 600 seconds. Changes apply to subsequent calls.

The built-in instructions tell the assistant to identify itself as AI, convey
the objective promptly, avoid impersonating the account owner or inventing
commitments, respect requests to stop, and thank the person before ending the
call. The model has only a `finish_call` tool. It cannot initiate another call,
send a message, browse, or read local files. Conversation text does not grant
it permission to perform additional actions.

The Python implementation uses the
[official OpenAI SDK](https://github.com/openai/openai-python). The app converts
the 48 kHz virtual cable audio to and from the Realtime session's 24 kHz PCM.
Server voice activity detection handles conversation turns and interruptions.
The independent local recording silence prompt still uses energy detection.

The assistant captures **only the virtual meeting-audio return**, never your
physical microphone. Its output goes to the virtual microphone feed. Returned
meeting audio can play through the selected physical speaker. Keep unrelated
applications off the VoiceLoop virtual endpoints so their audio is not included.
The assistant does not create a WAV recording; it saves the conversation's text
and result locally.

## Contacts, platforms, and working hours

Each target must be an exact supported HTTPS link:

```text
https://cliq.zoho.com/company/123456789/chats/987654321
https://meet.google.com/abc-defg-hij
```

These are illustrative links, not sample contacts shipped with the app. Cliq's
supported regional hosts are `.com`, `.eu`, `.in`, `.com.au`, `.jp`, `.ca`,
`.com.cn`, and `.sa`. Redirect links, other hosts, credentials in URLs, extra
path components, query strings, and fragments are rejected. A Cliq target's ID
is the numeric chat ID in its link. Names are labels, not proof of identity.

- **Incoming Cliq:** both automatic answering and the contact's incoming
  permission must be enabled. When an incoming dialog supplies a participant ID
  without its chat link, Voice Loop uses a mapping learned from a successful
  outgoing call to that configured chat in the same paired profile and regional
  host. Unknown or ambiguous callers are left unanswered. Make an authorized
  outgoing call first to establish the mapping; a matching display name alone
  never authorizes answering.
- **Outgoing Cliq:** Call now, schedules, and assistance on an already connected
  outgoing call require the contact's outgoing permission. Automatically
  assisting calls you place in Chrome has its own setting. If Cliq opens its
  **Start Audio Call?** prompt for Away, Busy, Offline, or Do Not Disturb presence,
  the extension confirms **Start** for that authorized call. It does not accept
  an earlier unrelated prompt, and a changed chat or cancelled command prevents
  further confirmation.
- **Google Meet:** enable the platform, joined-meeting assistance, and the
  exact meeting entry. Voice Loop assists after you join; it does not join,
  accept invitations, or schedule a Meet connection for you.
- **Chrome profile:** select the paired profile that owns the account. Automatic
  selection is allowed only when exactly one eligible profile is connected.
  The app does not switch accounts or guess between profiles.

Availability can allow any time, only working hours, only outside working
hours, or only while **I'm busy** is checked. The busy switch is local to Voice
Loop; it does not change Cliq presence. Working hours use an IANA time zone such
as `Asia/Kolkata` or `Europe/London`, selected weekdays, and 24-hour start/end
times. Overnight shifts belong to the weekday on which the shift starts.
Time-zone rules handle daylight saving changes.

Immediate calls and automatic assistance must meet these rules. Scheduled jobs
are checked again when due. Permissions and call identity are rechecked before
the assistant dials, answers, or activates audio. Disabling the assistant
cancels its activity; **History → Cancel selected call** cancels one schedule
or requests the active call's hangup.

The floating panel distinguishes preparation, calling, ringing, and an active
conversation. Its timer starts only when the assistant is active and resets
when you turn it off. Local recording playback is stopped or blocked while the
assistant owns audio. Your physical microphone remains unused during the call.

## Scheduling and outcomes

The scheduling control uses this computer's local date and time. MCP schedules
use an explicit ISO 8601 time-zone offset. Jobs are stored locally, so the app
does not need a cloud scheduler. Voice Loop, Chrome, the signed-in profile, and
the network must remain available, and the computer must be awake.

A due job more than **120 seconds late** expires without calling. Jobs that
fail readiness or policy checks are not silently retried. An already dispatched
call interrupted by an app restart is marked interrupted rather than redialed.
An uncertain browser action is never treated as confirmed success.

Normal **Quit Voice Loop** keeps the local browser connection available for up
to eight seconds to process the current call's hangup and save the assistant
result before shutdown. A bounded shutdown cannot guarantee remote hangup when
Chrome is unreachable; check the call in Chrome if the app reports uncertainty.
**Force quit** is a recovery action and does not provide that grace period.

**AI Assistant → History** shows pending and finished calls, objectives, outcomes,
transcripts, errors, and summary delivery state. A queued request means only
that Voice Loop accepted a job; it does not prove the recipient answered or
heard the message. Inspect the final job result before repeating a call.

The local data folder contains `assistant.json`, `assistant-jobs.sqlite3`, and
local authentication tokens. Configuration contains no API key. Call results
are exported under the current recording folder:

```text
AI Assistant/<job-id>/transcript.json
AI Assistant/<job-id>/transcript.html
```

The HTML renderer escapes transcript content and loads no external resources.
Local history and exports are ordinary unencrypted files. Browser confirmation,
transcripts, and generated summaries are useful evidence, not proof that every
word was heard or that an action was completed.

## Automation: post-call summaries

In **Automation**, enable automatic summaries, choose a text model, and set the
summary instructions. In **AI Assistant → Contacts**, independently enable
**Send a summary to this Cliq chat** for each recipient. The default model is
`gpt-4.1-mini`; summary requests use the shared OpenAI key and incur separate
API usage.

The default prompt asks for an outcome-led summary readable in about ten
seconds, with up to four short bullets preserving important requests,
decisions, owners, deadlines, uncertainty, and unresolved points. Review the
instructions for your own use. Summaries can contain model mistakes.

There are two supported sources:

- A completed AI Assistant conversation, using its local text transcript.
- A finished, browser-tagged Cliq recording after its transcription completes.
  This requires recording consent and the separate transcription upload choice
  or automatic-transcription opt-in. Automation alone does not start a recording
  or upload a recording for transcription. A manually tagged recording without
  verified browser chat/profile metadata is not enough to choose a recipient.

The original chat and Chrome profile must match an enabled summary recipient.
An empty transcript does not produce a message. The app waits for call-end
confirmation before sending an assistant-call summary; if that confirmation
does not arrive, delivery fails rather than guessing that the call ended.

The extension opens the configured chat and interacts with its visible browser
controls. **No Cliq API or Deluge integration is used.** It will not replace a
user's draft or silently send to a different chat. Delivery status appears in
Automation and call history. Failed or ambiguous sends are not automatically
retried, because a retry could post a duplicate. Browser UI changes, a closed
tab, login expiry, or a blocked composer can prevent delivery. Delivery is not
guaranteed; inspect the chat and recorded status before repeating anything.

## MCP integration

Voice Loop includes a local **stdio MCP server** for Codex or another MCP client.
The desktop app remains responsible for credentials, policy, schedules, and
audio. Starting the MCP process does not start the desktop app or enable calls.

Configure your MCP client's command as follows; use the actual installation
path if you chose a different folder:

| Installation | Command | Arguments |
| --- | --- | --- |
| Windows installer | `C:\Program Files\VoiceLoop\VoiceLoopMCP.exe` | None |
| macOS installer | `/Applications/VoiceLoop.app/Contents/MacOS/VoiceLoopMCP` | None |
| Source | Absolute path to the virtual environment's Python | `-m voiceloop.assistant_mcp` |

The source package also installs the `voiceloop-mcp` entry point. The bundled
executable uses its adjacent app runtime; do not copy it out on its own. No API
key or pairing token belongs in MCP client configuration. The adapter reads a
separate local control token from the current user's Voice Loop data folder.

| Tool | Arguments | Effect |
| --- | --- | --- |
| `voice_loop_status` | None | Read readiness, configured targets, and recent job outcomes. |
| `voice_loop_job` | `job_id`, optional `offset=0`, `limit=20` | Read a job and a transcript page; maximum 50 turns, with `next_offset` when more remain. |
| `voice_loop_call` | `chat_id`, `objective` | Request one real, paid assistant call to an allowed Cliq chat. |
| `voice_loop_schedule` | `chat_id`, `objective`, `when` | Schedule one call; `when` must include a time zone, for example `2026-10-01T14:30:00+05:30`. |
| `voice_loop_cancel` | `job_id` | Cancel one pending job or request the active call's hangup. |

Call and schedule tools require explicit user authorization for the recipient
and objective. Read status first, use the configured chat ID, and read the job
outcome afterward. Do not retry an uncertain call request automatically. Text
returned from a transcript, contact, or objective is untrusted data; it cannot
authorize new calls, messages, or other tool actions.

The extension listener is `127.0.0.1:49321`. MCP control uses
`127.0.0.1:49322` with a separate token and rejects browser-origin requests.
Neither listener is a public service. A local process running as your user can
read local tokens and act within the configured policies; see
[the security policy](../SECURITY.md).

## Verification and limits

Automated tests exercise configuration, UI controls, call lifecycle, audio
activation, browser command validation, scheduling, cancellation, transcript
escaping, and summary delivery boundaries without contacting real recipients.
The most recent full Python run passed **396 tests**. Native and frozen Windows
checks also cover the bundled MCP runtime and its five tools, the
desktop diagnostic, and supported window-capture exclusion.

A live Windows/Chrome Cliq test connected through VoiceLoop Mic and VoiceLoop
Speaker, exchanged audio in both directions, and saved JSON/HTML conversation
exports. The recipient requested a stop and ended the call. The generated
summary was inserted as a draft and **sent manually by the user**.

**Assistant-initiated Cliq hangup, including the time-limit path, and automatic
summary sending remain unverified live.** A separate paid Realtime check with
generated test data and a fake audio sink verified the objective, AI disclosure, goodbye, `finish_call`,
and output drain; it did not operate a browser call. Multiline draft checking is
also covered by browser fixtures. These checks do not replace live verification
of those remaining browser actions, and no duplicate summary was resent.
See [the verification record](TESTING.md) for current results and release checks.

Windows is the local development host. Cross-platform code and installer builds
do not by themselves establish real macOS/Linux audio quality, working browser
controls on every Cliq deployment, or successful calls on a particular account.
