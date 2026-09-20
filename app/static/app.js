// This file controls the chat screen and calls the FastAPI routes below.
const byId = (id) => document.getElementById(id);
const messages = byId("messages");
const input = byId("messageInput");
const fileInput = byId("fileInput");
let selectedFile = null;
let busy = false;

function sessionId() {
  let id = localStorage.getItem("zeroqueue_session_id");
  if (!id) {
    id = window.crypto?.randomUUID?.() || `session-${Date.now()}`;
    localStorage.setItem("zeroqueue_session_id", id);
  }
  return id;
}

function addMessage(role, text) {
  byId("welcome")?.remove();
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  if (role === "bot") {
    const avatar = document.createElement("div");
    avatar.className = "bot-avatar";
    avatar.textContent = "ZQ";
    row.appendChild(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "message";
  bubble.textContent = text;
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return row;
}

function showTyping() {
  const row = addMessage("bot", "");
  row.dataset.typing = "true";
  row.querySelector(".message").classList.add("typing");
  row.querySelector(".message").innerHTML = "<i></i><i></i><i></i>";
  return row;
}

function setBusy(value) {
  busy = value;
  byId("sendButton").disabled = value;
  byId("sendButton").querySelector("span").textContent = value ? "Thinking" : "Send";
}

function showFile(file) {
  selectedFile = file;
  byId("filePreview").classList.toggle("hidden", !file);
  byId("fileName").textContent = file?.name || "";
}

function updateTrace(trace = {}) {
  if (!trace || trace.state === "empty") return;
  byId("traceState").textContent = (trace.state || "ready").toUpperCase();
  byId("traceHelp").textContent = "Latest request completed through the grounded retrieval pipeline.";
  byId("retrievalMetric").textContent = trace.retrieval_ms == null ? "-" : `${trace.retrieval_ms} ms`;
  byId("totalMetric").textContent = trace.total_ms == null ? "-" : `${trace.total_ms} ms`;
  byId("confidenceMetric").textContent = trace.confidence_band || "-";
  byId("sourceMetric").textContent = trace.source_count ?? 0;
  const reason = byId("handoffReason");
  reason.textContent = trace.handoff_reason ? `Handoff: ${trace.handoff_reason.replaceAll("_", " ")}` : "";
  reason.classList.toggle("hidden", !trace.handoff_reason);
  const list = byId("sourceList");
  list.replaceChildren();
  (trace.sources || []).forEach((source) => {
    const item = document.createElement("li");
    item.textContent = source.label;
    list.appendChild(item);
  });
  byId("sourceSection").classList.toggle("hidden", !(trace.sources || []).length);
}

async function sendMessage() {
  const text = input.value.trim();
  if (busy || (!text && !selectedFile)) return;
  const file = selectedFile;
  addMessage("customer", text || `(attached ${file.name})`);
  input.value = "";
  input.style.height = "auto";
  showFile(null);
  fileInput.value = "";
  const form = new FormData();
  form.append("session_id", sessionId());
  form.append("message", text);
  if (file) form.append("file", file);
  setBusy(true);
  const typing = showTyping();
  try {
    const response = await fetch("/api/chat", { method: "POST", body: form });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Request failed");
    typing.remove();
    addMessage("bot", body.answer);
    if (body.attachment_note) addMessage("system", `Attachment: ${body.attachment_note}`);
    updateTrace(body.trace);
  } catch (error) {
    typing.remove();
    addMessage("system", `Something went wrong: ${error.message}`);
  } finally { setBusy(false); input.focus(); }
}

async function talkToHuman() {
  if (busy) return;
  setBusy(true);
  const typing = showTyping();
  try {
    const response = await fetch("/api/handoff", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({session_id:sessionId()}) });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Request failed");
    typing.remove();
    addMessage("bot", body.answer);
    updateTrace(body.trace);
  } catch (error) { typing.remove(); addMessage("system", `Something went wrong: ${error.message}`); }
  finally { setBusy(false); }
}

async function checkHealth() {
  const pill = byId("statusPill");
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error();
    const health = await response.json();
    pill.className = "status-pill ok";
    pill.querySelector("span").textContent = `${health.kb_brands} brands online`;
  } catch { pill.className = "status-pill bad"; pill.querySelector("span").textContent = "Offline"; }
}


let lastHumanReplyId = 0;
async function checkHumanReplies() {
  try {
    const response = await fetch(`/api/human-replies/${sessionId()}?after_id=${lastHumanReplyId}`);
    if (!response.ok) return;
    const body = await response.json();
    (body.replies || []).forEach((reply) => {
      lastHumanReplyId = Math.max(lastHumanReplyId, reply.id);
      addMessage("bot", `Human support: ${reply.body}`);
    });
  } catch (_) { /* A quiet poll failure should not interrupt chat. */ }
}

byId("sendButton").addEventListener("click", sendMessage);
byId("humanButton").addEventListener("click", talkToHuman);
byId("attachButton").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => showFile(fileInput.files[0] || null));
byId("removeFile").addEventListener("click", () => { fileInput.value = ""; showFile(null); });
byId("newChatButton").addEventListener("click", () => { localStorage.removeItem("zeroqueue_session_id"); location.reload(); });
input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 110)}px`; });
checkHealth();
setInterval(checkHumanReplies, 5000);
