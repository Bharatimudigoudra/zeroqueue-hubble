/* Agent console: review AI suggestions, approve replies, add internal notes. */
(function () {
  const queueList = document.getElementById('queueList');
  const detailEmpty = document.getElementById('detailEmpty');
  const detailBody = document.getElementById('detailBody');
  const detailTitle = document.getElementById('detailTitle');
  const detailMeta = document.getElementById('detailMeta');
  const transcriptEl = document.getElementById('transcript');
  const replyEditor = document.getElementById('replyEditor');
  const confidenceEl = document.getElementById('suggestionConfidence');
  const sourcesBox = document.getElementById('suggestionSources');
  const sourceList = document.getElementById('suggestionSourceList');
  const approveButton = document.getElementById('approveButton');
  const noteToggle = document.getElementById('noteToggle');
  const noteArea = document.getElementById('noteArea');
  const noteEditor = document.getElementById('noteEditor');
  const noteButton = document.getElementById('noteButton');
  const actionStatus = document.getElementById('actionStatus');
  const statusPill = document.getElementById('statusPill');
  const refreshButton = document.getElementById('refreshButton');

  let selectedSession = null;

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

  function bubble(role, text) {
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
    (data.messages || []).forEach(function (m) { transcriptEl.appendChild(bubble(m.role, m.text)); });
    transcriptEl.scrollTop = transcriptEl.scrollHeight;

    const suggestion = data.suggestion || {};
    replyEditor.value = suggestion.answer || '';
    confidenceEl.textContent = (suggestion.confidence_band || 'no sources').toUpperCase();
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
    if (!body) { setStatus('Write or keep a reply first.', false); return; }
    approveButton.disabled = true;
    setStatus('Sending through Intercom...', true);
    try {
      const result = await (await api('/api/agent/conversations/' + encodeURIComponent(selectedSession) + '/reply',
        { method: 'POST', body: JSON.stringify({ body: body }) })).json();
      if (result.sent) {
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

  noteToggle.addEventListener('click', function () { noteArea.classList.toggle('hidden'); });

  noteButton.addEventListener('click', async function () {
    if (!selectedSession) return;
    const body = noteEditor.value.trim();
    if (!body) { setStatus('Write the internal note first.', false); return; }
    noteButton.disabled = true;
    try {
      const result = await (await api('/api/agent/conversations/' + encodeURIComponent(selectedSession) + '/note',
        { method: 'POST', body: JSON.stringify({ body: body }) })).json();
      if (result.sent) {
        noteEditor.value = '';
        noteArea.classList.add('hidden');
        setStatus('Internal note added in Intercom. The customer never sees it.', true);
      } else {
        setStatus('Note not added: ' + (result.reason || 'unknown error') + '.', false);
      }
    } catch (e) {
      setStatus('Note not added: network error.', false);
    }
    noteButton.disabled = false;
  });

  refreshButton.addEventListener('click', loadQueue);

  loadHealth();
  loadQueue();
  setInterval(loadQueue, 5000);
})();
