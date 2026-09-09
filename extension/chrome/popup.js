"use strict";
const $ = id => document.getElementById(id);
const providerNames = {zoho_cliq: "Zoho Cliq", google_meet: "Google Meet"};
const stateNames = {ringing: "Incoming call · waiting for you", dialing: "Outgoing call · waiting for an answer", connected: "Call attended", ended: "Call ended"};
function showError(message = "") { $("error").textContent = message; $("error").hidden = !message; }
async function send(message) {
  try { return await chrome.runtime.sendMessage(message); }
  catch { return {ok: false, message: "The extension is restarting. Close this panel and open it again."}; }
}
function render(result) {
  if (!result || typeof result.paired !== "boolean") { showError(result?.message || "Could not check connection."); return; }
  const {paired, connection, call} = result;
  $("pairing").hidden = paired;
  $("paired").hidden = !paired;
  $("status").textContent = paired ? (connection.ok ? "Connected to desktop" : "Desktop unavailable") : "Not connected";
  $("indicator").dataset.connected = String(paired && connection.ok);
  if (paired && !connection.ok) showError(connection.message);
  else showError();
  $("call-details").hidden = !call;
  $("call-heading").textContent = call?.contact?.name || call?.title || "Ready for your next call";
  $("call-detail").textContent = call ? "Follow this call in your Voice Loop floating controls." : "Zoho Cliq calls and Google Meet meetings appear in your floating controls.";
  $("call-provider").textContent = providerNames[call?.provider] || "";
  $("call-state").textContent = stateNames[call?.state] || "";
  $("profile-id").textContent = paired ? `Profile · ${result.profileId || "Reopen the extension to initialize"}` : "";
}
async function refresh(check = false) { render(await send({type: "status", check})); }
$("pair-form").addEventListener("submit", async event => {
  event.preventDefault(); showError();
  $("connect").disabled = true; $("connect").textContent = "Connecting…";
  const result = await send({type: "pair", token: $("token").value});
  $("connect").disabled = false; $("connect").textContent = "Connect to Voice Loop";
  if (result.ok) { $("token").value = ""; await refresh(); $("recheck").focus(); }
  else showError(result.message);
});
$("recheck").addEventListener("click", async () => {
  $("recheck").disabled = true; await refresh(true); $("recheck").disabled = false;
});
$("disconnect").addEventListener("click", async () => {
  $("disconnect").disabled = true; const result = await send({type: "unpair"}); $("disconnect").disabled = false;
  if (!result.ok) showError(result.message); else { await refresh(); $("token").focus(); }
});
chrome.storage.onChanged.addListener((_changes, area) => { if (area === "session") void refresh(); });
void refresh(true);
