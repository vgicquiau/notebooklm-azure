// src/SourcesRail.jsx — Rail gauche : sources indexées dans Azure AI Search

// ── Carte d'ingestion en cours ─────────────────────────────────────────
const IngestCard = ({ job, onDismiss }) => {
  if (!job) return null;

  const STATUS = {
    pending: { color: T.sub,      bg: T.panel,     border: T.borderStrong, icon: '⏳' },
    running: { color: T.azureInk, bg: T.azureSoft, border: T.azureBorder,  icon: '⏳' },
    done:    { color: '#166534',   bg: '#f0fdf4',   border: '#bbf7d0',      icon: '✓'  },
    error:   { color: '#991b1b',   bg: '#fef2f2',   border: '#fecaca',      icon: '✗'  },
  };
  const s = STATUS[job.status] || STATUS.running;

  return (
    <div style={{
      margin: '0 10px 8px',
      padding: '10px 12px',
      background: s.bg,
      borderRadius: T.radiusMd,
      border: `1px solid ${s.border}`,
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 3 }}>
        <span style={{ fontSize: 12, flexShrink: 0 }}>{s.icon}</span>
        <span style={{
          flex: 1, minWidth: 0,
          fontSize: 12, fontWeight: 600, color: s.color,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{job.filename}</span>
        {(job.status === 'error') && (
          <button
            onClick={onDismiss}
            style={{
              border: 'none', background: 'transparent', color: s.color,
              cursor: 'pointer', opacity: 0.6, padding: 0, flexShrink: 0,
              display: 'flex', alignItems: 'center',
            }}
          >
            <Ic.Close s={12} />
          </button>
        )}
      </div>
      <div style={{ fontSize: 11, color: s.color, opacity: 0.85, lineHeight: 1.4, paddingLeft: 19 }}>
        {job.message}
      </div>
      {job.status === 'running' && (
        <div style={{ marginTop: 6, height: 3, background: T.azureBorder, borderRadius: 99, overflow: 'hidden' }}>
          <div style={{
            height: '100%', background: T.azure, borderRadius: 99,
            animation: 'nlSrcPulse 1.4s ease-in-out infinite',
          }} />
          <style>{`@keyframes nlSrcPulse {
            0%   { width: 15%; margin-left: 0;   }
            50%  { width: 50%; margin-left: 25%; }
            100% { width: 15%; margin-left: 85%; }
          }`}</style>
        </div>
      )}
      {job.chunks > 0 && (
        <div style={{ marginTop: 3, fontSize: 10.5, color: s.color, opacity: 0.7, paddingLeft: 19 }}>
          {job.chunks} chunks indexés
        </div>
      )}
    </div>
  );
};


// ── Modal de prévisualisation d'un document ───────────────────────────
const SourcePreviewModal = ({ preview, loading, onClose }) => {
  if (!preview) return null;

  // Fermeture avec Escape
  React.useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const { source, chunks } = preview;

  return ReactDOM.createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'rgba(0,0,0,0.42)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '32px',
        animation: 'nlSrcFadeIn .15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 740, maxHeight: '78vh',
          background: T.white, borderRadius: T.radiusLg,
          border: `1px solid ${T.border}`,
          boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
          animation: 'nlSrcSlideUp .18s ease',
        }}
      >
        {/* En-tête */}
        <div style={{
          padding: '16px 20px 14px',
          borderBottom: `1px solid ${T.border}`,
          display: 'flex', alignItems: 'flex-start', gap: 12,
          flexShrink: 0,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ color: T.azure, flexShrink: 0 }}><Ic.Doc s={15} /></span>
              <span style={{
                fontSize: 14, fontWeight: 700, color: T.ink,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {source.source_file}
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: T.sub, paddingLeft: 23 }}>
              {source.chunk_count} chunks indexés
              {source.created_at && (
                <span> · {new Date(source.created_at).toLocaleDateString('fr-FR')}</span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              color: T.muted, padding: 4, borderRadius: T.radiusSm,
              display: 'flex', alignItems: 'center',
              transition: 'color .12s',
              flexShrink: 0,
            }}
            onMouseEnter={e => e.currentTarget.style.color = T.ink}
            onMouseLeave={e => e.currentTarget.style.color = T.muted}
          >
            <Ic.Close s={18} />
          </button>
        </div>

        {/* Contenu scrollable */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading ? (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: 120, color: T.sub, fontSize: 13,
            }}>
              Chargement du contenu…
            </div>
          ) : chunks.length === 0 ? (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: 120, color: T.muted, fontSize: 13,
            }}>
              Aucun contenu disponible.
            </div>
          ) : (
            chunks.map((chunk, i) => (
              <div key={i} style={{
                padding: '13px 20px',
                borderBottom: i < chunks.length - 1 ? `1px solid ${T.border}` : 'none',
              }}>
                <div style={{
                  fontSize: 10.5, fontWeight: 700, color: T.azure,
                  marginBottom: 5, textTransform: 'uppercase', letterSpacing: 0.5,
                }}>
                  {chunk.section
                    ? `p.${chunk.page_number} — ${chunk.section}`
                    : `Page ${chunk.page_number}`}
                </div>
                <MarkdownContent text={chunk.content} />
              </div>
            ))
          )}
        </div>
      </div>

      <style>{`
        @keyframes nlSrcFadeIn  { from { opacity: 0; } to { opacity: 1; } }
        @keyframes nlSrcSlideUp { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
      `}</style>
    </div>,
    document.body
  );
};


