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
opt-in automatic transcription setting. Treat changes to upload consent, path
validation, credential storage, driver downloads, and HTML escaping as security-sensitive.

Optional Chrome detection uses an authenticated HTTP listener bound only to
`127.0.0.1:49321`. Its local pairing token is separate from transcription API
keys and must also be redacted from reports. The extension stores that token
locally, not in Chrome sync. Call metadata travels only to the local desktop app.
Review changes to origin/host checks, event validation, and the connected-call
recording gate as security-sensitive. A compromised supported meeting page can
alter its own call UI; DOM detection is not a security attestation of attendance.
