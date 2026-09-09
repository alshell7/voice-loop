# Security policy

Voice Loop is maintained by **alshell7**. Security fixes target the current
`main` branch and subsequent releases; older prereleases are not maintained separately.

Please [report a vulnerability privately](https://github.com/alshell7/voice-loop/security/advisories/new)
through GitHub's security advisory form. Include the affected version, operating
system, reproduction steps, and expected impact. Avoid public issues for
unfixed vulnerabilities. Response times are best effort for this personal project.

Never attach API keys, private recordings, transcripts, saved contacts, or raw
settings to a report. Use synthetic examples and redact paths/device names in
diagnostics. Credentials are stored in the operating system credential store;
recordings and transcripts are ordinary local files, without app-level encryption.

Cloud transcription uploads audio only after the user's explicit choice or
opt-in automatic transcription setting. An enabled AI Assistant call uploads
the virtual meeting-audio return to OpenAI only after activation on a connected
call; it does not open the physical microphone. Preparing devices and an API
session does not upload pre-call audio. Optional summary generation sends call
text to OpenAI. Treat changes to these gates, path validation, credential storage,
driver downloads, and HTML escaping as security-sensitive.

Optional Chrome detection uses an authenticated HTTP listener bound only to
`127.0.0.1:49321`. Its local pairing token is separate from transcription API
keys and must also be redacted from reports. The extension stores that token
locally, not in Chrome sync. Call metadata travels to the local desktop app.
Review changes to origin/host checks, event validation, and the connected-call
recording gate as security-sensitive. A compromised supported meeting page can
alter its own call UI; DOM detection is not a security attestation of attendance.

AI Assistant additionally permits bounded browser commands: call, answer,
hangup, and send a call summary. Recipient URLs, chat IDs, the paired Chrome
profile, call identity, platform flags, and availability rules are checked
before acting. Unknown incoming participants are not matched by display name;
the app requires an exact chat scope or a participant mapping learned from a
successful outgoing call within the same profile and regional host. Browser DOM
changes can cause failures or uncertainty. Uncertain external actions are not
automatically retried.

MCP control uses a separate token and listener at `127.0.0.1:49322`. It rejects
browser-origin requests and does not return the OpenAI key. The stdio adapter
reads the local token itself; never put a token or API key into client examples,
repository files, command-line arguments, or logs. Local tokens are not a
boundary against malicious processes running as the same OS user. Do not expose
these listeners through a proxy, tunnel, shared port, or remote MCP gateway.

Call and schedule tools perform real external actions and must have explicit
authorization for their recipient and objective. Tool descriptions and model
instructions are defense in depth, not a replacement for host approval or the
desktop's policy checks. Objectives, browser text, transcripts, names, and
summaries are untrusted data; they must not authorize follow-on tool calls.
The Realtime model can request only the current call's completion. Summary
generation produces text, without browser tools or arbitrary code execution.

Automation posts text to a real Cliq chat only when its global setting and the
recipient's summary permission are enabled. It uses the original recorded chat
and profile, waits for the call to finish, preserves existing drafts, and records
delivery status. Browser-tagged recording summaries additionally require a
completed recording and transcription; Automation alone grants neither recording
nor transcription consent. Redact the job journal, participant mappings, control
tokens, and assistant JSON/HTML exports when reporting bugs. They may contain
private contacts, objectives, conversation text, or account identifiers.

Optional window capture exclusion is a presentation privacy aid, not a security
boundary. Windows restricts supported OS capture paths; macOS ScreenCaptureKit
can ignore the legacy flag, and Linux is unsupported. It does not protect saved
files or accessibility text. See [capture protection](docs/CAPTURE_PROTECTION.md).