// ── Carte d'une source indexée ────────────────────────────────────────
const DocCard = ({ source, onView, onDelete }) => {
  const [hovered,    setHovered]    = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);

  return (
    <div
      onClick={() => { if (!confirming) onView(source); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setConfirming(false); }}
      style={{
        padding: '9px 12px',
        margin: '0 6px 2px',
        borderRadius: T.radiusMd,
        border: `1px solid ${hovered ? T.borderStrong : 'transparent'}`,
        background: hovered ? T.panel : 'transparent',
        cursor: confirming ? 'default' : 'pointer',
        transition: 'background .1s, border-color .1s',
      }}
    >
      {/* Ligne filename + bouton suppression au survol */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: T.azure, flexShrink: 0 }}><Ic.Doc s={13} /></span>
        <span style={{
          flex: 1, minWidth: 0,
          fontSize: 12, fontWeight: 600, color: T.ink,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {source.source_file}
        </span>

        {hovered && !confirming && (
          <button
            onClick={e => { e.stopPropagation(); setConfirming(true); }}
            title="Supprimer de l'index"
            style={{
              width: 22, height: 22, border: 'none', flexShrink: 0,
              background: '#fef2f2', borderRadius: 6,
              cursor: 'pointer', color: T.danger,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background .1s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#fecaca'}
            onMouseLeave={e => e.currentTarget.style.background = '#fef2f2'}
          >
            <Ic.Close s={11} />
          </button>
        )}
      </div>

      {/* Résumé (1 ligne) */}
      {source.summary && (
        <div style={{
          fontSize: 11, color: T.sub, lineHeight: 1.45, marginTop: 3,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          paddingLeft: 19,
        }}>
          {source.summary}
        </div>
      )}

      {/* Compteur chunks */}
      <div style={{ fontSize: 10.5, color: T.muted, marginTop: 2, paddingLeft: 19 }}>
        {source.chunk_count} chunks
      </div>

      {/* Confirmation suppression inline */}
      {confirming && (
        <div
          onClick={e => e.stopPropagation()}
          style={{
            marginTop: 7, padding: '7px 10px',
            background: '#fef2f2', borderRadius: T.radiusSm,
            border: '1px solid #fecaca',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          <span style={{ flex: 1, fontSize: 11, color: '#991b1b', fontWeight: 500 }}>
            Supprimer de l'index ?
          </span>
          <button
            onClick={() => { setConfirming(false); onDelete(source); }}
            style={{
              height: 22, padding: '0 8px',
              background: '#dc2626', border: 'none', borderRadius: 5,
              color: '#fff', fontSize: 11, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Oui
          </button>
          <button
            onClick={() => setConfirming(false)}
            style={{
              height: 22, padding: '0 8px',
              background: T.white, border: `1px solid ${T.borderStrong}`,
              borderRadius: 5, color: T.sub, fontSize: 11, cursor: 'pointer',
            }}
          >
            Non
          </button>
        </div>
      )}
    </div>
  );
};


// ── Rail principal ─────────────────────────────────────────────────────
const SourcesRail = ({ sources, loadingSources, ingestJob, onUpload, onRefresh, onDismissIngest, apiFetch }) => {
  const [deletingName, setDeletingName]     = React.useState(null);
  const [preview, setPreview]               = React.useState(null);
  const [loadingPreview, setLoadingPreview] = React.useState(false);
  const [width, setWidth]                   = React.useState(240);
  const [handleHovered, setHandleHovered]   = React.useState(false);
  const fileInputRef                        = React.useRef(null);
  const isDragging                          = React.useRef(false);
  const dragStartX                          = React.useRef(0);
  const dragStartW                          = React.useRef(0);

  const onHandleMouseDown = (e) => {
    e.preventDefault();
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartW.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (ev) => {
      if (!isDragging.current) return;
      const newW = Math.max(160, Math.min(480, dragStartW.current + (ev.clientX - dragStartX.current)));
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

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) { onUpload(file); e.target.value = ''; }
  };

  const handleView = async (source) => {
    setPreview({ source, chunks: [] });
    setLoadingPreview(true);
    try {
      const r = await apiFetch(`${API_BASE}/sources/${encodeURIComponent(source.source_file)}/chunks`);
      if (r.ok) setPreview({ source, chunks: await r.json() });
    } catch { /* silently ignore */ }
    finally { setLoadingPreview(false); }
  };

  const handleDelete = async (source) => {
    setDeletingName(source.source_file);
    try {
      await apiFetch(`${API_BASE}/sources/${encodeURIComponent(source.source_file)}`, { method: 'DELETE' });
      onRefresh();
    } catch { /* silently ignore */ }
    finally { setDeletingName(null); }
  };

  const isEmpty = !loadingSources && sources.length === 0 && !ingestJob;

  return (
    <aside style={{
      width, flexShrink: 0,
      borderRight: `1px solid ${handleHovered ? T.azure : T.border}`,
      background: T.railBg,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      fontFamily: T.font,
      position: 'relative',
      transition: 'border-color .15s',
    }}>
      {/* Poignée de redimensionnement — bord droit */}
      <div
        onMouseDown={onHandleMouseDown}
        onMouseEnter={() => setHandleHovered(true)}
        onMouseLeave={() => setHandleHovered(false)}
        style={{
          position: 'absolute', top: 0, bottom: 0, right: -4,
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

      {/* En-tête */}
      <div style={{
        padding: '14px 14px 12px',
        borderBottom: `1px solid ${T.border}`,
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 1,
          color: T.muted, textTransform: 'uppercase', marginBottom: 10,
        }}>
          Sources
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.md,.docx,.pptx,.xlsx,.txt,.py,.js,.ts,.jsx,.tsx,.java,.cpp,.c,.h,.cs,.go,.rs,.rb,.php,.sh,.bash,.yaml,.yml,.json,.xml,.html,.css,.sql,.r,.scala,.kt,.swift"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          style={{
            width: '100%', height: 31,
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            border: `1px solid ${T.azureBorder}`,
            borderRadius: T.radiusPill,
            background: T.azureSoft,
            color: T.azureInk,
            fontFamily: T.font, fontSize: 12, fontWeight: 500,
            cursor: 'pointer',
            transition: 'background .12s, border-color .12s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = T.azureBorder; e.currentTarget.style.borderColor = T.azure; }}
          onMouseLeave={e => { e.currentTarget.style.background = T.azureSoft; e.currentTarget.style.borderColor = T.azureBorder; }}
          title="Ajouter un document (PDF, DOCX, PPTX, XLSX, Markdown, texte, code…)"
        >
          <Ic.Upload s={12} /> Ajouter un document
        </button>
      </div>

      {/* Corps scrollable */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: 8 }}>

        {/* Progression d'ingestion */}
        {ingestJob && (
          <IngestCard job={ingestJob} onDismiss={onDismissIngest} />
        )}

        {/* Spinner chargement initial */}
        {loadingSources && sources.length === 0 && (
          <div style={{ textAlign: 'center', padding: '28px 16px', fontSize: 12, color: T.muted }}>
            Chargement…
          </div>
        )}

        {/* Liste des sources */}
        {sources.map(s => (
          <DocCard
            key={s.source_file}
            source={s}
            onView={handleView}
            onDelete={handleDelete}
          />
        ))}

        {/* État vide */}
        {isEmpty && (
          <div style={{ padding: '28px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>📂</div>
            <div style={{ fontSize: 12, fontWeight: 600, color: T.sub, marginBottom: 5 }}>
              Aucun document indexé
            </div>
            <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.55 }}>
              PDF, Word, PowerPoint, Excel,<br />Markdown, texte, code…
            </div>
          </div>
        )}
      </div>

      {/* Modal prévisualisation */}
      <SourcePreviewModal
        preview={preview}
        loading={loadingPreview}
        onClose={() => setPreview(null)}
      />
    </aside>
  );
};
