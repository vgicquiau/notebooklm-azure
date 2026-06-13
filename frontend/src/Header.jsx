// src/Header.jsx — Barre supérieure
// Props: onClearSession(), view, onViewChange(view), apiFetch(url, options), apiBase

// ── Switch de vue (Chat ⇄ Graphe ADG-M) ────────────────────────
const VIEW_OPTIONS = [
  { key: 'chat',        label: 'Chat' },
  { key: 'graph',       label: 'Graphe ADG-M' },
  { key: 'exploration', label: 'Exploration' },
];

const ViewSwitch = ({ view, onChange }) => (
  <div style={{
    display: 'flex', gap: 2, padding: 3,
    background: T.panel, borderRadius: T.radiusPill, border: `1px solid ${T.border}`,
  }}>
    {VIEW_OPTIONS.map(({ key, label }) => {
      const active = view === key;
      return (
        <button
          key={key}
          onClick={() => onChange(key)}
          style={{
            height: 30, padding: '0 16px',
            borderRadius: T.radiusPill, border: 'none',
            background: active ? T.white : 'transparent',
            color: active ? T.ink : T.muted,
            fontFamily: T.font, fontSize: 13, fontWeight: active ? 700 : 500,
            cursor: 'pointer', transition: 'all .12s', whiteSpace: 'nowrap',
            boxShadow: active ? '0 1px 3px rgba(28,27,24,.1)' : 'none',
          }}
          onMouseEnter={e => { if (!active) e.currentTarget.style.color = T.sub; }}
          onMouseLeave={e => { if (!active) e.currentTarget.style.color = T.muted; }}
        >
          {label}
        </button>
      );
    })}
  </div>
);

// ── Modale "Configuration corpus" ──────────────────────────────
const _FIELD_LABEL = {
  nom_systeme: 'Nom du système',
  stack_primaire: 'Stack technique primaire',
  stacks_secondaires: 'Stacks secondaires',
  langue_documentation: 'Langue de la documentation',
};

const _FIELD_HINT = {
  nom_systeme: "Identifiant stable, sans espace ni accent (ex. CardDemo) — utilisé tel quel dans l'id du nœud System.",
  stack_primaire: 'Ex. COBOL_ZOS, JAVA, DOTNET…',
  stacks_secondaires: 'Liste séparée par des virgules, ex. DB2_ZOS, IMS_DLI, IBM_MQ, BMS',
  langue_documentation: 'Ex. FR, EN…',
};

const CorpusConfigModal = ({ apiFetch, apiBase, onClose }) => {
  const [config, setConfig] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [status, setStatus] = React.useState(null); // { ok: bool, message: string }

  React.useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiBase}/extract/config`)
      .then(r => r.json())
      .then(data => { if (!cancelled) { setConfig(data); setLoading(false); } })
      .catch(() => { if (!cancelled) { setLoading(false); setStatus({ ok: false, message: "Impossible de charger la configuration." }); } });
    return () => { cancelled = true; };
  }, []);

  const update = (key, value) => setConfig(c => ({ ...c, [key]: value }));

  const apply = () => {
    setSaving(true);
    setStatus(null);
    apiFetch(`${apiBase}/extract/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => {
        setConfig(data);
        setStatus({ ok: true, message: "Configuration appliquée — utilisée dès la prochaine extraction (\"Mise à jour\")." });
      })
      .catch(() => setStatus({ ok: false, message: "Échec de l'enregistrement de la configuration." }))
      .finally(() => setSaving(false));
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(28,27,24,.45)', backdropFilter: 'blur(2px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 520, maxWidth: 'calc(100vw - 48px)', maxHeight: 'calc(100vh - 48px)',
          overflowY: 'auto',
          background: T.white, border: `1px solid ${T.border}`, borderRadius: T.radiusLg,
          boxShadow: '0 12px 48px rgba(28,27,24,.22)',
          padding: 24,
          fontFamily: T.font,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: T.ink }}>Configuration corpus</h2>
          <button
            onClick={onClose}
            style={{ display: 'flex', border: 'none', background: 'transparent', color: T.muted, cursor: 'pointer', padding: 6, borderRadius: T.radiusSm }}
            title="Fermer"
          >
            <Ic.Close s={16} />
          </button>
        </div>
        <p style={{ margin: '4px 0 18px', fontSize: 13, color: T.sub, lineHeight: 1.5 }}>
          Ces informations contextualisent l'extraction du graphe ADG-M (bouton "Mise à jour") pour
          le système legacy actuellement étudié, afin d'améliorer la qualité et la pertinence des
          entités extraites du corpus documentaire indexé.
        </p>

        {loading ? (
          <div style={{ fontSize: 13, color: T.sub, padding: '12px 0' }}>Chargement…</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {['nom_systeme', 'stack_primaire', 'stacks_secondaires', 'langue_documentation'].map(key => (
              <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.ink }}>{_FIELD_LABEL[key]}</span>
                <input
                  type="text"
                  value={config[key] || ''}
                  onChange={e => update(key, e.target.value)}
                  style={{
                    height: 36, padding: '0 12px',
                    borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
                    fontFamily: T.font, fontSize: 13.5, color: T.ink, background: T.panel,
                  }}
                />
                <span style={{ fontSize: 11.5, color: T.muted, lineHeight: 1.4 }}>{_FIELD_HINT[key]}</span>
              </label>
            ))}

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: T.ink }}>Contexte métier additionnel</span>
              <textarea
                value={config.contexte_libre || ''}
                onChange={e => update('contexte_libre', e.target.value)}
                rows={6}
                placeholder="Décrivez le système, son périmètre fonctionnel, son vocabulaire métier, des points d'attention pour l'extraction…"
                style={{
                  padding: 12, resize: 'vertical',
                  borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
                  fontFamily: T.font, fontSize: 13.5, color: T.ink, background: T.panel,
                  lineHeight: 1.5,
                }}
              />
              <span style={{ fontSize: 11.5, color: T.muted, lineHeight: 1.4 }}>
                Injecté tel quel dans le prompt d'extraction, en complément du schéma ADG-M.
              </span>
            </label>
          </div>
        )}

        {status && (
          <div style={{
            marginTop: 14, padding: '8px 12px', borderRadius: T.radiusSm,
            fontSize: 12.5, lineHeight: 1.4,
            background: status.ok ? '#eafaf0' : '#fdecec',
            color: status.ok ? T.success : T.danger,
            border: `1px solid ${status.ok ? '#bfead0' : '#f6c9c9'}`,
          }}>
            {status.message}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
          <button
            onClick={onClose}
            style={{
              height: 34, padding: '0 16px', borderRadius: T.radiusPill,
              border: `1px solid ${T.border}`, background: T.white, color: T.sub,
              fontFamily: T.font, fontSize: 13.5, fontWeight: 500, cursor: 'pointer',
            }}
          >
            Fermer
          </button>
          <button
            onClick={apply}
            disabled={loading || saving}
            style={{
              height: 34, padding: '0 18px', borderRadius: T.radiusPill,
              border: 'none', background: T.azure, color: T.white,
              fontFamily: T.font, fontSize: 13.5, fontWeight: 600,
              cursor: (loading || saving) ? 'default' : 'pointer',
              opacity: (loading || saving) ? 0.6 : 1,
              display: 'flex', alignItems: 'center', gap: 7,
            }}
          >
            <Ic.Check s={14} /> {saving ? 'Application…' : 'Appliquer'}
          </button>
        </div>
      </div>
    </div>
  );
};

