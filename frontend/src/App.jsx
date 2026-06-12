// src/App.jsx — État global, logique sendMessage / notes, montage React

const uid = () => Math.random().toString(36).slice(2, 10);

const API_BASE = window.location.origin + '/api';

// top_k par mode (économie de tokens sur Rapide, exhaustivité sur Approfondi)
const MODE_TOP_K = { rapide: 5, standard: 10, approfondi: 20 };

// Clé API chargée depuis /api/config au démarrage — incluse dans tous les appels /api/*
let _apiKey = '';
const _apiFetch = (url, options = {}) => {
  const headers = { ...(options.headers || {}) };
  if (_apiKey) headers['X-API-Key'] = _apiKey;
  return fetch(url, { ...options, headers });
};

// ── Persistance localStorage ───────────────────────────────────
const loadNotes = () => {
  try { return JSON.parse(localStorage.getItem('nlaz-notes') ?? '[]'); }
  catch { return []; }
};
const saveNotes = (notes) => localStorage.setItem('nlaz-notes', JSON.stringify(notes));

// Cache local des messages — restitution instantanée au reload, en attendant
// l'hydratation depuis l'historique persisté côté serveur (cf. fetchHistory)
const MESSAGES_CACHE_LIMIT = 50;
const loadMessagesCache = () => {
  try { return JSON.parse(localStorage.getItem('nlaz-messages') ?? '[]'); }
  catch { return []; }
};
const saveMessagesCache = (messages) =>
  localStorage.setItem('nlaz-messages', JSON.stringify(messages.slice(-MESSAGES_CACHE_LIMIT)));

const getOrCreateSessionId = () => {
  let sid = localStorage.getItem('nlaz-session');
  if (!sid) { sid = uid(); localStorage.setItem('nlaz-session', sid); }
  return sid;
};

// ── Utilitaire : formate le détail d'erreur renvoyé par l'API ─
// FastAPI renvoie soit une chaîne, soit une liste d'erreurs de
// validation Pydantic ([{ loc, msg, type }, ...])
const formatApiError = (detail) => {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map(e => {
        const field = Array.isArray(e?.loc) ? e.loc.filter(p => p !== 'body').join('.') : '';
        return field ? `${field} : ${e.msg}` : e.msg;
      })
      .join(' · ');
  }
  return JSON.stringify(detail);
};

