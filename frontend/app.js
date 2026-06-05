const API_BASE = window.location.origin + '/api';

let sessionId = null;

const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const btnSend = document.getElementById('btn-send');
const btnClear = document.getElementById('btn-clear');
const charCount = document.getElementById('char-count');

// ── Markdown (marked.js) ─────────────────────────────────────────────────────
marked.setOptions({ breaks: true, gfm: true });

// ── Mermaid — securityLevel:'strict' désactive HTML dans les labels (SEC-002) ─
mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });

async function renderMermaid(container) {
  const blocks = container.querySelectorAll('code.language-mermaid');
  for (let i = 0; i < blocks.length; i++) {
    const codeEl = blocks[i];
    const pre = codeEl.closest('pre');
    if (!pre) continue;
    try {
      const id = `mermaid-${Date.now()}-${i}`;
      const { svg } = await mermaid.render(id, codeEl.textContent.trim());
      const wrapper = document.createElement('div');
      wrapper.className = 'mermaid-diagram';
      wrapper.innerHTML = svg;
      pre.replaceWith(wrapper);
    } catch {
      pre.classList.add('mermaid-error');
    }
  }
}

// ── Mode selector ─────────────────────────────────────────────────────────────
const modeButtons = document.querySelectorAll('.mode-btn');
let currentMode = 'standard';

const MODE_TOP_K  = { rapide: 5, standard: 10, approfondi: 20 };
const MODE_LABEL  = { rapide: '⚡ Rapide', standard: '📋 Standard', approfondi: '🔬 Approfondi' };

modeButtons.forEach(btn => {
  btn.addEventListener('click', () => {
    modeButtons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentMode = btn.dataset.mode;
  });
});

// ── Input ─────────────────────────────────────────────────────────────────────
userInput.addEventListener('input', () => {
  charCount.textContent = `${userInput.value.length} / 4000`;
});
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
btnSend.addEventListener('click', sendMessage);
btnClear.addEventListener('click', clearSession);

// ── Message rendering ─────────────────────────────────────────────────────────
function appendMessage(role, rawContent, sources = [], mode = null) {
  document.getElementById('welcome')?.remove();

  const msg = document.createElement('div');
  msg.className = `message ${role}`;

  // Mode tag above user bubble
  if (role === 'user' && mode) {
    const modeTag = document.createElement('span');
    modeTag.className = `mode-tag mode-${mode}`;
    modeTag.textContent = MODE_LABEL[mode];
    msg.appendChild(modeTag);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (role === 'assistant') {
    // Mode header inside assistant bubble
    if (mode) {
      const modeHeader = document.createElement('div');
      modeHeader.className = 'response-mode';
      modeHeader.textContent = `Réponse en mode ${MODE_LABEL[mode]}`;
      bubble.appendChild(modeHeader);
    }

    // Rendered markdown content
    const contentDiv = document.createElement('div');
    contentDiv.className = 'md-content';
    contentDiv.innerHTML = marked.parse(rawContent);
    bubble.appendChild(contentDiv);

    // Copy raw markdown button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn-copy';
    copyBtn.innerHTML = '📋 Copier le Markdown';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(rawContent).then(() => {
        copyBtn.innerHTML = '✓ Copié !';
        setTimeout(() => { copyBtn.innerHTML = '📋 Copier le Markdown'; }, 2000);
      });
    });
    bubble.appendChild(copyBtn);

    msg.appendChild(bubble);
    chatContainer.appendChild(msg);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Render mermaid blocks after DOM insertion
    renderMermaid(contentDiv);

  } else {
    bubble.textContent = rawContent;
    msg.appendChild(bubble);
    chatContainer.appendChild(msg);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  if (sources.length > 0) {
    const srcDiv = document.createElement('div');
    srcDiv.className = 'sources';
    srcDiv.innerHTML = `<strong>Sources :</strong> ` +
      sources.map(s =>
        `<span class="source-item">📄 ${escapeHtml(s.file)} p.${s.page}${s.section ? ` — ${escapeHtml(s.section.substring(0, 40))}` : ''}</span>`
      ).join('');
    msg.appendChild(srcDiv);
  }

  return msg;
}

function appendLoading(mode) {
  const labels = { rapide: 'Recherche rapide…', standard: 'Recherche en cours…', approfondi: 'Analyse approfondie…' };
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = 'loading-indicator';
  div.innerHTML = `<div class="loading">
    <div class="dots"><span>●</span><span>●</span><span>●</span></div>
    ${labels[mode] || 'Recherche en cours…'}
  </div>`;
  chatContainer.appendChild(div);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function removeLoading() {
  document.getElementById('loading-indicator')?.remove();
}

// ── Send ──────────────────────────────────────────────────────────────────────
async function sendMessage() {
  const text = userInput.value.trim();
  if (!text || btnSend.disabled) return;

  const mode = currentMode;
  userInput.value = '';
  charCount.textContent = '0 / 4000';
  btnSend.disabled = true;

  appendMessage('user', text, [], mode);
  appendLoading(mode);

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId, top_k: MODE_TOP_K[mode], mode }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const data = await response.json();
    sessionId = data.session_id;
    removeLoading();
    appendMessage('assistant', data.answer, data.sources, mode);

  } catch (err) {
    removeLoading();
    appendMessage('assistant', `❌ Erreur : ${err.message}`);
  } finally {
    btnSend.disabled = false;
    userInput.focus();
  }
}

// ── Clear ─────────────────────────────────────────────────────────────────────
async function clearSession() {
  if (sessionId) {
    // session_id dans le body — ne plus exposer en URL (SEC-015)
    await fetch(`${API_BASE}/chat/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch(() => {});
    sessionId = null;
  }
  chatContainer.innerHTML = `
    <div class="welcome-message" id="welcome">
      <p>Posez une question sur vos documents métier, spécifications techniques ou règles métier.</p>
      <p class="hint">Exemples : <em>"Quelles sont les règles de gestion du module de facturation ?"</em></p>
    </div>`;
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
