// src/NotesRail.jsx — Rail droit : notes enregistrées
// Props: notes[], onDelete(id), onAddBlank(), blankActive, onBlankConfirm, onBlankCancel, onIngestNote(note)

const NOTE_MAX_CHARS = 140;

// ── Modal de lecture d'une note ────────────────────────────────
const NoteModal = ({ note, onClose, onIngest }) => {
  React.useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const dateStr = new Date(note.timestamp).toLocaleString('fr-FR', {
    day: '2-digit', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });

  return ReactDOM.createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(28, 27, 24, 0.45)',
        backdropFilter: 'blur(3px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 999,
        animation: 'nlModalIn .15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: T.white,
          borderRadius: T.radiusLg,
          width: '90%', maxWidth: 620,
          maxHeight: '78vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 24px 64px rgba(0,0,0,0.22)',
          overflow: 'hidden',
        }}
      >
        {/* En-tête */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          padding: '18px 20px 14px',
          borderBottom: `1px solid ${T.border}`,
          flexShrink: 0, gap: 12,
        }}>
          <div style={{ minWidth: 0 }}>
            {note.source && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <Ic.Doc s={13} />
                <span style={{
                  fontSize: 13, fontWeight: 600, color: T.sub,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {note.source}
                </span>
              </div>
            )}
            <span style={{ fontSize: 11.5, color: T.muted, fontFamily: T.font }}>{dateStr}</span>
          </div>
          <button
            onClick={onClose}
            title="Fermer (Échap)"
            style={{
              display: 'grid', placeItems: 'center', flexShrink: 0,
              width: 30, height: 30, borderRadius: 8,
              border: 'none', background: 'transparent',
              color: T.muted, cursor: 'pointer',
              transition: 'background .12s, color .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = T.panel; e.currentTarget.style.color = T.ink; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = T.muted; }}
          >
            <Ic.Close s={16} />
          </button>
        </div>

        {/* Corps */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '22px 24px' }}>
          <p style={{
            margin: 0,
            fontSize: 15, lineHeight: 1.75,
            color: T.ink, fontFamily: T.font,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>
            {note.text}
          </p>
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 20px',
          borderTop: `1px solid ${T.border}`,
          display: 'flex', justifyContent: 'flex-end',
          flexShrink: 0,
        }}>
          <button
            onClick={() => { onIngest(note); onClose(); }}
            style={{
              display: 'flex', alignItems: 'center', gap: 7,
              height: 34, padding: '0 16px',
              borderRadius: T.radiusPill,
              border: `1px solid ${T.azureBorder}`,
              background: T.azureSoft,
              color: T.azureInk,
              fontFamily: T.font, fontSize: 13, fontWeight: 500,
              cursor: 'pointer', transition: 'all .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = T.azureBorder; e.currentTarget.style.borderColor = T.azure; }}
            onMouseLeave={e => { e.currentTarget.style.background = T.azureSoft; e.currentTarget.style.borderColor = T.azureBorder; }}
            title="Indexer cette note dans Azure AI Search comme une source"
          >
            <Ic.Upload s={14} />
            Indexer comme source
          </button>
        </div>
      </div>

      <style>{`
        @keyframes nlModalIn { from { opacity: 0; } to { opacity: 1; } }
      `}</style>
    </div>,
    document.body
  );
};

// ── Carte de note ──────────────────────────────────────────────
const NoteCard = ({ note, onDelete, onOpen, onIngest }) => {
  const [hovered, setHovered] = React.useState(false);

  const isTruncated = note.text.length > NOTE_MAX_CHARS;
  const preview = isTruncated
    ? note.text.slice(0, NOTE_MAX_CHARS) + '…'
    : note.text;

  const timeStr = new Date(note.timestamp).toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit',
  });

  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${hovered ? T.borderStrong : T.border}`,
        borderRadius: T.radiusMd, padding: '12px 13px',
        position: 'relative', transition: 'border-color .12s, background .12s',
        cursor: 'pointer',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onOpen(note)}
      title="Cliquer pour lire"
    >
      {/* Bouton supprimer */}
      <button
        onClick={e => { e.stopPropagation(); onDelete(note.id); }}
        title="Supprimer cette note"
        style={{
          position: 'absolute', top: 9, right: 9,
          display: 'grid', placeItems: 'center',
          width: 22, height: 22, borderRadius: 6,
          border: 'none', background: hovered ? T.panel2 : 'transparent',
          color: T.muted, cursor: 'pointer',
          opacity: hovered ? 1 : 0,
          transition: 'opacity .12s, background .12s, color .12s',
        }}
        onMouseEnter={e => { e.currentTarget.style.color = T.danger; e.currentTarget.style.background = '#fee2e2'; }}
        onMouseLeave={e => { e.currentTarget.style.color = T.muted; e.currentTarget.style.background = T.panel2; }}
      >
        <Ic.Close s={12} />
      </button>

      {/* Aperçu texte */}
      <p style={{
        margin: '0 20px 8px 0',
        fontSize: 13.5, lineHeight: 1.5,
        color: T.ink, fontFamily: T.font,
        wordBreak: 'break-word',
      }}>
        {preview}
      </p>

      {/* Méta : ingest + source + heure */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <button
          onClick={e => { e.stopPropagation(); onIngest(note); }}
          title="Indexer cette note comme source"
          style={{
            display: 'flex', alignItems: 'center',
            padding: 0, border: 'none', background: 'transparent',
            color: T.azure,
            cursor: 'pointer', flexShrink: 0,
            opacity: hovered ? 1 : 0,
            transition: 'opacity .12s, color .12s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = T.azureHover}
          onMouseLeave={e => e.currentTarget.style.color = T.azure}
        >
          <Ic.Upload s={13} />
        </button>

        {note.source && (
          <span style={{
            display: 'flex', alignItems: 'center', gap: 4,
            fontSize: 11, fontWeight: 600, color: T.sub,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            flex: 1, minWidth: 0,
          }}>
            <Ic.Doc s={11} /> {note.source}
          </span>
        )}
        <span style={{ fontSize: 11, color: T.muted, marginLeft: 'auto', flexShrink: 0 }}>{timeStr}</span>
      </div>
    </div>
  );
};

// ── Note vierge éditable ───────────────────────────────────────
const BlankNoteCard = ({ onConfirm, onCancel }) => {
  const [text, setText] = React.useState('');
  const ref = React.useRef(null);

  React.useEffect(() => { ref.current?.focus(); }, []);

  const confirm = () => {
    if (text.trim()) onConfirm(text.trim());
    else onCancel();
  };

  return (
    <div style={{
      background: T.azureSoft, border: `1px solid ${T.azureBorder}`,
      borderRadius: T.radiusMd, padding: '12px 13px',
    }}>
      <textarea
        ref={ref}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); confirm(); }
          if (e.key === 'Escape') onCancel();
        }}
        onBlur={confirm}
        placeholder="Saisissez une note…"
        rows={3}
        style={{
          width: '100%', boxSizing: 'border-box',
          border: 'none', outline: 'none', resize: 'none',
          background: 'transparent', fontFamily: T.font,
          fontSize: 13.5, lineHeight: 1.5, color: T.ink,
        }}
      />
      <p style={{ margin: '6px 0 0', fontSize: 11, color: T.azureInk, fontFamily: T.font }}>
        Entrée pour confirmer · Échap pour annuler
      </p>
    </div>
  );
};

// ── Rail principal ─────────────────────────────────────────────
const NotesRail = ({ notes, onDelete, onAddBlank, blankActive, onBlankConfirm, onBlankCancel, onIngestNote }) => {
  const [openNote, setOpenNote]           = React.useState(null);
  const [width, setWidth]                 = React.useState(264);
  const [handleHovered, setHandleHovered] = React.useState(false);
  const isDragging                        = React.useRef(false);
  const dragStartX                        = React.useRef(0);
  const dragStartW                        = React.useRef(0);

  const onHandleMouseDown = (e) => {
    e.preventDefault();
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartW.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (ev) => {
      if (!isDragging.current) return;
      const newW = Math.max(160, Math.min(480, dragStartW.current + (dragStartX.current - ev.clientX)));
      setWidth(newW);
    };
    const onUp = () => {
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  return (
    <aside style={{
      width, flexShrink: 0,
      borderLeft: `1px solid ${handleHovered ? T.azure : T.border}`,
      background: T.railBg,
      display: 'flex', flexDirection: 'column',
      fontFamily: T.font,
      overflow: 'hidden',
      position: 'relative',
      transition: 'border-color .15s',
    }}>
      {/* Poignée de redimensionnement — bord gauche */}
      <div
        onMouseDown={onHandleMouseDown}
        onMouseEnter={() => setHandleHovered(true)}
        onMouseLeave={() => setHandleHovered(false)}
        style={{
          position: 'absolute', top: 0, bottom: 0, left: -4,
          width: 8, cursor: 'col-resize', zIndex: 10,
          display: 'flex', alignItems: 'stretch', justifyContent: 'center',
        }}
      >
        <div style={{
          width: 2, borderRadius: 1,
          background: handleHovered ? T.azure : 'transparent',
          transition: 'background .15s',
        }} />
      </div>

      {/* Modal lecture */}
      {openNote && (
        <NoteModal
          note={openNote}
          onClose={() => setOpenNote(null)}
          onIngest={onIngestNote}
        />
      )}

      {/* En-tête */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 16px 12px',
        borderBottom: `1px solid ${T.border}`,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: T.ink, letterSpacing: 0.2 }}>
          Notes
        </span>
        {notes.length > 0 && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: T.muted,
            background: T.white, border: `1px solid ${T.border}`,
            borderRadius: T.radiusPill, padding: '2px 8px',
          }}>
            {notes.length}
          </span>
        )}
      </div>

      {/* Liste (scrollable) */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 14px 4px', scrollbarWidth: 'none' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

          {blankActive && (
            <BlankNoteCard onConfirm={onBlankConfirm} onCancel={onBlankCancel} />
          )}

          {notes.map(note => (
            <NoteCard
              key={note.id}
              note={note}
              onDelete={onDelete}
              onOpen={setOpenNote}
              onIngest={onIngestNote}
            />
          ))}

          {notes.length === 0 && !blankActive && (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              gap: 8, padding: '40px 0', color: T.muted, textAlign: 'center',
            }}>
              <Ic.Bookmark s={28} />
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55 }}>
                Enregistrez des réponses<br />de l'agent ici
              </p>
              <p style={{ margin: 0, fontSize: 11.5, color: T.muted, lineHeight: 1.5 }}>
                Construisez vos notes, puis<br />indexez-les comme source.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Bouton ajouter */}
      <div style={{ padding: '10px 14px 16px', flexShrink: 0 }}>
        <button
          onClick={onAddBlank}
          disabled={blankActive}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
            width: '100%', height: 38,
            borderRadius: T.radiusMd,
            border: `1px dashed ${T.borderStrong}`,
            background: 'transparent', color: T.sub,
            fontFamily: T.font, fontSize: 12.5, fontWeight: 500,
            cursor: blankActive ? 'default' : 'pointer',
            opacity: blankActive ? 0.4 : 1,
            transition: 'background .12s',
          }}
          onMouseEnter={e => { if (!blankActive) e.currentTarget.style.background = T.panel; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          <Ic.Plus s={14} /> Ajouter une note
        </button>
      </div>
    </aside>
  );
};

Object.assign(window, { NotesRail });
