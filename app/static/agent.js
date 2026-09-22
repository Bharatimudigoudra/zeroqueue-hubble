/* Agent console: read escalated chats and approve replies. */
(function () {
  const queueList = document.getElementById('queueList');
  const detailEmpty = document.getElementById('detailEmpty');
  const detailBody = document.getElementById('detailBody');
  const detailTitle = document.getElementById('detailTitle');
  const detailMeta = document.getElementById('detailMeta');
  const transcriptEl = document.getElementById('transcript');
  const replyEditor = document.getElementById('replyEditor');
  const sourcesBox = document.getElementById('suggestionSources');
  const sourceList = document.getElementById('suggestionSourceList');
  const approveButton = document.getElementById('approveButton');
  const actionStatus = document.getElementById('actionStatus');
  const statusPill = document.getElementById('statusPill');
  const refreshButton = document.getElementById('refreshButton');

  let selectedSession = null;
  // Server messages rendered so far for the open chat. Replies the agent
  // sends are appended locally and never come back through this list, so
  // the count must only track what the server returned.
  let renderedServerMessages = 0;

  // Optional protection: only asked for when the server demands a key.
  function agentKey() { return localStorage.getItem('zq-agent-key') || ''; }

  async function api(path, options = {}, retried = false) {
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers, { 'x-agent-key': agentKey() });
    const response = await fetch(path, opts);
    if (response.status === 403 && !retried) {
      const key = window.prompt('This console is protected. Enter the agent key:');
      if (key) {
        localStorage.setItem('zq-agent-key', key);
        return api(path, options, true);
      }
    }
    return response;
  }

  function setStatus(text, ok) {
    actionStatus.textContent = text;
    actionStatus.className = 'action-status ' + (ok ? 'ok' : 'warn');
  }

  async function loadHealth() {
    try {
      const health = await (await fetch('/health')).json();
      const ok = health.intercom_configured;
      statusPill.className = 'status-pill ' + (ok ? 'ok' : 'bad');
      statusPill.querySelector('span').textContent = ok ? 'Intercom live' : 'Intercom not connected';
    } catch (e) {
      statusPill.className = 'status-pill bad';
      statusPill.querySelector('span').textContent = 'Backend offline';
    }
  }

  function shortId(sessionId) {
    return sessionId.length > 12 ? sessionId.slice(0, 8) + '..' + sessionId.slice(-2) : sessionId;
  }

  async function loadQueue() {
    const data = await (await api('/api/agent/conversations')).json();
    const conversations = data.conversations || [];
    if (!conversations.length) {
      queueList.innerHTML = '<p class="queue-empty">No customer is waiting. Escalated chats appear here the moment a customer asks for a human or the AI hands off.</p>';
      return;
    }
    queueList.innerHTML = '';
    conversations.forEach(function (item) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'queue-item' + (item.session_id === selectedSession ? ' selected' : '');
      button.dataset.session = item.session_id;
      const reason = (item.handoff_reason || 'handoff').replace(/_/g, ' ');
      button.innerHTML = '<strong>Chat ' + shortId(item.session_id) + '</strong>' +
        '<span class="queue-reason">' + reason + '</span>' +
        '<span class="queue-preview"></span>';
      button.querySelector('.queue-preview').textContent = item.last_customer_message || '(no customer message yet)';
      button.addEventListener('click', function () { selectConversation(item.session_id); });
      queueList.appendChild(button);
    });
    // Demo-friendly: open the first waiting chat when nothing is selected.
    if (!selectedSession || !conversations.some(function (c) { return c.session_id === selectedSession; })) {
      selectConversation(conversations[0].session_id);
    }
  }

  function bubble(role, text, attachment) {
    const row = document.createElement('div');
    const kind = role === 'customer' ? 'customer' : (role === 'agent' ? 'human' : 'bot');
    row.className = 'message-row ' + kind;
    const avatar = document.createElement('div');
    avatar.className = kind === 'human' ? 'human-avatar' : 'bot-avatar';
    avatar.textContent = kind === 'human' ? 'You' : 'ZQ';
    const msg = document.createElement('div');
    msg.className = 'message';
    if (kind === 'human') {
      const label = document.createElement('span');
      label.className = 'human-label';
      label.textContent = 'Human agent';
      msg.appendChild(label);
    }
    msg.appendChild(document.createTextNode(text));
    // The agent must see what the customer actually sent: the image itself
    // (or a file link), with the OCR text as a small note under it.
    if (attachment) {
      if (attachment.kind === 'image' && attachment.url) {
        const img = document.createElement('img');
        img.className = 'message-image';
        img.alt = attachment.name || 'Customer attachment';
        img.src = attachment.url;
        msg.appendChild(img);
      } else if (attachment.url) {
        const link = document.createElement('a');
        link.href = attachment.url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = attachment.name || 'Download attachment';
        msg.appendChild(link);
      }
      if (attachment.ocr) {
        const ocr = document.createElement('div');
        ocr.className = 'message-ocr';
        ocr.textContent = 'OCR: ' + attachment.ocr;
        msg.appendChild(ocr);
      }
    }
    if (kind === 'customer') { row.appendChild(msg); } else { row.appendChild(avatar); row.appendChild(msg); }
    return row;
  }

  async function selectConversation(sessionId) {
    selectedSession = sessionId;
    setStatus('', true);
    const data = await (await api('/api/agent/conversations/' + encodeURIComponent(sessionId))).json();
    detailEmpty.classList.add('hidden');
    detailBody.classList.remove('hidden');
    detailTitle.textContent = 'Chat ' + shortId(sessionId);
    const reason = (data.handoff_reason || 'handoff').replace(/_/g, ' ');
    let meta = 'Reason: ' + reason + ' · Intercom ' + (data.intercom_linked ? 'linked' : 'will be created on send');
    const snap = data.intercom_conversation;
    if (snap && snap.state) meta += ' (Intercom state: ' + snap.state + ')';
    if (snap && snap.error) meta += ' (Intercom fetch failed: ' + snap.error + ')';
    detailMeta.textContent = meta;

    transcriptEl.innerHTML = '';
    (data.messages || []).forEach(function (m) { transcriptEl.appendChild(bubble(m.role, m.text, m.attachment)); });
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    renderedServerMessages = (data.messages || []).length;

    const suggestion = data.suggestion || {};
    replyEditor.value = '';
    if (suggestion.citations && suggestion.citations.length) {
      sourcesBox.classList.remove('hidden');
      sourceList.innerHTML = '';
      suggestion.citations.forEach(function (c) {
        const li = document.createElement('li');
        li.textContent = c.label;
        sourceList.appendChild(li);
      });
    } else {
      sourcesBox.classList.add('hidden');
    }
    Array.prototype.forEach.call(queueList.children, function (child) {
      if (child.classList) child.classList.toggle('selected', child.dataset.session === selectedSession);
    });
  }

  approveButton.addEventListener('click', async function () {
    if (!selectedSession) return;
    const body = replyEditor.value.trim();
    if (!body) { setStatus('Write a reply first.', false); return; }
    approveButton.disabled = true;
    setStatus('Sending through Intercom...', true);
    try {
      const result = await (await api('/api/agent/conversations/' + encodeURIComponent(selectedSession) + '/reply',
        { method: 'POST', body: JSON.stringify({ body: body }) })).json();
      if (result.sent) {
        replyEditor.value = '';
        transcriptEl.appendChild(bubble('agent', body));
        transcriptEl.scrollTop = transcriptEl.scrollHeight;
        setStatus('Sent - the customer sees this in their chat.', true);
      } else {
        setStatus('Not sent: ' + (result.reason || 'unknown error') + (result.reason === 'intercom_not_configured' ? ' - connect Intercom in the .env to send live.' : '.'), false);
      }
    } catch (e) {
      setStatus('Not sent: network error.', false);
    }
    approveButton.disabled = false;
  });

  refreshButton.addEventListener('click', loadQueue);

  loadHealth();
  loadQueue();
  // While a chat is open, pull in new CUSTOMER messages as they arrive
  // (the AI is paused during handoff, but the customer can still write).
  // Only appends messages the server has since stored - the agent's typed
  // draft and their just-sent replies stay untouched.
  async function refreshSelected() {
    if (!selectedSession || detailBody.classList.contains('hidden')) return;
    try {
      const data = await (await api('/api/agent/conversations/' + encodeURIComponent(selectedSession))).json();
      const messages = data.messages || [];
      if (messages.length > renderedServerMessages) {
        messages.slice(renderedServerMessages).forEach(function (m) { transcriptEl.appendChild(bubble(m.role, m.text, m.attachment)); });
        renderedServerMessages = messages.length;
        transcriptEl.scrollTop = transcriptEl.scrollHeight;
      }
    } catch (e) { /* a quiet poll failure must not interrupt the reply */ }
  }

  setInterval(function () { loadQueue(); refreshSelected(); }, 5000);
})();
