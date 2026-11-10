// ── State ──
let currentThreadId = null;
let isWaiting = false;
let sidebarOpen = true;
let API_BASE = '';
var threadCache = {};
var threadTitles = {};

// ── Init ──
fetch('/api-url')
  .then(function(res) { return res.json(); })
  .then(function(data) {
    API_BASE = data.url || '';
    refreshThreadList();
    return fetch(API_BASE + '/config', { credentials: 'include' });
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    var label = data.model || '';
    var match = label.match(/llama[\-_]?(\d+[\.\d]*)[\-_]?(\d+b)/i);
    var display = match ? ('Llama ' + match[1] + ' ' + match[2].toUpperCase()) : label;
    document.getElementById('model-badge').textContent = display;
    document.getElementById('welcome-subtitle').textContent =
      'Powered by ' + display + ' · memory persisted to Lakebase';
  })
  .catch(function() {
    refreshThreadList();
    document.getElementById('model-badge').textContent = 'Model';
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

// ── Thread management ──
function newChat() {
  currentThreadId = crypto.randomUUID();
  localStorage.setItem('lastThreadId', currentThreadId);
  threadCache[currentThreadId] = [];
  clearMessages();
  setHasMessages(false);
  updateThreadBadge(currentThreadId);
  highlightActiveThread();
}

function loadThread(threadId) {
  if (currentThreadId === threadId) return;
  currentThreadId = threadId;
  localStorage.setItem('lastThreadId', currentThreadId);
  clearMessages();
  setHasMessages(true);
  updateThreadBadge(threadId);
  highlightActiveThread();

  if (threadCache.hasOwnProperty(threadId)) {
    var cached = threadCache[threadId];
    if (cached.length === 0) return;
    setHasMessages(true);
    renderHistoryMessages(cached);
  } else {
    fetchAndCacheHistory(threadId);
  }
}

function fetchAndCacheHistory(threadId) {
  var loadingEl = document.createElement('div');
  loadingEl.className = 'history-loading';
  loadingEl.textContent = 'Loading history...';
  document.getElementById('messages').appendChild(loadingEl);

  fetch(API_BASE + '/history/' + encodeURIComponent(threadId), { credentials: 'include' })
    .then(function(res) { return res.json(); })
    .then(function(data) {
      if (loadingEl.parentNode) loadingEl.remove();
      if (currentThreadId !== threadId) return;
      var msgs = data.messages || [];
      threadCache[threadId] = msgs;
      if (msgs.length === 0) return;
      setHasMessages(true);
      renderHistoryMessages(msgs);
      var humanCount = msgs.filter(function(m) { return m.role === 'user'; }).length;
      var note = addSystemNote('Loaded from Lakebase · ' + humanCount + ' exchanges');
      setTimeout(function() { note.classList.add('fade-out'); }, 1000);
    })
    .catch(function(err) {
      if (loadingEl.parentNode) loadingEl.remove();
      addSystemNote('Could not load history from Lakebase.');
      console.error('History fetch error:', err);
    });
}

// ── Thread list ──
function refreshThreadList() {
  fetch(API_BASE + '/threads', { credentials: 'include' })
    .then(function(res) { return res.json(); })
    .then(function(data) {
      var threads = data.threads || [];
      // Merge server list with locally known threads so sidebar works without Lakebase
      var serverIds = new Set(threads.map(function(t) { return typeof t === 'string' ? t : t.id; }));
      Object.keys(threadCache).forEach(function(tid) {
        if (!serverIds.has(tid)) threads.unshift(tid);
      });
      renderThreadList(threads);
      // On page load (currentThreadId is null), restore the last active thread
      var savedId = localStorage.getItem('lastThreadId');
      if (savedId && !currentThreadId) {
        var exists = threads.some(function(t) { return (typeof t === 'string' ? t : t.id) === savedId; });
        if (exists) loadThread(savedId);
      }
    })
    .catch(function(err) {
      console.error('Failed to fetch threads:', err);
      renderThreadList(Object.keys(threadCache));
    });
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
    var tid = typeof thread === 'string' ? thread : thread.id;
    var title = (typeof thread === 'object' && thread.title) ? thread.title : null;
    if (title) threadTitles[tid] = title;

    var item = document.createElement('div');
    item.className = 'thread-item';
    item.dataset.threadId = tid;

    var dot = document.createElement('span');
    dot.className = 'thread-dot';

    var label = document.createElement('span');
    label.className = 'thread-label';
    label.textContent = threadTitles[tid] || tid;

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
  var currentTitle = threadTitles[tid] || tid;

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
      threadTitles[tid] = newTitle;
      label.textContent = newTitle;
      fetch(API_BASE + '/threads/' + encodeURIComponent(tid), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ title: newTitle }),
      }).catch(function(err) { console.error('Rename failed:', err); });
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
  delete threadCache[tid];
  delete threadTitles[tid];
  var item = document.querySelector('.thread-item[data-thread-id="' + tid + '"]');
  if (item) item.remove();
  if (currentThreadId === tid) {
    currentThreadId = null;
    clearMessages();
    setHasMessages(false);
    updateThreadBadge('');
  }
  fetch(API_BASE + '/threads/' + encodeURIComponent(tid), {
    method: 'DELETE',
    credentials: 'include',
  }).catch(function(err) {
    console.error('Delete failed:', err);
    refreshThreadList();
  });
}

