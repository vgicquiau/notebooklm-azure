// src/ChatPanel.jsx — Liste de messages + barre de saisie
// Props: messages[], isLoading, input, onInputChange(), onSend(), onSaveNote(),
//        mode, onModeChange()

// ── Rendu Markdown ─────────────────────────────────────────────
const MarkdownContent = ({ text }) => {
  if (!text) return null;
  const html = DOMPurify.sanitize(marked.parse(text));
  return (
    <div
      className="nlaz-md"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};

// ── Config modes ───────────────────────────────────────────────
const MODE_CONFIG = {
  rapide:     { label: 'Rapide',     icon: Ic.Lightning, color: '#059669', bg: '#ecfdf5', border: '#a7f3d0' },
  standard:   { label: 'Standard',  icon: Ic.Search,    color: '#2563eb', bg: '#eff6ff', border: '#bfdbfe' },
  approfondi: { label: 'Approfondi',icon: Ic.Microscope,color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
};

// ── Indicateur de chargement ───────────────────────────────────
const TypingDots = ({ mode }) => {
  const labels = {
    rapide: 'Recherche rapide…',
    standard: 'Analyse en cours…',
    approfondi: 'Analyse approfondie…',
  };
  const dot = (delay) => (
    <span style={{
      display: 'inline-block', width: 6, height: 6, borderRadius: 3,
      background: T.muted, margin: '0 2px',
      animation: `nlDotBounce 1.2s ${delay}s ease-in-out infinite`,
    }} />
  );
  return (
    <div style={{ display: 'flex', gap: 14, marginBottom: 26 }}>
      <Logo s={28} r={9} />
      <div style={{ display: 'flex', alignItems: 'center', padding: '10px 0', gap: 10 }}>
        <div>{dot(0)}{dot(0.2)}{dot(0.4)}</div>
        <span style={{ fontSize: 13.5, color: T.muted, fontFamily: T.font }}>
          {labels[mode] || 'Analyse en cours…'}
        </span>
      </div>
    </div>
  );
};

// ── Message utilisateur ────────────────────────────────────────
const UserMessage = ({ msg }) => {
  const mc = MODE_CONFIG[msg.mode];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginBottom: 22 }}>
      {mc && (
        <span className={`nlaz-mode-tag ${msg.mode}`} style={{ marginBottom: 5 }}>
          {mc.label}
        </span>
      )}
      <div style={{
        maxWidth: '74%', background: T.panel,
        borderRadius: T.radiusLg, padding: '12px 18px',
        fontSize: 15.5, lineHeight: 1.55, color: T.ink,
        fontFamily: T.font,
      }}>
        {msg.content}
      </div>
    </div>
  );
};

// ── Modale de visualisation d'un chunk source ─────────────────
const CitationModal = ({ citation, onClose }) => {
  React.useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return ReactDOM.createPortal(
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 500,
        background: 'rgba(28,27,24,0.45)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: T.white, borderRadius: T.radiusLg,
          width: '100%', maxWidth: 680, maxHeight: '80vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
          overflow: 'hidden',
          animation: 'nlCiteModalIn .18s ease',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* En-tête */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          padding: '16px 18px 14px',
          borderBottom: `1px solid ${T.border}`,
          flexShrink: 0,
        }}>
          <span style={{
            display: 'grid', placeItems: 'center',
            width: 24, height: 24, borderRadius: 7, flexShrink: 0,
            background: T.azure, color: '#fff', fontSize: 12, fontWeight: 700,
          }}>
            {citation.id}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: 14, fontWeight: 700, color: T.ink,
              wordBreak: 'break-word', lineHeight: 1.4,
            }}>
              {citation.source}
              {citation.page != null && (
                <span style={{ fontWeight: 400, color: T.muted, marginLeft: 8, fontSize: 13 }}>
                  p.{citation.page}
                </span>
              )}
            </div>
            {citation.snippet && (
              <div style={{ fontSize: 12.5, color: T.sub, marginTop: 3, fontFamily: T.font }}>
                {citation.snippet}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{
              border: 'none', background: 'transparent',
              cursor: 'pointer', color: T.muted, padding: 4, flexShrink: 0,
              borderRadius: 6, transition: 'background .12s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = T.panel}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <Ic.Close s={16} />
          </button>
        </div>

        {/* Corps — texte du chunk */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '18px 22px 22px' }}>
          {citation.content
            ? <MarkdownContent text={citation.content} />
            : <p style={{ color: T.muted, fontFamily: T.font, fontSize: 14 }}>
                Contenu non disponible.
              </p>
          }
        </div>
      </div>
      <style>{`
        @keyframes nlCiteModalIn {
          from { opacity: 0; transform: scale(.97) translateY(6px); }
          to   { opacity: 1; transform: none; }
        }
      `}</style>
    </div>,
    document.body
  );
};