const Header = ({ onClearSession, view, onViewChange, apiFetch, apiBase }) => {
  const [configOpen, setConfigOpen] = React.useState(false);
  const btnBase = {
    display: 'flex', alignItems: 'center', gap: 7,
    height: 34, padding: '0 14px',
    borderRadius: T.radiusPill,
    border: `1px solid ${T.border}`,
    background: T.white,
    color: T.ink,
    fontFamily: T.font, fontSize: 13.5, fontWeight: 500,
    cursor: 'pointer', whiteSpace: 'nowrap',
    transition: 'background .12s, border-color .12s',
  };

  return (
    <header style={{
      height: 56, flexShrink: 0,
      display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center',
      padding: '0 22px',
      borderBottom: `1px solid ${T.border}`,
      background: T.white,
      fontFamily: T.font,
      zIndex: 10,
    }}>
      {/* Marque */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Logo s={26} r={8} />
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: -0.2, color: T.ink }}>
          NotebookLM{' '}
          <span style={{
            background: 'linear-gradient(135deg, #f97316 0%, #ec4899 22%, #a855f7 42%, #6366f1 62%, #4338ca 80%, #3730a3 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}>Azure</span>
        </span>
      </div>

      {/* Switch de vue */}
      <ViewSwitch view={view} onChange={onViewChange} />

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
        <button
          onClick={() => setConfigOpen(true)}
          style={{ ...btnBase, color: T.sub }}
          onMouseEnter={e => { e.currentTarget.style.background = T.panel; e.currentTarget.style.borderColor = T.borderStrong; }}
          onMouseLeave={e => { e.currentTarget.style.background = T.white; e.currentTarget.style.borderColor = T.border; }}
          title="Configurer le contexte du corpus documentaire pour l'extraction du graphe ADG-M"
        >
          <Ic.Settings s={15} /> Configuration corpus
        </button>
        <button
          onClick={onClearSession}
          style={{ ...btnBase, color: T.sub }}
          onMouseEnter={e => { e.currentTarget.style.background = T.panel; e.currentTarget.style.borderColor = T.borderStrong; }}
          onMouseLeave={e => { e.currentTarget.style.background = T.white; e.currentTarget.style.borderColor = T.border; }}
          title="Effacer la conversation et démarrer une nouvelle session"
        >
          <Ic.Refresh s={15} /> Nouvelle conversation
        </button>
      </div>

      {configOpen && (
        <CorpusConfigModal apiFetch={apiFetch} apiBase={apiBase} onClose={() => setConfigOpen(false)} />
      )}
    </header>
  );
};

Object.assign(window, { Header });