function highlightActiveThread() {
  document.querySelectorAll('.thread-item').forEach(function(item) {
    item.classList.toggle('active', item.dataset.threadId === currentThreadId);
  });
}

// ── Send message (streaming) ──
function sendMessage() {
  if (isWaiting) return;

  var input = document.getElementById('user-input');
  var text = input.value.trim();
  if (!text) return;

  if (!currentThreadId) {
    currentThreadId = crypto.randomUUID();
    localStorage.setItem('lastThreadId', currentThreadId);
    updateThreadBadge(currentThreadId);
  }

  removeEmptyState();
  if (!threadCache.hasOwnProperty(currentThreadId)) threadCache[currentThreadId] = [];
  threadCache[currentThreadId].push({ role: 'user', content: text });

  appendMessage('user', text);
  input.value = '';
  autoResize(input);

  var typingEl = showTyping();
  isWaiting = true;
  setSendDisabled(true);

  fetch(API_BASE + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ thread_id: currentThreadId, message: text })
  })
    .then(function(res) {
      if (!res.ok) throw new Error('Error ' + res.status);
      removeTyping(typingEl);

      var messagesEl = document.getElementById('messages');
      var row = document.createElement('div');
      row.className = 'message-row assistant';
      var label = document.createElement('div');
      label.className = 'message-label';
      label.textContent = 'Assistant';
      var toolContainer = document.createElement('div');
      var bubble = document.createElement('div');
      bubble.className = 'message-bubble';
      row.appendChild(label);
      row.appendChild(toolContainer);
      row.appendChild(bubble);
      messagesEl.appendChild(row);
      scrollToBottom();

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var streamedText = '';
      var finalContent = '';
      var currentToolBlocks = {};

      function pump() {
        return reader.read().then(function(result) {
          if (result.done) {
            isWaiting = false;
            setSendDisabled(false);
            if (finalContent) threadCache[currentThreadId].push({ role: 'assistant', content: finalContent });
            refreshThreadList();
            return;
          }

          var lines = decoder.decode(result.value, { stream: true }).split('\n');
          for (var i = 0; i < lines.length; i++) {
            if (!lines[i].startsWith('data: ')) continue;
            try {
              var evt = JSON.parse(lines[i].slice(6));
              if (evt.event === 'token') {
                // Incremental token — append to bubble
                streamedText += evt.content;
                bubble.style.display = '';
                bubble.textContent = streamedText;
              } else if (evt.event === 'tool_call') {
                // Tool invocation starting
                var block = buildToolBlock(evt.name, evt.args);
                toolContainer.appendChild(block);
                currentToolBlocks[evt.id] = block;
                bubble.style.display = 'none';
                streamedText = '';
              } else if (evt.event === 'tools') {
                // Tool result
                var tb = currentToolBlocks[evt.tool_call_id];
                if (tb) {
                  var spinner = tb.querySelector('.tool-spinner');
                  if (spinner) spinner.remove();
                  var status = tb.querySelector('.tool-status');
                  if (status) { status.textContent = 'Done'; status.className = 'tool-status done'; }
                  var outputEl = tb.querySelector('.tool-output');
                  if (outputEl) outputEl.textContent = evt.output;
                }
              } else if (evt.event === 'done') {
                finalContent = evt.content;
                if (finalContent) {
                  bubble.style.display = '';
                  bubble.innerHTML = renderMarkdown(finalContent);
                }
              } else if (evt.event === 'error') {
                bubble.style.display = '';
                bubble.textContent = 'Error: ' + evt.detail;
              }
            } catch (e) {}
          }
          scrollToBottom();
          return pump();
        });
      }
      return pump();
    })
    .catch(function(err) {
      removeTyping(typingEl);
      isWaiting = false;
      setSendDisabled(false);
      addSystemNote('Error: could not reach the server. Please try again.');
      console.error('Send error:', err);
    });
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

  var indicator = document.createElement('div');
  indicator.id = 'typing-indicator';
  for (var i = 0; i < 3; i++) {
    var dot = document.createElement('span');
    dot.className = 'typing-dot';
    indicator.appendChild(dot);
  }

  row.appendChild(label);
  row.appendChild(indicator);
  messagesEl.appendChild(row);
  scrollToBottom();
  return row;
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
