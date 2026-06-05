// src/Header.jsx — Barre supérieure
// Props: onClearSession()

const Header = ({ onClearSession }) => {
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
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
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
          NotebookLM <span style={{ color: T.azure }}>Azure</span>
        </span>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