// ── Fiche source ───────────────────────────────────────────────
const SourceCard = ({ citation, onClick }) => {
  const [hovered, setHovered] = React.useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', gap: 10, padding: '11px 13px',
        border: `1px solid ${hovered ? T.azureBorder : T.border}`,
        borderRadius: T.radiusMd,
        background: hovered ? T.azureSoft : T.white,
        cursor: 'pointer',
        transition: 'background .12s, border-color .12s',
      }}
      title="Voir le passage source"
    >
      {/* Badge numéroté */}
      <span style={{
        display: 'grid', placeItems: 'center',
        width: 20, height: 20, borderRadius: 6, flexShrink: 0,
        background: T.azure, color: '#fff', fontSize: 10.5, fontWeight: 700,
      }}>
        {citation.id}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontSize: 12.5, fontWeight: 600, color: T.ink,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 3,
        }}>
          {citation.source}
          {citation.page != null && (
            <span style={{ fontWeight: 400, color: T.muted, marginLeft: 6 }}>p.{citation.page}</span>
          )}
        </div>
        {citation.snippet && (
          <div style={{
            fontSize: 12, color: T.sub, lineHeight: 1.45,
            overflow: 'hidden', display: '-webkit-box',
            WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          }}>
            {citation.snippet}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Message assistant ──────────────────────────────────────────
const AssistantMessage = ({ msg, onSaveNote }) => {
  const [copied,        setCopied]        = React.useState(false);
  const [openCitation,  setOpenCitation]  = React.useState(null);

  const handleCopy = () => {
    navigator.clipboard?.writeText(msg.rawContent || msg.content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const btnBase = {
    display: 'flex', alignItems: 'center', gap: 6,
    height: 30, padding: '0 12px',
    border: `1px solid ${T.border}`, borderRadius: 9,
    background: T.white, color: T.sub,
    fontFamily: T.font, fontSize: 12.5, fontWeight: 500,
    cursor: 'pointer', whiteSpace: 'nowrap',
    transition: 'background .12s',
  };

  // Filtre : uniquement les sources réellement citées [N] dans la réponse
  const citedNums = new Set(
    [...(msg.content || '').matchAll(/\[(\d+)\]/g)].map(m => Number(m[1]))
  );
  const visibleCitations = (msg.citations ?? []).filter(c => citedNums.has(c.id));
  const hasCitations = visibleCitations.length > 0;

  const handleCitationClick = React.useCallback((num) => {
    const c = visibleCitations.find(c => c.id === num);
    if (c) setOpenCitation(c);
  }, [visibleCitations]);

  return (
    <div style={{ display: 'flex', gap: 14, marginBottom: 28 }}>
      {openCitation && (
        <CitationModal citation={openCitation} onClose={() => setOpenCitation(null)} />
      )}
      <Logo s={28} r={9} />
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Rendu Markdown + Mermaid + badges citation cliquables */}
        <MarkdownContent
          text={msg.content}
          hasCitations={hasCitations}
          onCitationClick={hasCitations ? handleCitationClick : undefined}
        />

        {/* Fiches sources — uniquement celles citées dans le texte */}
        {hasCitations && (
          <div style={{ marginTop: 14, marginBottom: 14 }}>
            <div style={{
              fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6,
              textTransform: 'uppercase', color: T.muted, marginBottom: 9,
            }}>
              Références
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 10 }}>
              {visibleCitations.map(c => (
                <SourceCard key={c.id} citation={c} onClick={() => setOpenCitation(c)} />
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
          <button
            onClick={() => !msg.saved && onSaveNote(msg)}
            style={{
              ...btnBase,
              background: msg.saved ? T.azureSoft : T.white,
              color:      msg.saved ? T.azureInk  : T.sub,
              borderColor:msg.saved ? T.azureBorder: T.border,
              cursor:     msg.saved ? 'default'    : 'pointer',
            }}
            onMouseEnter={e => { if (!msg.saved) e.currentTarget.style.background = T.panel; }}
            onMouseLeave={e => { if (!msg.saved) e.currentTarget.style.background = msg.saved ? T.azureSoft : T.white; }}
          >
            {msg.saved
              ? <><Ic.Check s={13} /> Enregistré</>
              : <><Ic.Bookmark s={13} /> Enregistrer</>}
          </button>

          <button
            onClick={handleCopy}
            style={btnBase}
            onMouseEnter={e => e.currentTarget.style.background = T.panel}
            onMouseLeave={e => e.currentTarget.style.background = T.white}
            title="Copier le Markdown brut"
          >
            {copied
              ? <><Ic.Check s={13} /> Copié !</>
              : <><Ic.Copy s={13} /> Copier</>}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Sélecteur de mode ──────────────────────────────────────────
const ModeSelector = ({ mode, onChange }) => (
  <div style={{ display: 'flex', gap: 2 }}>
    {Object.entries(MODE_CONFIG).map(([key, cfg]) => {
      const active = mode === key;
      const Icon = cfg.icon;
      return (
        <button
          key={key}
          onClick={() => onChange(key)}
          title={`Mode ${cfg.label}`}
          style={{
            display: 'flex', alignItems: 'center', gap: 5,
            height: 28, padding: '0 10px',
            borderRadius: T.radiusPill,
            border: active ? `1px solid ${cfg.border}` : '1px solid transparent',
            background: active ? cfg.bg : 'transparent',
            color: active ? cfg.color : T.muted,
            fontFamily: T.font, fontSize: 12, fontWeight: active ? 700 : 500,
            cursor: 'pointer', transition: 'all .12s', whiteSpace: 'nowrap',
          }}
          onMouseEnter={e => { if (!active) { e.currentTarget.style.background = T.panel; e.currentTarget.style.color = T.sub; } }}
          onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = T.muted; } }}
        >
          <Icon s={12} /> {cfg.label}
        </button>
      );
    })}
  </div>
);

// ── Panneau principal ──────────────────────────────────────────
const ChatPanel = ({ messages, isLoading, input, onInputChange, onSend, onSaveNote, mode, onModeChange }) => {
  const listRef = React.useRef(null);
  const textareaRef = React.useRef(null);

  React.useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }
  };

  // Auto-resize textarea
  const handleInput = (e) => {
    onInputChange(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px';
  };

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>

      {/* Liste des messages */}
      <div ref={listRef} style={{
        flex: 1, overflow: 'auto', padding: '28px 32px 8px',
        display: 'flex', flexDirection: 'column',
      }}>
        {messages.length === 0 && !isLoading && (
          <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 12, color: T.muted,
          }}>
            <Logo s={40} r={13} />
            <p style={{ margin: 0, fontSize: 15, fontFamily: T.font, textAlign: 'center' }}>
              Posez une question à votre agent
            </p>
            <p style={{ margin: 0, fontSize: 13, fontFamily: T.font, color: T.muted, textAlign: 'center', maxWidth: 380, lineHeight: 1.6 }}>
              Exemples : <em>"Quelles sont les règles de gestion du module de facturation ?"</em>
              · <em>"Liste tous les flux détectés dans les sources"</em>
            </p>
          </div>
        )}

        <div style={{ maxWidth: 660, width: '100%', margin: '0 auto' }}>
          {messages.map(msg =>
            msg.role === 'user'
              ? <UserMessage key={msg.id} msg={msg} />
              : <AssistantMessage key={msg.id} msg={msg} onSaveNote={onSaveNote} />
          )}
          {isLoading && <TypingDots mode={mode} />}
        </div>
      </div>

      {/* Barre de saisie */}
      <div style={{ padding: '6px 32px 20px' }}>
        <div style={{ maxWidth: 660, margin: '0 auto' }}>
          <div style={{
            borderRadius: T.radiusLg,
            border: `1px solid ${T.borderStrong}`,
            background: T.white,
            boxShadow: '0 1px 4px rgba(0,0,0,.05)',
            overflow: 'hidden',
          }}>
            {/* Zone de texte */}
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, padding: '8px 8px 6px 14px' }}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                placeholder="Posez une question sur vos sources…"
                rows={1}
                style={{
                  flex: 1, border: 'none', outline: 'none', resize: 'none',
                  background: 'transparent', fontFamily: T.font,
                  fontSize: 15, color: T.ink, lineHeight: 1.55,
                  padding: '6px 0', maxHeight: 140, overflowY: 'auto',
                }}
              />

              <button
                onClick={onSend}
                disabled={!input.trim() || isLoading}
                style={{
                  display: 'grid', placeItems: 'center',
                  width: 38, height: 38, flexShrink: 0,
                  border: 'none', borderRadius: T.radiusPill,
                  background: input.trim() && !isLoading ? T.azure : T.panel2,
                  color: input.trim() && !isLoading ? '#fff' : T.muted,
                  cursor: input.trim() && !isLoading ? 'pointer' : 'default',
                  transition: 'background .15s, color .15s', alignSelf: 'flex-end',
                }}
              >
                <Ic.Up />
              </button>
            </div>

            {/* Barre du bas : mode selector */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '6px 14px 10px',
              borderTop: `1px solid ${T.border}`,
            }}>
              <ModeSelector mode={mode} onChange={onModeChange} />
              <span style={{ fontSize: 11.5, color: T.muted, fontFamily: T.font }}>
                {input.length > 0 ? `${input.length} / 4000` : 'Maj+Entrée pour sauter une ligne'}
              </span>
            </div>
          </div>

          <p style={{
            textAlign: 'center', fontSize: 11.5, color: T.muted,
            margin: '9px 0 0', fontFamily: T.font,
          }}>
            Les réponses s'appuient sur vos documents. Vérifiez les informations importantes.
          </p>
        </div>
      </div>

      <style>{`
        @keyframes nlDotBounce {
          0%, 60%, 100% { transform: translateY(0); opacity: .4; }
          30%            { transform: translateY(-5px); opacity: 1; }
        }
        textarea::placeholder { color: ${T.muted}; }
      `}</style>
    </div>
  );
};

Object.assign(window, { ChatPanel, MarkdownContent });
