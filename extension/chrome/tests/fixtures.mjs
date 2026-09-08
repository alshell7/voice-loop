// Anonymized visible-call snapshots; no real contacts, account IDs, or chat data.
export const outgoing = {
  provider: "zoho_cliq", url: "https://cliq.zoho.com/",
  callPanel: true, hangup: true, dialing: true, incoming: false,
  elapsed: -1, contact: "Test Contact", title: "Call with Test Contact",
};
export const incoming = {...outgoing, dialing: false, incoming: true};
export const connected = {...outgoing, dialing: false, elapsed: 1};
export const meetPreview = {
  provider: "google_meet", url: "https://meet.google.com/abc-defg-hij?authuser=1#private",
  meetingPath: true, hangup: false, preview: true, title: "Weekly planning", contact: "",
};
export const meetJoined = {...meetPreview, hangup: true, preview: false};
