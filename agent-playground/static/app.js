// ── State ──
var agents = [];
var currentAgent = null;
var currentThreadId = null;
var isWaiting = false;
var sidebarOpen = true;
var pendingApproval = null; // { agentId, threadId, requests } while a run waits for a decision

var SOURCE_LABELS = { agentbricks: 'Agent Bricks', app: 'Custom agent', 'agents.yml': 'agents.yml' };
var STORE_KEY = 'playground.conversations';

// ── Init ──
fetch('/api/agents')
  .then(function(res) {
    return res.json().then(function(body) {
      if (!res.ok) throw new Error(body.detail || 'HTTP ' + res.status);
      return body;
    });
  })
  .then(function(body) {
    agents = body.agents;
    document.getElementById('sidebar-subtitle').textContent = body.me ? 'Signed in as ' + body.me : '';
    renderAgentPicker();
    var saved = localStorage.getItem('lastAgentId');
    var pick = agents.find(function(a) { return a.id === saved && a.available; })
      || agents.find(function(a) { return a.available; });
    if (pick) selectAgent(pick.id);
    else addSystemNote('No agents available. Deploy an agent-* app or add one to agents.yml.');
  })
  .catch(function(err) {
    document.getElementById('sidebar-subtitle').textContent = '';
    addSystemNote('Could not load agents: ' + err.message);
  });

// ── Sidebar ──
function toggleSidebar() {
  var sidebar = document.getElementById('sidebar');
  sidebarOpen = !sidebarOpen;
  sidebar.classList.toggle('collapsed', !sidebarOpen);
}

function setHasMessages(has) {
  document.getElementById('main').classList.toggle('has-messages', has);
}

// ── Agent picker ──
function renderAgentPicker() {
  var picker = document.getElementById('agent-picker');
  picker.replaceChildren();
  agents.forEach(function(a) {
    var opt = document.createElement('option');
    opt.value = a.id;
    opt.textContent = a.available ? a.name : a.name + ' (' + (a.unavailable_reason || 'unavailable') + ')';
    opt.disabled = !a.available;
    picker.appendChild(opt);
  });
}

function selectAgent(id) {
  currentAgent = agents.find(function(a) { return a.id === id; });
  localStorage.setItem('lastAgentId', id);
  document.getElementById('agent-picker').value = id;
  document.getElementById('model-badge').textContent = SOURCE_LABELS[currentAgent.source] || '';
  var traces = document.getElementById('traces-link');
  traces.href = currentAgent.traces_url || '';
  traces.hidden = !currentAgent.traces_url;
  document.getElementById('welcome-subtitle').textContent = currentAgent.description || '';
  if (pendingApproval) hideApproval();
  currentThreadId = null;
  clearMessages();
  setHasMessages(false);
  updateThreadBadge('');
  refreshThreadList();
}

function api(path) {
  return '/api/agents/' + encodeURIComponent(currentAgent.id) + path;
}

// ── Conversation store (in this browser; each agent keeps its own memory by session ID) ──
// Shape: { [agentId]: { [threadId]: { title, messages } } }; messages are { role, content, tool_calls? }.
function readStore() {
  return JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
}

function writeStore(store) {
  localStorage.setItem(STORE_KEY, JSON.stringify(store));
}

function recordLocal(turn, msg) {
  var store = readStore();
  var byAgent = store[turn.agentId] = store[turn.agentId] || {};
  var convo = byAgent[turn.threadId] = byAgent[turn.threadId] || { title: '', messages: [] };
  if (!convo.title && msg.role === 'user') convo.title = msg.content.slice(0, 60);
  convo.messages.push(msg);
  writeStore(store);
}

// ── Thread management ──
function newChat() {
  currentThreadId = crypto.randomUUID();
  if (pendingApproval) hideApproval();
  clearMessages();
  setHasMessages(false);
  updateThreadBadge(currentThreadId);
  highlightActiveThread();
}

function loadThread(threadId) {
  if (currentThreadId === threadId) return;
  if (pendingApproval && pendingApproval.threadId !== threadId) hideApproval();
  currentThreadId = threadId;
  clearMessages();
  updateThreadBadge(threadId);
  highlightActiveThread();

  var convo = (readStore()[currentAgent.id] || {})[threadId];
  var msgs = convo ? convo.messages : [];
  setHasMessages(msgs.length > 0);
  renderHistoryMessages(msgs);
}

