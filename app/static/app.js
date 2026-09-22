// This file controls the chat screen and calls the FastAPI routes below.
const byId = (id) => document.getElementById(id);
const messages = byId("messages");
const input = byId("messageInput");
const fileInput = byId("fileInput");
let selectedFile = null;
let selectedPreviewUrl = null;
let busy = false;

function sessionId() {
  let id = localStorage.getItem("zeroqueue_session_id");
  if (!id) {
    id = window.crypto?.randomUUID?.() || `session-${Date.now()}`;
    localStorage.setItem("zeroqueue_session_id", id);
  }
  return id;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(text) {
  // Escape first. Formatting is added only after user/model text is safe.
  let safeText = escapeHtml(text);

  // Models sometimes return a whole list as one paragraph. Put common list
  // markers on their own lines so the normal line renderer can handle them.
  safeText = safeText
    .replace(/\s+(?=(?:\d+\.)\s+)/g, "\n")
    .replace(/\s+(?=[*-]\s+)/g, "\n")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>");

  const lines = safeText.split("\n");
  let result = "";
  let listIsOpen = false;

  for (let index = 0; index < lines.length; index += 1) {
    const bullet = lines[index].match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      if (!listIsOpen) {
        result += "<ul>";
        listIsOpen = true;
      }
      result += `<li>${bullet[1]}</li>`;
      continue;
    }

    if (listIsOpen) {
      result += "</ul>";
      listIsOpen = false;
    }
    result += lines[index];
    if (index < lines.length - 1) result += "<br>";
  }

  if (listIsOpen) result += "</ul>";
  return result;
}

function renderPlain(text) {
  // No list handling: the text is shown exactly as written. Used for
  // clarifying questions, which are single plain sentences.
  return escapeHtml(text).replaceAll("\n", "<br>");
}

function addMessage(role, text, imageUrl = null, plain = false) {
  byId("welcome")?.remove();
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  if (role === "bot" || role === "human") {
    const avatar = document.createElement("div");
    avatar.className = role === "human" ? "human-avatar" : "bot-avatar";
    avatar.textContent = role === "human" ? "HS" : "ZQ";
    row.appendChild(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "message";
  if (role === "human") {
    const label = document.createElement("strong");
    label.className = "human-label";
    label.textContent = "Human support";
    bubble.appendChild(label);
    const content = document.createElement("span");
    content.innerHTML = renderPlain(text);
    bubble.appendChild(content);
  } else if (role === "bot") {
    bubble.innerHTML = plain ? renderPlain(text) : renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  if (imageUrl) {
    const image = document.createElement("img");
    image.className = "message-image";
    image.alt = "Uploaded image";
    image.src = imageUrl;
    image.addEventListener("load", () => URL.revokeObjectURL(imageUrl), {once: true});
    image.addEventListener("error", () => URL.revokeObjectURL(imageUrl), {once: true});
    bubble.prepend(image);
  }
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
  if (selectedPreviewUrl) URL.revokeObjectURL(selectedPreviewUrl);
  selectedPreviewUrl = null;
  selectedFile = file;
  byId("filePreview").classList.toggle("hidden", !file);
  byId("fileName").textContent = file?.name || "";
  const thumbnail = byId("fileThumbnail");
  const isImage = Boolean(file?.type?.startsWith("image/"));
  if (isImage) {
    selectedPreviewUrl = URL.createObjectURL(file);
    thumbnail.src = selectedPreviewUrl;
  } else {
    thumbnail.removeAttribute("src");
  }
  thumbnail.classList.toggle("hidden", !isImage);
  byId("fileIcon").classList.toggle("hidden", isImage || !file);
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

function showError(message, retry) {
  byId("welcome")?.remove();
  const row = document.createElement("div");
  row.className = "message-row system";
  const bubble = document.createElement("div");
  bubble.className = "message";
  bubble.appendChild(document.createTextNode(`Something went wrong: ${message}. `));
  const retryButton = document.createElement("button");
  retryButton.type = "button";
  retryButton.className = "retry-button";
  retryButton.textContent = "Try again";
  retryButton.addEventListener("click", () => { row.remove(); retry(); });
  bubble.appendChild(retryButton);
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
}

async function sendMessage(retry = null) {
  const text = retry ? retry.text : input.value.trim();
  const file = retry ? retry.file : selectedFile;
  if (busy || (!text && !file)) return;
  if (!retry) {
    const sentImageUrl = file?.type?.startsWith("image/") ? URL.createObjectURL(file) : null;
    addMessage("customer", text || `(attached ${file.name})`, sentImageUrl);
    input.value = "";
    input.style.height = "auto";
    showFile(null);
    fileInput.value = "";
  }
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
    addMessage("bot", body.answer, null, body.status === "clarifying");
    if (body.attachment_note) addMessage("system", `Attachment: ${body.attachment_note}`);
    updateTrace(body.trace);
  } catch (error) {
    typing.remove();
    showError(error.message, () => sendMessage({ text, file }));
  } finally { setBusy(false); input.focus(); }
}

async function talkToHuman() {
  if (busy) return;
  setBusy(true);
  const launchers = [byId("humanButton"), byId("humanLabelButton")];
  launchers.forEach((button) => button.classList.add("working"));
  const typing = showTyping();
  try {
    const response = await fetch("/api/handoff", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId()}),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Request failed");
    typing.remove();
    addMessage("bot", body.answer);
    updateTrace(body.trace);
  } catch (error) {
    typing.remove();
    showError(error.message, talkToHuman);
  } finally {
    launchers.forEach((button) => button.classList.remove("working"));
    setBusy(false);
  }
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
      addMessage("human", reply.body);
    });
  } catch (_) { /* A quiet poll failure should not interrupt chat. */ }
}

// A click listener receives a MouseEvent. Do not pass that event into sendMessage,
// because sendMessage only accepts our own optional retry object.
byId("sendButton").addEventListener("click", () => sendMessage());
byId("humanButton").addEventListener("click", talkToHuman);
byId("humanLabelButton").addEventListener("click", talkToHuman);
byId("attachButton").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => showFile(fileInput.files[0] || null));
byId("removeFile").addEventListener("click", () => { fileInput.value = ""; showFile(null); });
byId("newChatButton").addEventListener("click", () => { localStorage.removeItem("zeroqueue_session_id"); location.reload(); });
input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 110)}px`; });
checkHealth();
setInterval(checkHumanReplies, 5000);