// ── Utilitaire : Markdown → texte brut (pour aperçu note) ─────
const markdownToPlain = (md) => {
  try {
    const div = document.createElement('div');
    div.innerHTML = marked.parse(md);
    return (div.textContent || div.innerText || '').trim();
  } catch {
    return md.replace(/[#*`_>~\[\]]/g, '').trim();
  }
};

// ── Composant principal ────────────────────────────────────────
const App = () => {
  const [view,          setView]          = React.useState('chat');
  const [messages,      setMessages]      = React.useState(loadMessagesCache);
  const [notes,         setNotes]         = React.useState(loadNotes);
  const [isLoading,     setIsLoading]     = React.useState(false);
  const [input,         setInput]         = React.useState('');
  const [mode,          setMode]          = React.useState('standard');
  const [blankActive,   setBlankActive]   = React.useState(false);
  const [sessionId,     setSessionId]     = React.useState(getOrCreateSessionId);
  const [ingestJob,     setIngestJob]     = React.useState(null);
  const [sources,       setSources]       = React.useState([]);
  const [loadingSources, setLoadingSources] = React.useState(false);
  const ingestPollRef                     = React.useRef(null);

  // ── Récupération de la liste des sources indexées ──────────
  const fetchSources = React.useCallback(async () => {
    setLoadingSources(true);
    try {
      const r = await _apiFetch(`${API_BASE}/sources`);
      if (r.ok) setSources(await r.json());
    } catch { /* silently ignore */ }
    finally { setLoadingSources(false); }
  }, []);

  // Charge la clé API, puis les sources et l'historique de chat au démarrage
  React.useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then(r => r.json())
      .then(cfg => { if (cfg.apiKey) _apiKey = cfg.apiKey; })
      .catch(() => {})
      .then(() => {
        fetchSources();
        return _apiFetch(`${API_BASE}/chat/history/${sessionId}`)
          .then(r => r.ok ? r.json() : null)
          .then(data => { if (data?.messages?.length) setMessages(data.messages); })
          .catch(() => { /* le cache local reste affiché en cas d'échec */ });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchSources]);

  // Actualise les sources dès qu'une ingestion se termine
  React.useEffect(() => {
    if (ingestJob?.status === 'done') fetchSources();
  }, [ingestJob?.status, fetchSources]);

  // Persiste les notes à chaque changement
  React.useEffect(() => { saveNotes(notes); }, [notes]);

  // Persiste les messages (cache local — restitution instantanée au reload)
  React.useEffect(() => { saveMessagesCache(messages); }, [messages]);

  // ── Envoi d'un message ─────────────────────────────────────
  const sendMessage = React.useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setMessages(prev => [...prev, {
      id: uid(), role: 'user',
      content: text, mode,
      timestamp: new Date().toISOString(),
    }]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await _apiFetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message:    text,
          session_id: sessionId,
          top_k:      MODE_TOP_K[mode],
          mode,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(formatApiError(err.detail) || `HTTP ${res.status}`);
      }

      const data = await res.json();

      const citations = (data.sources ?? []).map((s, i) => ({
        id:      i + 1,
        source:  s.file,
        snippet: s.section,
        page:    s.page,
        content: s.content ?? '',
      }));

      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('nlaz-session', data.session_id);
      }

      setMessages(prev => [...prev, {
        id:         uid(),
        role:       'assistant',
        content:    data.answer,
        rawContent: data.answer,
        citations,
        timestamp:  new Date().toISOString(),
        saved:      false,
      }]);

    } catch (err) {
      setMessages(prev => [...prev, {
        id:         uid(),
        role:       'assistant',
        content:    `**Erreur :** ${err.message}\n\nVérifiez que l'API est démarrée et accessible.`,
        rawContent: `**Erreur :** ${err.message}`,
        citations:  [],
        timestamp:  new Date().toISOString(),
        saved:      false,
      }]);
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, mode, sessionId]);

  // ── Enregistrer un message comme note ─────────────────────
  const handleSaveNote = React.useCallback((msg) => {
    const raw    = msg.rawContent || msg.content;
    const plain  = markdownToPlain(raw);
    const source = msg.citations?.[0]?.source ?? undefined;

    setNotes(prev => [{
      id:        uid(),
      text:      raw,
      preview:   plain,
      source,
      messageId: msg.id,
      timestamp: new Date().toISOString(),
    }, ...prev]);

    setMessages(prev => prev.map(m =>
      m.id === msg.id ? { ...m, saved: true } : m
    ));
  }, []);

  // ── Indexer une note comme source ─────────────────────────
  const handleNoteIngest = React.useCallback(async (note) => {
    const slug = note.text.slice(0, 40)
      .replace(/\s+/g, '-')
      .replace(/[^\w-]/g, '')
      .toLowerCase() || 'note';
    const date = new Date(note.timestamp).toISOString().slice(0, 10);
    const filename = `note-${date}-${slug}.md`;
    const file = new File([note.text], filename, { type: 'text/plain' });
    await handleFileUpload(file);
  }, [handleFileUpload]);

  // ── Supprimer une note ─────────────────────────────────────
  const handleDeleteNote = React.useCallback((id) => {
    setNotes(prev => prev.filter(n => n.id !== id));
  }, []);

  // ── Modifier une note ───────────────────────────────────────
  const handleEditNote = React.useCallback((id, text) => {
    setNotes(prev => prev.map(n => {
      if (n.id !== id) return n;
      const { preview, ...rest } = n;
      return { ...rest, text };
    }));
  }, []);

  // ── Nouvelle note manuelle ─────────────────────────────────
  const handleBlankConfirm = React.useCallback((text) => {
    setNotes(prev => [{
      id:        uid(),
      text,
      timestamp: new Date().toISOString(),
    }, ...prev]);
    setBlankActive(false);
  }, []);

  // ── Upload et ingestion d'un fichier ──────────────────────
  const handleFileUpload = React.useCallback(async (file) => {
    if (ingestPollRef.current) { clearInterval(ingestPollRef.current); ingestPollRef.current = null; }

    const formData = new FormData();
    formData.append('file', file);

    setIngestJob({ status: 'pending', filename: file.name, message: 'Envoi du fichier…', chunks: 0 });

    try {
      const res = await _apiFetch(`${API_BASE}/ingest`, { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(formatApiError(err.detail) || `HTTP ${res.status}`);
      }
      const job = await res.json();
      setIngestJob(job);

      ingestPollRef.current = setInterval(async () => {
        try {
          const r = await _apiFetch(`${API_BASE}/ingest/${job.job_id}`);
          const updated = await r.json();
          setIngestJob(updated);
          if (updated.status === 'done' || updated.status === 'error') {
            clearInterval(ingestPollRef.current);
            ingestPollRef.current = null;
            if (updated.status === 'done') {
              setTimeout(() => setIngestJob(null), 6000);
            }
          }
        } catch { /* réseau — on réessaie au prochain tick */ }
      }, 2000);

    } catch (err) {
      setIngestJob({ status: 'error', filename: file.name, message: err.message, chunks: 0 });
    }
  }, []);

  // Nettoyage du polling au démontage
  React.useEffect(() => () => {
    if (ingestPollRef.current) clearInterval(ingestPollRef.current);
  }, []);

  // ── Nouvelle conversation ──────────────────────────────────
  const clearSession = React.useCallback(async () => {
    await _apiFetch(`${API_BASE}/chat/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch(() => {});

    const newSid = uid();
    setSessionId(newSid);
    localStorage.setItem('nlaz-session', newSid);
    setMessages([]);
    localStorage.removeItem('nlaz-messages');
    setInput('');
  }, [sessionId]);

  // ── Rendu ──────────────────────────────────────────────────
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100vh', width: '100vw',
      background: T.white, fontFamily: T.font,
      overflow: 'hidden',
    }}>
      <Header
        onClearSession={clearSession}
        view={view}
        onViewChange={setView}
        apiFetch={_apiFetch}
        apiBase={API_BASE}
      />

      {view === 'graph' ? (
        <GraphPage apiFetch={_apiFetch} />
      ) : (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <SourcesRail
            sources={sources}
            loadingSources={loadingSources}
            ingestJob={ingestJob}
            onUpload={handleFileUpload}
            onRefresh={fetchSources}
            onDismissIngest={() => setIngestJob(null)}
            apiFetch={_apiFetch}
          />
          <ChatPanel
            messages={messages}
            isLoading={isLoading}
            input={input}
            onInputChange={setInput}
            onSend={sendMessage}
            onSaveNote={handleSaveNote}
            mode={mode}
            onModeChange={setMode}
          />
          <NotesRail
            notes={notes}
            onDelete={handleDeleteNote}
            onEditNote={handleEditNote}
            onAddBlank={() => setBlankActive(true)}
            blankActive={blankActive}
            onBlankConfirm={handleBlankConfirm}
            onBlankCancel={() => setBlankActive(false)}
            onIngestNote={handleNoteIngest}
          />
        </div>
      )}
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