function refreshThreadList() {
  var convos = readStore()[currentAgent.id] || {};
  renderThreadList(Object.keys(convos).map(function(id) {
    return { id: id, title: convos[id].title || id };
  }).reverse());
}

function renderThreadList(threads) {
  var list = document.getElementById('thread-list');
  while (list.firstChild) list.removeChild(list.firstChild);

  if (!threads || threads.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'padding: 12px 10px; font-size: 12px; color: #9ca3af; text-align: center;';
    empty.textContent = 'No threads yet';
    list.appendChild(empty);
    return;
  }

  threads.forEach(function(thread) {
    var tid = thread.id;

    var item = document.createElement('div');
    item.className = 'thread-item';
    item.dataset.threadId = tid;

    var dot = document.createElement('span');
    dot.className = 'thread-dot';

    var label = document.createElement('span');
    label.className = 'thread-label';
    label.textContent = thread.title;

    var actions = document.createElement('span');
    actions.className = 'thread-actions';

    var renameBtn = document.createElement('button');
    renameBtn.className = 'thread-action-btn';
    renameBtn.title = 'Rename';
    var renameSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    renameSvg.setAttribute('viewBox', '0 0 16 16');
    var renamePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    renamePath.setAttribute('d', 'M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z');
    renameSvg.appendChild(renamePath);
    renameBtn.appendChild(renameSvg);

    var deleteBtn = document.createElement('button');
    deleteBtn.className = 'thread-action-btn';
    deleteBtn.title = 'Delete';
    var deleteSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    deleteSvg.setAttribute('viewBox', '0 0 16 16');
    var deletePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    deletePath.setAttribute('d', 'M5.5 2V1h5v1h4v1.5H1.5V2h4zM3 5h10l-.7 9.1a1 1 0 01-1 .9H4.7a1 1 0 01-1-.9L3 5z');
    deleteSvg.appendChild(deletePath);
    deleteBtn.appendChild(deleteSvg);

    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    item.appendChild(dot);
    item.appendChild(label);
    item.appendChild(actions);

    (function(id) {
      label.addEventListener('click', function() { loadThread(id); });
      dot.addEventListener('click', function() { loadThread(id); });
      renameBtn.addEventListener('click', function(e) { e.stopPropagation(); startRename(item, id); });
      deleteBtn.addEventListener('click', function(e) { e.stopPropagation(); deleteThread(id); });
    })(tid);

    list.appendChild(item);
  });

  highlightActiveThread();
}

function startRename(item, tid) {
  var label = item.querySelector('.thread-label');
  var actions = item.querySelector('.thread-actions');
  var currentTitle = label.textContent;

  var input = document.createElement('input');
  input.className = 'thread-rename-input';
  input.value = currentTitle;
  label.style.display = 'none';
  actions.style.display = 'none';
  item.insertBefore(input, actions);
  input.focus();
  input.select();

  function save() {
    var newTitle = input.value.trim();
    if (newTitle && newTitle !== currentTitle) {
      label.textContent = newTitle;
      var store = readStore();
      if (store[currentAgent.id] && store[currentAgent.id][tid]) {
        store[currentAgent.id][tid].title = newTitle;
        writeStore(store);
      }
    }
    input.remove();
    label.style.display = '';
    actions.style.display = '';
  }

  input.addEventListener('blur', save);
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') { input.remove(); label.style.display = ''; actions.style.display = ''; }
  });
}

function deleteThread(tid) {
  var item = document.querySelector('.thread-item[data-thread-id="' + tid + '"]');
  if (item) item.remove();
  if (pendingApproval && pendingApproval.threadId === tid) hideApproval();
  if (currentThreadId === tid) {
    currentThreadId = null;
    clearMessages();
    setHasMessages(false);
    updateThreadBadge('');
  }
  var store = readStore();
  if (store[currentAgent.id]) delete store[currentAgent.id][tid];
  writeStore(store);
}

function highlightActiveThread() {
  document.querySelectorAll('.thread-item').forEach(function(item) {
    item.classList.toggle('active', item.dataset.threadId === currentThreadId);
  });
}

// ── Send message and approvals ──
function sendMessage() {
  if (isWaiting) return;

  var input = document.getElementById('user-input');
  var text = input.value.trim();
  if (!text || !currentAgent) return;

  if (!currentThreadId) newChat();
  removeEmptyState();

  var turn = { agentId: currentAgent.id, threadId: currentThreadId };
  recordLocal(turn, { role: 'user', content: text });
  appendMessage('user', text);
  input.value = '';
  autoResize(input);

  streamTurn('/chat', { session_id: turn.threadId, message: text }, turn);
}

