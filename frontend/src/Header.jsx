// src/Header.jsx — Barre supérieure
// Props: onClearSession(), view, onViewChange(view), apiFetch(url, options)

// AUDIT-2026-06 : neo4j-legacykb n'a plus d'IP publique -- en local, ce backend ne peut
// plus l'atteindre. <meta name="nlaz-legacykb-api-url"> (injecté par api/main.py depuis
// NOTEBOOKLM_API_URL) pointe vers ca-api, intégré au VNet, pour les routes /api/legacykb/*
// uniquement. Absent en production (pas de frontend déployé) -- fallback same-origin.
const LEGACYKB_API_BASE =
  (document.querySelector('meta[name="nlaz-legacykb-api-url"]')?.content || window.location.origin) + '/api';

// ── Switch de vue (Chat ⇄ Legacy KB) ────────────────────────────
const VIEW_OPTIONS = [
  { key: 'chat',     label: 'Chat' },
  { key: 'legacykb', label: 'Legacy KB' },
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

// ── Voyant de connexion à neo4j-legacykb ────────────────────────
const LegacyKbStatus = ({ apiFetch }) => {
  const [status, setStatus] = React.useState('loading'); // 'loading' | 'ok' | 'error'

  React.useEffect(() => {
    let cancelled = false;
    const check = () => {
      apiFetch(`${LEGACYKB_API_BASE}/legacykb/health`)
        .then(r => { if (!cancelled) setStatus(r.ok ? 'ok' : 'error'); })
        .catch(() => { if (!cancelled) setStatus('error'); });
    };
    check();
    const id = setInterval(check, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, [apiFetch]);

  const color = status === 'ok' ? T.success : status === 'error' ? T.danger : T.muted;
  const label = status === 'ok'
    ? 'Legacy KB (neo4j) — connectée'
    : status === 'error'
      ? 'Legacy KB (neo4j) — injoignable'
      : 'Legacy KB (neo4j) — vérification…';

  return (
    <span title={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.muted, whiteSpace: 'nowrap' }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
      Legacy KB
    </span>
  );
};

const Header = ({ onClearSession, view, onViewChange, apiFetch }) => {
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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 14 }}>
        <LegacyKbStatus apiFetch={apiFetch} />
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
    </header>
  );
};

Object.assign(window, { Header });