// Approve or reject the tool call the agent paused on. Resumes the same session.
function decide(decision) {
  var p = pendingApproval;
  if (!p || isWaiting) return;
  hideApproval();
  addSystemNote(decision === 'approve' ? 'Approved pending tool call.' : 'Rejected pending tool call.');
  var decisions = p.requests.map(function() {
    return decision === 'approve'
      ? { type: 'approve' }
      : { type: 'reject', message: 'Rejected from Agent Playground.' };
  });
  var turn = { agentId: p.agentId, threadId: p.threadId };
  streamTurn('/chat', { session_id: p.threadId, resume: { decisions: decisions } }, turn);
}

function showApproval(turn, requests) {
  pendingApproval = { agentId: turn.agentId, threadId: turn.threadId, requests: requests || [] };
  var summary = pendingApproval.requests.map(function(r) {
    return (r.name || 'tool') + ' ' + JSON.stringify(r.args || {});
  }).join(' · ');
  document.getElementById('approval-text').textContent = summary || 'The agent paused and needs a decision.';
  document.getElementById('approval-panel').hidden = false;
}

function hideApproval() {
  pendingApproval = null;
  document.getElementById('approval-panel').hidden = true;
}

// POST a turn and render its event stream into a new assistant row.
function streamTurn(path, payload, turn) {
  var typingEl = showTyping();
  isWaiting = true;
  setSendDisabled(true);

  fetch(api(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(function(res) {
      removeTyping(typingEl);
      if (!res.ok) throw new Error('agent returned ' + res.status);
      openAssistantRow(turn);
      return readSse(res, function(evt) { handleEvent(evt, turn); });
    })
    .catch(function(err) {
      removeTyping(typingEl);
      addSystemNote('Error: could not get a response (' + err.message + ').');
      console.error('Send error:', err);
    })
    .finally(function() {
      if (turn.dots) turn.dots.remove();
      isWaiting = false;
      setSendDisabled(false);
      refreshThreadList();
    });
}

function openAssistantRow(turn) {
  var row = document.createElement('div');
  row.className = 'message-row assistant';
  var label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = 'Assistant';
  turn.toolContainer = document.createElement('div');
  turn.bubble = document.createElement('div');
  turn.bubble.className = 'message-bubble';
  turn.text = '';
  turn.tools = {};
  // Animated dots stay at the bottom of the reply until the agent's stream ends.
  turn.dots = typingDots();
  row.appendChild(label);
  row.appendChild(turn.toolContainer);
  row.appendChild(turn.bubble);
  row.appendChild(turn.dots);
  document.getElementById('messages').appendChild(row);
  scrollToBottom();
}

function handleEvent(evt, turn) {
  if (evt.event === 'token') {
    turn.text += evt.content;
    turn.bubble.style.display = '';
    turn.bubble.textContent = turn.text;
  } else if (evt.event === 'tool_call') {
    var block = buildToolBlock(evt.name, evt.args);
    turn.toolContainer.appendChild(block);
    turn.tools[evt.id] = block;
    turn.bubble.style.display = 'none';
    turn.text = '';
    recordLocal(turn, { role: 'assistant', content: '', tool_calls: [{ id: evt.id, name: evt.name, args: evt.args }] });
  } else if (evt.event === 'tools') {
    var tb = turn.tools[evt.tool_call_id];
    if (tb) {
      var spinner = tb.querySelector('.tool-spinner');
      if (spinner) spinner.remove();
      var status = tb.querySelector('.tool-status');
      if (status) { status.textContent = 'Done'; status.className = 'tool-status done'; }
      var outputEl = tb.querySelector('.tool-output');
      if (outputEl) outputEl.textContent = evt.output;
    }
    recordLocal(turn, { role: 'tool', tool_call_id: evt.tool_call_id, content: evt.output });
  } else if (evt.event === 'done') {
    if (evt.content) {
      turn.bubble.style.display = '';
      turn.bubble.innerHTML = renderMarkdown(evt.content);
      recordLocal(turn, { role: 'assistant', content: evt.content });
    }
  } else if (evt.event === 'interrupt') {
    showApproval(turn, evt.requests);
  } else if (evt.event === 'error') {
    turn.bubble.style.display = '';
    turn.bubble.textContent = 'Error: ' + evt.detail;
  }
  scrollToBottom();
}

// Reads an SSE response and calls onEvent with each parsed `data:` payload.
function readSse(res, onEvent) {
  var reader = res.body.getReader();
  var decoder = new TextDecoder();
  var buffer = '';

  function emit(frame) {
    var line = frame.split('\n').find(function(l) { return l.indexOf('data: ') === 0; });
    if (line) onEvent(JSON.parse(line.slice(6)));
  }

  function pump() {
    return reader.read().then(function(result) {
      if (result.done) {
        if (buffer.trim()) emit(buffer);
        return;
      }
      buffer += decoder.decode(result.value, { stream: true });
      var frames = buffer.split('\n\n');
      buffer = frames.pop();
      frames.forEach(emit);
      return pump();
    });
  }
  return pump();
}

// ── History rendering ──
function renderHistoryMessages(msgs) {
  var i = 0;
  while (i < msgs.length) {
    var m = msgs[i];
    if (m.role === 'user') {
      appendMessage('user', m.content);
      i++;
    } else if (m.role === 'assistant' && m.tool_calls && m.tool_calls.length > 0) {
      var messagesEl = document.getElementById('messages');
      var row = document.createElement('div');
      row.className = 'message-row assistant';
      var label = document.createElement('div');
      label.className = 'message-label';
      label.textContent = 'Assistant';
      var toolContainer = document.createElement('div');
      row.appendChild(label);
      row.appendChild(toolContainer);

      while (i < msgs.length && msgs[i].role === 'assistant' && msgs[i].tool_calls && msgs[i].tool_calls.length > 0) {
        var toolCalls = msgs[i].tool_calls;
        var toolResults = {};
        i++;
        while (i < msgs.length && msgs[i].role === 'tool') {
          toolResults[msgs[i].tool_call_id] = msgs[i];
          i++;
        }
        for (var t = 0; t < toolCalls.length; t++) {
          var tc = toolCalls[t];
          var block = buildToolBlock(tc.name, tc.args);
          var spinner = block.querySelector('.tool-spinner');
          if (spinner) spinner.remove();
          var status = block.querySelector('.tool-status');
          if (status) { status.textContent = 'Done'; status.className = 'tool-status done'; }
          var tr = toolResults[tc.id];
          if (tr) {
            var outputEl = block.querySelector('.tool-output');
            if (outputEl) outputEl.textContent = tr.content;
          }
          toolContainer.appendChild(block);
        }
      }

      if (i < msgs.length && msgs[i].role === 'assistant' && (!msgs[i].tool_calls || msgs[i].tool_calls.length === 0)) {
        var bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = renderMarkdown(msgs[i].content);
        row.appendChild(bubble);
        i++;
      }

      messagesEl.appendChild(row);
      scrollToBottom();
    } else if (m.role === 'assistant') {
      appendMessage('assistant', m.content);
      i++;
    } else {
      i++;
    }
  }
}

// ── Message rendering ──
function appendMessage(role, content) {
  var messagesEl = document.getElementById('messages');
  var row = document.createElement('div');
  row.className = 'message-row ' + role;

  var label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'You' : 'Assistant';

  var bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  if (role === 'assistant') {
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.textContent = content;
  }

  row.appendChild(label);
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  scrollToBottom();
}

function showTyping() {
  var messagesEl = document.getElementById('messages');
  var row = document.createElement('div');
  row.className = 'message-row assistant';
  row.id = 'typing-row';

  var label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = 'Assistant';

  row.appendChild(label);
  row.appendChild(typingDots());
  messagesEl.appendChild(row);
  scrollToBottom();
  return row;
}

function typingDots() {
  var indicator = document.createElement('div');
  indicator.className = 'typing-indicator';
  for (var i = 0; i < 3; i++) {
    var dot = document.createElement('span');
    dot.className = 'typing-dot';
    indicator.appendChild(dot);
  }
  return indicator;
}

function removeTyping(el) {
  if (el && el.parentNode) el.remove();
}

function addSystemNote(text) {
  var messagesEl = document.getElementById('messages');
  var note = document.createElement('div');
  note.className = 'system-note';
  note.textContent = text;
  messagesEl.appendChild(note);
  scrollToBottom();
  return note;
}

// ── Markdown rendering ──
// Note: escapeHtml runs first to prevent XSS, then markdown syntax is converted to safe HTML
function escapeHtml(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderMarkdown(text) {
  var html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(_, lang, code) {
    return '\x00PRE' + code.replace(/\n$/, '') + 'PRE\x00';
  });
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

  var blocks = html.split(/\n\n+/);
  var result = [];
  for (var b = 0; b < blocks.length; b++) {
    var block = blocks[b].trim();
    if (!block) continue;
    if (block.indexOf('\x00PRE') === 0) {
      var code = block.replace(/^\x00PRE/, '').replace(/PRE\x00$/, '');
      result.push('<pre class="md-code-block"><code>' + code + '</code></pre>');
      continue;
    }
    var lines = block.split('\n');
    if (lines[0].match(/^\d+\.\s/) || lines[0].match(/^[-*]\s/)) {
      var isOl = !!lines[0].match(/^\d+\.\s/);
      result.push(isOl ? '<ol>' : '<ul>');
      for (var li = 0; li < lines.length; li++) {
        var lm = lines[li].match(/^(?:\d+\.|[-*])\s+(.*)/);
        if (lm) result.push('<li>' + lm[1] + '</li>');
      }
      result.push(isOl ? '</ol>' : '</ul>');
    } else {
      result.push('<p>' + block.replace(/\n/g, '<br>') + '</p>');
    }
  }
  return result.join('');
}

// ── Tool blocks ──
function buildToolBlock(name, args) {
  var block = document.createElement('div');
  block.className = 'tool-block';

  var header = document.createElement('div');
  header.className = 'tool-header';
  header.onclick = function() { block.classList.toggle('open'); };

  var chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chevron.setAttribute('class', 'tool-chevron');
  chevron.setAttribute('viewBox', '0 0 16 16');
  var chevronPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  chevronPath.setAttribute('d', 'M6 3l5 5-5 5');
  chevronPath.setAttribute('fill', 'none');
  chevronPath.setAttribute('stroke', 'currentColor');
  chevronPath.setAttribute('stroke-width', '2');
  chevronPath.setAttribute('stroke-linecap', 'round');
  chevronPath.setAttribute('stroke-linejoin', 'round');
  chevron.appendChild(chevronPath);

  var toolIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  toolIcon.setAttribute('class', 'tool-icon');
  toolIcon.setAttribute('viewBox', '0 0 16 16');
  var iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  iconPath.setAttribute('d', 'M2 4l4 4-4 4M8 12h6');
  iconPath.setAttribute('fill', 'none');
  iconPath.setAttribute('stroke', 'currentColor');
  iconPath.setAttribute('stroke-width', '2');
  iconPath.setAttribute('stroke-linecap', 'round');
  iconPath.setAttribute('stroke-linejoin', 'round');
  toolIcon.appendChild(iconPath);

  var nameSpan = document.createElement('span');
  nameSpan.className = 'tool-name';
  nameSpan.textContent = name;

  var spinnerEl = document.createElement('div');
  spinnerEl.className = 'tool-spinner';

  var statusEl = document.createElement('span');
  statusEl.className = 'tool-status running';
  statusEl.textContent = 'Running';

  header.appendChild(chevron);
  header.appendChild(toolIcon);
  header.appendChild(nameSpan);
  header.appendChild(spinnerEl);
  header.appendChild(statusEl);

  var details = document.createElement('div');
  details.className = 'tool-details';

  var argsLabel = document.createElement('div');
  argsLabel.className = 'tool-section-label';
  argsLabel.textContent = 'Arguments';
  var argsCode = document.createElement('div');
  argsCode.className = 'tool-code tool-args';
  argsCode.textContent = JSON.stringify(args, null, 2);

  var outputLabel = document.createElement('div');
  outputLabel.className = 'tool-section-label';
  outputLabel.style.marginTop = '10px';
  outputLabel.textContent = 'Output';
  var outputCode = document.createElement('div');
  outputCode.className = 'tool-code tool-output';
  outputCode.textContent = 'Waiting...';

  details.appendChild(argsLabel);
  details.appendChild(argsCode);
  details.appendChild(outputLabel);
  details.appendChild(outputCode);

  block.appendChild(header);
  block.appendChild(details);
  return block;
}

// ── Helpers ──
function clearMessages() {
  var el = document.getElementById('messages');
  while (el.firstChild) el.removeChild(el.firstChild);
}

function removeEmptyState() {
  var empty = document.getElementById('empty-state');
  if (empty && empty.parentNode) empty.remove();
  setHasMessages(true);
}

function updateThreadBadge(threadId) {
  document.getElementById('thread-badge').textContent = threadId;
}

function scrollToBottom() {
  var el = document.getElementById('messages');
  el.scrollTop = el.scrollHeight;
}

function setSendDisabled(disabled) {
  document.getElementById('send-btn').disabled = disabled;
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function handleKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}
