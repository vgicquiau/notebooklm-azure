// src/LegacyKbPage.jsx — Vue "Legacy KB" : exploration du graphe GraphRAG brut (neo4j-legacykb)
// Props: apiFetch(url, options) — wrapper _apiFetch (injecte X-API-Key), fourni par App
//
// Lecture seule, via api/routers/legacykb.py (connexion directe à l'instance Neo4j
// neo4j-legacykb, distincte du graphe ADG-M, retiré). Recherche par nom/titre, puis
// exploration progressive du voisinage par double-clic. Rendu avec React Flow (xyflow,
// window.ReactFlow) + dagre (window.dagre) pour le layout.

const API_BASE = window.location.origin + '/api';
const _uid = () => Math.random().toString(36).slice(2, 10);

const {
  ReactFlow: ReactFlowCanvas,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  applyNodeChanges,
  useReactFlow,
} = window.ReactFlow;

// ── Couleurs/formes par type d'entité et niveau de communauté ─────────────────
const ENTITY_COLORS = {
  Program:        '#1565c0',
  BatchJob:       '#8d6e63',
  Copybook:       '#7b1fa2',
  GenericFile:    '#26a69a',
  'External/Doc': '#9e9e9e',
};
const COMMUNITY_COLORS = { 1: '#ffb74d', 2: '#fb8c00' };

const ENTITY_TYPE_LABELS = {
  Program:        'Programme',
  BatchJob:       'Job batch',
  Copybook:       'Copybook',
  GenericFile:    'Fichier',
  'External/Doc': 'Référence externe',
};

const COMMUNITY_LEVEL_LABELS = { 2: 'Domaine fonctionnel', 1: 'Sous-domaine' };

// ── Menu "Affichage" — types/niveaux de nœuds proposés au filtrage ────────────
// Clé de visibilité d'un nœud : `community:<level>` ou `entity:<type>`.
const _nodeKindKey = (n) => (n.kind === 'entity' ? `entity:${n.type}` : `community:${n.level}`);

const VISIBILITY_OPTIONS = [
  { key: 'community:2', label: COMMUNITY_LEVEL_LABELS[2], color: COMMUNITY_COLORS[2] },
  { key: 'community:1', label: COMMUNITY_LEVEL_LABELS[1], color: COMMUNITY_COLORS[1] },
  ...Object.keys(ENTITY_COLORS).map(type => ({
    key: `entity:${type}`, label: ENTITY_TYPE_LABELS[type] ?? type, color: ENTITY_COLORS[type],
  })),
];

const RELATION_LABELS = {
  CALLS: 'Appelle', INCLUDES: 'Inclut', READS: 'Lit', INSERTS: 'Insère',
  UPDATES: 'Met à jour', DELETES: 'Supprime', CREATES: 'Crée',
  REFERENCES: 'Référence', EXECUTES: 'Exécute', INTERACTS_WITH: 'Interagit avec',
  SENDS: 'Envoie', RECEIVES: 'Reçoit', TRIGGERS: 'Déclenche', DEPENDS_ON: 'Dépend de',
  IN_COMMUNITY: 'Domaine', SUBCOMMUNITY_OF: 'Sous-domaine de',
};

// Sémantique couleur par type de relation (flux bleu, lecture vert, écriture orange,
// structure violet, événement rouge, message sarcelle)
const RELATION_COLORS = {
  CALLS: '#1565c0', EXECUTES: '#1976d2',
  READS: '#2e7d32', REFERENCES: '#388e3c', DEPENDS_ON: '#43a047',
  INSERTS: '#e65100', UPDATES: '#ef6c00', DELETES: '#bf360c', CREATES: '#f57c00',
  INCLUDES: '#7b1fa2',
  TRIGGERS: '#c62828',
  SENDS: '#00695c', RECEIVES: '#00796b',
  INTERACTS_WITH: '#546e7a',
};

// Mots-clés techniques mainframe détectés dans `technical_description` (tags)
const TECH_TAGS = ['VSAM', 'CICS', 'DB2', 'SQL', 'MQ', 'IMS', 'KSDS', 'JCL', 'COPY', 'PACBASE', 'GOBACK'];

const NODE_W = 220;
const NODE_H = 56;

// Marge des zones de regroupement par communauté (le haut inclut l'espace
// pour l'étiquette de titre de la zone).
const ZONE_PADDING_X = 24;
const ZONE_PADDING_TOP = 34;
const ZONE_PADDING_BOTTOM = 16;

// Disposition en grille des membres d'une zone (carré/rectangle plutôt que
// colonne) — pas horizontal/vertical entre deux membres adjacents.
const ZONE_GRID_GAP_X = NODE_W + 24;
const ZONE_GRID_GAP_Y = NODE_H + 14;

// ── Couleur → rgba (teinte/bordure des zones de regroupement) ────────────────
const _hexToRgba = (hex, alpha) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

// ── Couleur → teinte opaque (mélange avec le blanc) — fond des nœuds, qui ne
// doivent pas être transparents (contrairement aux zones de regroupement).
const _hexToTint = (hex, alpha) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  const mix = (c) => Math.round(c * alpha + 255 * (1 - alpha));
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
};

// ── Couleur → ton foncé (mélange avec le noir) — extrémité sombre du dégradé
// des pills de type.
const _hexToShade = (hex, alpha) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  const mix = (c) => Math.round(c * (1 - alpha));
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
};

// Points d'ancrage multiples — un par côté, chacun cumulant source + target
// pour permettre à dagre/_pickHandles de router les arêtes au plus court.
const HANDLE_SIDES = [
  { id: 'top',    position: Position.Top },
  { id: 'right',  position: Position.Right },
  { id: 'bottom', position: Position.Bottom },
  { id: 'left',   position: Position.Left },
];

// ── Nœud custom — entité (pastille ronde) ou communauté (pastille carrée) ─────
const LegacyNode = ({ data }) => {
  const isEntity = data.kind === 'entity';
  const color = isEntity
    ? (ENTITY_COLORS[data.type] ?? '#9e9e9e')
    : (COMMUNITY_COLORS[data.level] ?? '#bdbdbd');

  // Points d'ancrage invisibles — toujours présents pour l'accroche des arêtes,
  // mais masqués visuellement (cf. demande : pas de poignées de connexion affichées).
  const handleStyle = { background: 'transparent', border: 'none', width: 1, height: 1, opacity: 0 };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 5,
      width: NODE_W, height: NODE_H, boxSizing: 'border-box', padding: '7px 12px',
      borderRadius: T.radiusSm,
      border: data.isCenter ? `2px solid ${T.azure}` : 'none',
      background: T.white,
      fontFamily: T.font, color: T.ink,
      boxShadow: data.highlighted
        ? '0 2px 6px rgba(28,27,24,0.12), 0 0 0 3px rgba(251,140,0,0.45)'
        : '0 2px 6px rgba(28,27,24,0.12)',
    }}>
      {HANDLE_SIDES.map(({ id, position }) => (
        <React.Fragment key={id}>
          <Handle type="target" position={position} id={`${id}-target`} style={handleStyle} />
          <Handle type="source" position={position} id={`${id}-source`} style={handleStyle} />
        </React.Fragment>
      ))}
      <span style={{
        alignSelf: 'flex-start', flexShrink: 0,
        padding: '2px 8px', borderRadius: 999,
        background: `linear-gradient(135deg, ${_hexToShade(color, 0.5)}, ${color})`,
        fontSize: 10, fontWeight: 700, color: T.white, whiteSpace: 'nowrap',
      }}>
        {isEntity ? (ENTITY_TYPE_LABELS[data.type] ?? data.type) : (COMMUNITY_LEVEL_LABELS[data.level] ?? `Niveau ${data.level}`)}
      </span>
      <span style={{
        fontSize: 12, fontWeight: 600,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {data.nom}
      </span>
    </div>
  );
};

// ── Nœud zone — englobe les entités d'une même communauté (regroupement) ─────
// Porte les mêmes ancrages que LegacyNode (HANDLE_SIDES) pour pouvoir recevoir
// des arêtes vers/depuis d'autres zones ou communautés (relations SUBCOMMUNITY_OF
// redirigées depuis le nœud :Community masqué que cette zone représente).
const ZoneNode = ({ data }) => {
  const color = COMMUNITY_COLORS[data.level] ?? '#bdbdbd';
  const handleStyle = { background: 'transparent', border: 'none', width: 1, height: 1, opacity: 0 };
  return (
    <div style={{
      position: 'relative',
      width: data.width, height: data.height,
      borderRadius: T.radiusLg,
      background: _hexToRgba(color, 0.06),
      border: `1.5px dashed ${_hexToRgba(color, 0.35)}`,
      boxSizing: 'border-box',
      cursor: 'grab',
    }}>
      {HANDLE_SIDES.map(({ id, position }) => (
        <React.Fragment key={id}>
          <Handle type="target" position={position} id={`${id}-target`} style={handleStyle} />
          <Handle type="source" position={position} id={`${id}-source`} style={handleStyle} />
        </React.Fragment>
      ))}
      <div style={{
        position: 'absolute', top: -11, left: 14,
        display: 'flex', alignItems: 'center',
        fontFamily: T.font, fontSize: 11, fontWeight: 700, color: T.white,
        background: `linear-gradient(135deg, ${_hexToShade(color, 0.5)}, ${color})`,
        padding: '2px 9px', borderRadius: 999, whiteSpace: 'nowrap',
        pointerEvents: 'none',
      }}>
        {data.nom}
      </div>
    </div>
  );
};

const NODE_TYPES = { legacyNode: LegacyNode, zoneNode: ZoneNode };

// ── Menu contextuel nœud (style Neo4j) — affiché au clic, ancré au curseur ────
const NodeContextMenu = ({ x, y, onRecenter, onRecenterLayout, onRemove, onClose }) => {
  const itemStyle = {
    display: 'flex', alignItems: 'center', gap: 8,
    width: '100%', padding: '8px 12px', border: 'none', background: 'transparent',
    fontFamily: T.font, fontSize: 12.5, fontWeight: 500, color: T.ink,
    textAlign: 'left', cursor: 'pointer', borderRadius: T.radiusSm, whiteSpace: 'nowrap',
  };
  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
      <div style={{
        position: 'fixed', left: x + 6, top: y + 6, zIndex: 41,
        display: 'flex', flexDirection: 'column', gap: 1, padding: 4, minWidth: 240,
        background: T.white, border: `1px solid ${T.border}`, borderRadius: T.radiusMd,
        boxShadow: '0 4px 18px rgba(28,27,24,.14)',
      }}>
        <button
          style={itemStyle} onClick={onRecenter}
          onMouseEnter={e => e.currentTarget.style.background = T.panel}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <Ic.Refresh s={14} /> Réinitialiser la vue et la recentrer sur ce nœud
        </button>
        <button
          style={itemStyle} onClick={onRecenterLayout}
          onMouseEnter={e => e.currentTarget.style.background = T.panel}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <Ic.Microscope s={14} /> Recentrer la disposition sur ce nœud
        </button>
        <button
          style={{ ...itemStyle, color: T.danger }} onClick={onRemove}
          onMouseEnter={e => e.currentTarget.style.background = T.panel}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <Ic.Close s={14} /> Effacer de la vue
        </button>
      </div>
    </>
  );
};

// ── Fil d'Ariane domaine/sous-domaine — navigue vers la communauté au clic ────
const DomainBreadcrumb = ({ items, onNavigate }) => {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
      {items.map((d, i) => (
        <React.Fragment key={d.id}>
          {i > 0 && <span style={{ fontSize: 11, color: T.muted }}>›</span>}
          <button
            onClick={() => onNavigate(d.id)}
            title={COMMUNITY_LEVEL_LABELS[d.level] ?? 'Domaine'}
            style={{
              fontSize: 11.5, fontWeight: 600, color: T.azureInk, background: T.azureSoft,
              border: `1px solid ${T.azureBorder}`, borderRadius: 999, padding: '2px 9px',
              cursor: 'pointer', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            {d.nom}
          </button>
        </React.Fragment>
      ))}
    </div>
  );
};

// ── Carte de connectivité — compteurs de relations par type, triés ───────────
const RelationBars = ({ relations }) => {
  if (!relations || relations.length === 0) return null;
  const totals = new Map();
  relations.forEach(r => totals.set(r.type, (totals.get(r.type) ?? 0) + r.count));
  const sorted = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = sorted[0]?.[1] ?? 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {sorted.map(([type, count]) => (
        <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11.5, color: T.sub, width: 100, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {RELATION_LABELS[type] ?? type}
          </span>
          <div style={{ flex: 1, height: 6, borderRadius: 3, background: T.panel, overflow: 'hidden' }}>
            <div style={{ height: '100%', borderRadius: 3, background: T.azure, width: `${Math.max(6, (count / max) * 100)}%` }} />
          </div>
          <span style={{ fontSize: 11.5, color: T.muted, width: 24, textAlign: 'right', flexShrink: 0 }}>{count}</span>
        </div>
      ))}
    </div>
  );
};

// ── Résumé exécutif — première phrase en avant, reste dépliable ──────────────
const ExpandableText = ({ text }) => {
  const [expanded, setExpanded] = React.useState(false);
  if (!text) return null;
  const match = text.match(/^.*?[.!?](?=\s|$)/);
  const firstSentence = match ? match[0] : text;
  const rest = text.slice(firstSentence.length).trim();
  if (!rest) return <div style={{ fontSize: 12.5, color: T.ink, lineHeight: 1.6 }}>{firstSentence}</div>;
  return (
    <div>
      <div style={{ fontSize: 12.5, color: T.ink, lineHeight: 1.6, fontWeight: 600 }}>{firstSentence}</div>
      {expanded && (
        <div style={{ fontSize: 12.5, color: T.sub, lineHeight: 1.6, marginTop: 6, whiteSpace: 'pre-wrap' }}>{rest}</div>
      )}
      <button
        onClick={() => setExpanded(v => !v)}
        style={{ marginTop: 6, border: 'none', background: 'transparent', color: T.azure, fontFamily: T.font, fontSize: 12, fontWeight: 600, cursor: 'pointer', padding: 0 }}
      >
        {expanded ? 'Réduire' : 'Lire la suite'}
      </button>
    </div>
  );
};

// ── Tags techniques détectés par mots-clés dans la description technique ─────
const TechTagList = ({ text }) => {
  if (!text) return null;
  const found = TECH_TAGS.filter(tag => new RegExp(`\\b${tag}\\b`, 'i').test(text));
  if (found.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
      {found.map(tag => (
        <span key={tag} style={{
          fontSize: 11, fontWeight: 600, color: T.azureInk, background: T.azureSoft,
          border: `1px solid ${T.azureBorder}`, borderRadius: 999, padding: '2px 8px',
        }}>{tag}</span>
      ))}
    </div>
  );
};

// ── Panneau de détail ───────────────────────────────────────────────────────
const NodeDetailPanel = ({ nodeId, apiFetch, onNavigate, onClose }) => {
  const [detail, setDetail] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiFetch(`${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => { if (!cancelled) { setDetail(data); setLoading(false); } })
      .catch(err => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [nodeId, apiFetch]);

  const Section = ({ title, children }) => (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11.5, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ fontSize: 12.5, color: T.sub, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
        {children}
      </div>
    </div>
  );

  return (
    <div style={{
      width: 360, flexShrink: 0, borderLeft: `1px solid ${T.border}`,
      background: T.white, overflowY: 'auto', padding: 18, fontFamily: T.font,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: T.ink, wordBreak: 'break-word' }}>
          {detail?.nom ?? '…'}
        </div>
        <button
          onClick={onClose}
          style={{ display: 'flex', border: 'none', background: 'transparent', color: T.muted, cursor: 'pointer', padding: 4, borderRadius: T.radiusSm, flexShrink: 0 }}
          title="Fermer"
        >
          <Ic.Close s={14} />
        </button>
      </div>

      {loading && <div style={{ fontSize: 12.5, color: T.muted, marginTop: 10 }}>Chargement…</div>}
      {error && <div style={{ fontSize: 12.5, color: T.danger, marginTop: 10 }}>Erreur : {error}</div>}

      {detail && !loading && (
        <>
          {detail.kind === 'entity' ? (
            <>
              <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: ENTITY_COLORS[detail.type] ?? '#9e9e9e', flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: T.sub }}>{ENTITY_TYPE_LABELS[detail.type] ?? detail.type}</span>
                {detail.is_missing && (
                  <span style={{ fontSize: 11, fontWeight: 600, color: T.muted, background: T.panel, border: `1px solid ${T.border}`, borderRadius: 999, padding: '2px 8px' }}>
                    Référence externe
                  </span>
                )}
              </div>

              <DomainBreadcrumb items={detail.domain} onNavigate={onNavigate} />

              {detail.functional_description && (
                <Section title="Résumé"><ExpandableText text={detail.functional_description} /></Section>
              )}

              {detail.relations?.length > 0 && (
                <Section title="Connectivité"><RelationBars relations={detail.relations} /></Section>
              )}

              <Section title="Métadonnées techniques">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {detail.source && <div><strong style={{ color: T.ink }}>Fichier :</strong> {detail.source}</div>}
                  {detail.repo_name && <div><strong style={{ color: T.ink }}>Dépôt :</strong> {detail.repo_name}</div>}
                  {detail.updated_at && <div><strong style={{ color: T.ink }}>Mise à jour :</strong> {detail.updated_at}</div>}
                </div>
                <TechTagList text={detail.technical_description} />
              </Section>

              {detail.technical_description && (
                <Section title="Description technique">{detail.technical_description}</Section>
              )}
            </>
          ) : (
            <>
              <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: COMMUNITY_COLORS[detail.level] ?? '#bdbdbd', flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: T.sub }}>{COMMUNITY_LEVEL_LABELS[detail.level] ?? `Communauté niveau ${detail.level}`}</span>
              </div>

              {detail.parent_domain && (
                <DomainBreadcrumb items={[{ ...detail.parent_domain, level: 2 }]} onNavigate={onNavigate} />
              )}

              <Section title="Composition">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {detail.level === 2 && (
                    <div>{detail.subdomain_count ?? 0} sous-domaine{detail.subdomain_count === 1 ? '' : 's'}</div>
                  )}
                  <div>{detail.member_count ?? 0} membre{detail.member_count === 1 ? '' : 's'}</div>
                </div>
              </Section>

              {detail.functional_summary && (
                <Section title="Résumé fonctionnel"><ExpandableText text={detail.functional_summary} /></Section>
              )}

              {detail.relations?.length > 0 && (
                <Section title="Connectivité"><RelationBars relations={detail.relations} /></Section>
              )}

              {detail.technical_summary && (
                <Section title="Résumé technique"><ExpandableText text={detail.technical_summary} /></Section>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
};

// Choisit les ancrages source/target d'une arête selon les boîtes (position +
// dimensions) des deux nœuds. Privilégie une liaison en ligne droite (sans
// coude) quand les plages se recouvrent sur un axe — sinon retombe sur l'axe
// dominant entre les centres. Réduit le nombre de courbures des smoothstep et
// facilite la lecture du schéma.
const _pickHandles = (a, b) => {
  const centerA = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
  const centerB = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  const dx = centerB.x - centerA.x;
  const dy = centerB.y - centerA.y;

  const yOverlap = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  const xOverlap = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const xSeparated = a.x + a.w <= b.x || b.x + b.w <= a.x;
  const ySeparated = a.y + a.h <= b.y || b.y + b.h <= a.y;

  // Plages verticales superposées et boîtes séparées horizontalement →
  // liaison droite gauche/droite.
  if (yOverlap > 0 && xSeparated) {
    return dx >= 0
      ? { sourceHandle: 'right-source', targetHandle: 'left-target' }
      : { sourceHandle: 'left-source', targetHandle: 'right-target' };
  }
  // Plages horizontales superposées et boîtes séparées verticalement →
  // liaison droite haut/bas.
  if (xOverlap > 0 && ySeparated) {
    return dy >= 0
      ? { sourceHandle: 'bottom-source', targetHandle: 'top-target' }
      : { sourceHandle: 'top-source', targetHandle: 'bottom-target' };
  }

  // Sinon, axe dominant entre les centres (cas diagonal).
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { sourceHandle: 'right-source', targetHandle: 'left-target' }
      : { sourceHandle: 'left-source', targetHandle: 'right-target' };
  }
  return dy >= 0
    ? { sourceHandle: 'bottom-source', targetHandle: 'top-target' }
    : { sourceHandle: 'top-source', targetHandle: 'bottom-target' };
};

// Boîte (position + dimensions) d'un nœud React Flow courant — utilisée pour
// recalculer dynamiquement les ancrages des arêtes qui s'y connectent.
const _nodeBox = (node) => ({
  x: node.position.x,
  y: node.position.y,
  w: node.type === 'zoneNode' ? node.data.width : NODE_W,
  h: node.type === 'zoneNode' ? node.data.height : NODE_H,
});

// Recalcule les ancrages (sourceHandle/targetHandle) de chaque arête à partir
// des positions courantes des nœuds — appelé à chaque rendu (y compris pendant
// un drag), pour que l'arête se réancre toujours sur le côté le plus adapté,
// même si un nœud a été déplacé manuellement après le layout initial.
const _withHandles = (edges, nodes) => {
  const boxes = new Map();
  nodes.forEach(n => boxes.set(n.id, _nodeBox(n)));
  return edges.map(e => {
    const a = boxes.get(e.source);
    const b = boxes.get(e.target);
    if (!a || !b) return e;
    return { ...e, ..._pickHandles(a, b) };
  });
};

// ── Calcule un layout dagre (gauche → droite) pour le bundle courant ──────────
// `positions` (Map id → {x,y} coin haut-gauche) permet de conserver les positions
// déplacées manuellement par l'utilisateur lors d'un re-layout (nouveaux voisins).
// `visibleKinds` (Set de clés `_nodeKindKey`) filtre les types/niveaux affichés
// (menu "Affichage") — un nœud absent de cet ensemble est entièrement exclu du
// schéma (lui et ses arêtes), et n'est pas compté comme membre de zone.
const _layout = (bundle, centerId, positions, visibleKinds, highlightedIds) => {
  if (!bundle) return { nodes: [], edges: [], clusters: new Map() };

  const filteredNodeMap = new Map(
    [...bundle.nodeMap].filter(([, n]) => !visibleKinds || visibleKinds.has(_nodeKindKey(n)))
  );

  const allEdges = bundle.edgeList.filter(e => filteredNodeMap.has(e.from) && filteredNodeMap.has(e.to));

  // ── Regroupement par communauté (zones) ───────────────────────────────────
  // Chaque entité est rattachée à au plus une communauté (`n.community`) et
  // reste dans sa zone même si une relation structurelle la relie à une
  // entité d'une AUTRE communauté — ces arêtes traversent alors simplement
  // les rectangles de zone (dessinés en arrière-plan, zIndex -1).
  const clusters = new Map(); // zoneId -> { nom, level, members: [] }
  filteredNodeMap.forEach(n => {
    if (n.kind !== 'entity' || !n.community) return;
    if (visibleKinds && !visibleKinds.has(`community:${n.community.level}`)) return;
    const zoneId = `zone:${n.community.id}`;
    if (!clusters.has(zoneId)) {
      clusters.set(zoneId, { nom: n.community.nom, level: n.community.level, members: [] });
    }
    clusters.get(zoneId).members.push(n.id);
  });

  // ── Simplification du schéma ──────────────────────────────────────────────
  // 1. Un nœud :Community déjà représenté par une zone (≥2 membres) est masqué
  //    — ainsi que ses arêtes IN_COMMUNITY/SUBCOMMUNITY_OF, qui deviennent
  //    redondantes avec le regroupement visuel.
  const zoneCommunityIds = new Set(
    [...clusters.entries()]
      .filter(([, c]) => c.members.length >= 2)
      .map(([zoneId]) => zoneId.slice('zone:'.length))
  );
  const visibleIds = new Set(
    [...filteredNodeMap.values()]
      .filter(n => !(n.kind === 'community' && zoneCommunityIds.has(n.id)))
      .map(n => n.id)
  );

  // Une arête dont une extrémité est un nœud :Community masqué est redirigée
  // vers la zone qui le représente (`zone:<id>`) plutôt que supprimée — ainsi
  // une relation SUBCOMMUNITY_OF entre un sous-domaine (masqué, devenu zone) et
  // son domaine parent reste visible comme un lien zone -> nœud. Les arêtes
  // qui deviendraient des boucles (ex. IN_COMMUNITY d'une entité vers sa propre
  // zone) sont supprimées.
  const remapEndpoint = (id) => zoneCommunityIds.has(id) ? `zone:${id}` : id;
  const drawableIds = new Set([
    ...visibleIds,
    ...[...zoneCommunityIds].map(cid => `zone:${cid}`),
  ]);

  // Zone parente (≥2 membres) de chaque entité — une arête entre une entité et
  // sa propre zone (ex. IN_COMMUNITY redirigée vers `zone:<sa communauté>`)
  // formerait un cycle parent/enfant dans le graphe compound de dagre
  // (`Cannot set properties of undefined (setting 'rank')`) : à exclure.
  const entityZone = new Map(); // entity id -> zoneId
  clusters.forEach((cluster, zoneId) => {
    if (cluster.members.length < 2) return;
    cluster.members.forEach(id => entityZone.set(id, zoneId));
  });

  // 2. Les arêtes parallèles entre une même paire de nœuds (plusieurs types de
  //    relation) sont fusionnées en une seule, pour réduire le nombre de flux
  //    affichés à l'écran. Map imbriquée (from -> to -> types) pour éviter de
  //    construire une clé composite à partir d'identifiants contenant `|`.
  const edgeGroups = new Map(); // from -> Map(to -> Set<type>)
  allEdges.forEach(e => {
    const from = remapEndpoint(e.from);
    const to = remapEndpoint(e.to);
    if (from === to) return;
    if (entityZone.get(e.from) === to || entityZone.get(e.to) === from) return;
    if (!drawableIds.has(from) || !drawableIds.has(to)) return;
    if (!edgeGroups.has(from)) edgeGroups.set(from, new Map());
    const byTarget = edgeGroups.get(from);
    if (!byTarget.has(to)) byTarget.set(to, new Set());
    byTarget.get(to).add(e.type);
  });

  // Dimensions estimées de chaque zone (grille carrée/rectangle de ses membres,
  // cf. étape 3) — communiquées à dagre via `g.setNode` pour qu'il réserve
  // l'espace réellement occupé par la zone et évite les chevauchements avec les
  // autres nœuds/zones lors du calcul des rangs.
  const clusterGrid = new Map(); // zoneId -> { cols, rows, width, height }
  clusters.forEach((cluster, zoneId) => {
    if (cluster.members.length < 2) return;
    const cols = Math.ceil(Math.sqrt(cluster.members.length));
    const rows = Math.ceil(cluster.members.length / cols);
    clusterGrid.set(zoneId, {
      cols, rows,
      width: cols * ZONE_GRID_GAP_X + ZONE_PADDING_X * 2,
      height: rows * ZONE_GRID_GAP_Y + ZONE_PADDING_TOP + ZONE_PADDING_BOTTOM,
    });
  });

  const g = new dagre.graphlib.Graph({ compound: true });
  // `nodesep`/`ranksep` généreux — avec des zones désormais dimensionnées
  // (cf. `clusterGrid`), un espacement trop faible laissait les rectangles de
  // zone chevaucher leurs voisins.
  g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 110 });
  g.setDefaultEdgeLabel(() => ({}));
  // Filet de sécurité : un nœud créé implicitement par setEdge/setParent (id
  // référencé par une arête ou un parent mais jamais explicitement ajouté via
  // setNode) reçoit un label `undefined` par défaut côté graphlib — dagre plante
  // alors avec « Cannot set properties of undefined (setting 'rank') » lors du
  // ranking. `{}` évite le crash quel que soit l'id concerné.
  g.setDefaultNodeLabel(() => ({}));

  clusters.forEach((cluster, zoneId) => {
    const dims = clusterGrid.get(zoneId);
    if (dims) g.setNode(zoneId, { width: dims.width, height: dims.height });
  });
  bundle.nodeMap.forEach(n => {
    if (!visibleIds.has(n.id)) return;
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
    if (n.kind === 'entity' && n.community) {
      const zoneId = `zone:${n.community.id}`;
      if ((clusters.get(zoneId)?.members.length ?? 0) >= 2) g.setParent(n.id, zoneId);
    }
  });
  // Pour le ranking dagre, une arête ne doit jamais toucher directement un nœud
  // de cluster (`zone:...`) — dagre ne gère pas ce cas en mode compound et plante
  // (`Cannot set properties of undefined (setting 'rank')`). On substitue donc
  // l'extrémité "zone" par un de ses membres (même rang visé) pour le calcul des
  // rangs ; le rendu (edgeGroups) continue lui de pointer vers la zone.
  const rankProxy = (id) => {
    if (!id.startsWith('zone:')) return id;
    const members = clusters.get(id)?.members;
    return members?.length ? members[0] : id;
  };

  // ── Hiérarchie centrée sur `centerId` (option "recentrer la disposition") ──
  // Si un centre est défini, les rangs dagre (position sur l'axe LR) suivent
  // la distance (BFS, arêtes non dirigées) depuis ce nœud le long d'un arbre
  // couvrant du graphe affiché — le nœud sélectionné se retrouve à l'extrémité
  // gauche, ses voisins juste après, etc. Les composantes non atteintes depuis
  // le centre (ou en l'absence de centre) retombent sur le ranking par
  // direction d'arête d'origine.
  const adjacency = new Map();
  const addAdj = (a, b) => {
    if (a === b) return;
    if (!adjacency.has(a)) adjacency.set(a, new Set());
    adjacency.get(a).add(b);
  };
  edgeGroups.forEach((byTarget, from) => {
    byTarget.forEach((_types, to) => {
      addAdj(rankProxy(from), rankProxy(to));
      addAdj(rankProxy(to), rankProxy(from));
    });
  });

  const bfsParent = new Map(); // id -> id parent dans l'arbre couvrant depuis le centre
  const rootProxy = centerId ? rankProxy(remapEndpoint(centerId)) : null;
  if (rootProxy && adjacency.has(rootProxy)) {
    bfsParent.set(rootProxy, null);
    const queue = [rootProxy];
    while (queue.length) {
      const cur = queue.shift();
      adjacency.get(cur)?.forEach(nb => {
        if (!bfsParent.has(nb)) {
          bfsParent.set(nb, cur);
          queue.push(nb);
        }
      });
    }
  }

  edgeGroups.forEach((byTarget, from) => {
    byTarget.forEach((_types, to) => {
      const rf = rankProxy(from);
      const rt = rankProxy(to);
      if (rf === rt) return;
      if (bfsParent.size > 0) {
        // Seules les arêtes de l'arbre couvrant (parent -> enfant) contraignent
        // le rang, pour que celui-ci reflète la distance au centre — les autres
        // (ex. liens entre nœuds de même rang) sont ignorées.
        if (bfsParent.get(rt) === rf) { g.setEdge(rf, rt); return; }
        if (bfsParent.get(rf) === rt) { g.setEdge(rt, rf); return; }
        if (!bfsParent.has(rf) || !bfsParent.has(rt)) g.setEdge(rf, rt);
        return;
      }
      g.setEdge(rf, rt);
    });
  });

  dagre.layout(g);

  const topLeft = new Map();
  bundle.nodeMap.forEach(n => {
    if (!visibleIds.has(n.id)) return;
    const saved = positions?.get(n.id);
    if (saved) {
      topLeft.set(n.id, saved);
    } else {
      const pos = g.node(n.id);
      topLeft.set(n.id, { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 });
    }
  });

  // 3. Disposition en grille des membres de chaque zone — un rectangle
  //    compact (plusieurs colonnes) plutôt qu'une longue colonne verticale,
  //    centré sur le barycentre calculé par dagre pour le cluster. Les
  //    positions sauvegardées (déplacées manuellement) sont préservées.
  clusters.forEach((cluster, zoneId) => {
    if (cluster.members.length < 2) return;
    const c = g.node(zoneId);
    const { cols, rows } = clusterGrid.get(zoneId);
    const gridW = cols * ZONE_GRID_GAP_X;
    const gridH = rows * ZONE_GRID_GAP_Y;
    cluster.members.forEach((id, i) => {
      if (positions?.get(id)) return;
      const col = i % cols;
      const row = Math.floor(i / cols);
      const cx = c.x - gridW / 2 + col * ZONE_GRID_GAP_X + ZONE_GRID_GAP_X / 2;
      const cy = c.y - gridH / 2 + row * ZONE_GRID_GAP_Y + ZONE_GRID_GAP_Y / 2;
      topLeft.set(id, { x: cx - NODE_W / 2, y: cy - NODE_H / 2 });
    });
  });

  // ── Résolution des chevauchements ─────────────────────────────────────────
  // dagre ne garantit la non-superposition qu'entre nœuds de rangs adjacents ;
  // deux zones (qui occupent un rectangle bien plus grand qu'un nœud, et dont
  // dagre ne connaît que le placement de leur centre) — ou une zone et un nœud
  // isolé — peuvent malgré tout se recouvrir. On traite les zones comme des
  // "nœuds" de premier niveau au même titre que les nœuds isolés, et on écarte
  // par itérations toute paire de boîtes qui se chevauchent encore, en
  // préservant les positions sauvegardées par l'utilisateur (`positions`).
  const zoneMemberIds = new Set();
  const overlapItems = [];
  clusters.forEach((cluster, zoneId) => {
    if (cluster.members.length < 2) return;
    cluster.members.forEach(id => zoneMemberIds.add(id));
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let movable = true;
    cluster.members.forEach(id => {
      if (positions?.get(id)) movable = false;
      const tl = topLeft.get(id);
      minX = Math.min(minX, tl.x);
      minY = Math.min(minY, tl.y);
      maxX = Math.max(maxX, tl.x + NODE_W);
      maxY = Math.max(maxY, tl.y + NODE_H);
    });
    overlapItems.push({
      kind: 'zone',
      members: cluster.members,
      movable,
      box: {
        x: minX - ZONE_PADDING_X, y: minY - ZONE_PADDING_TOP,
        w: (maxX - minX) + ZONE_PADDING_X * 2,
        h: (maxY - minY) + ZONE_PADDING_TOP + ZONE_PADDING_BOTTOM,
      },
    });
  });
  bundle.nodeMap.forEach(n => {
    if (!visibleIds.has(n.id) || zoneMemberIds.has(n.id)) return;
    const tl = topLeft.get(n.id);
    overlapItems.push({
      kind: 'node',
      id: n.id,
      movable: !positions?.get(n.id),
      box: { x: tl.x, y: tl.y, w: NODE_W, h: NODE_H },
    });
  });
  overlapItems.forEach(item => { item.origX = item.box.x; item.origY = item.box.y; });

  const OVERLAP_GAP = 24;
  for (let iter = 0; iter < 6; iter++) {
    for (let i = 0; i < overlapItems.length; i++) {
      for (let j = i + 1; j < overlapItems.length; j++) {
        const a = overlapItems[i], b = overlapItems[j];
        if (!a.movable && !b.movable) continue;
        const dx = Math.min(a.box.x + a.box.w, b.box.x + b.box.w) - Math.max(a.box.x, b.box.x);
        const dy = Math.min(a.box.y + a.box.h, b.box.y + b.box.h) - Math.max(a.box.y, b.box.y);
        if (dx <= 0 || dy <= 0) continue; // pas de recouvrement
        const both = a.movable && b.movable;
        if (dx < dy) {
          const sign = Math.sign((b.box.x + b.box.w / 2) - (a.box.x + a.box.w / 2)) || 1;
          const push = dx + OVERLAP_GAP;
          if (a.movable) a.box.x -= sign * (both ? push / 2 : push);
          if (b.movable) b.box.x += sign * (both ? push / 2 : push);
        } else {
          const sign = Math.sign((b.box.y + b.box.h / 2) - (a.box.y + a.box.h / 2)) || 1;
          const push = dy + OVERLAP_GAP;
          if (a.movable) a.box.y -= sign * (both ? push / 2 : push);
          if (b.movable) b.box.y += sign * (both ? push / 2 : push);
        }
      }
    }
  }

  overlapItems.forEach(item => {
    if (!item.movable) return;
    const dx = item.box.x - item.origX;
    const dy = item.box.y - item.origY;
    if (!dx && !dy) return;
    if (item.kind === 'node') {
      topLeft.set(item.id, { x: item.box.x, y: item.box.y });
    } else {
      item.members.forEach(id => {
        const tl = topLeft.get(id);
        topLeft.set(id, { x: tl.x + dx, y: tl.y + dy });
      });
    }
  });

  // Rectangles de zone — englobent la position effective (sauvegardée ou
  // calculée) de leurs membres ; pas de zone pour un groupe à un seul membre.
  // `clusters` (zoneId -> ids des membres) est renvoyé pour permettre au
  // déplacement d'une zone de translater ses membres (drag-and-drop).
  const zoneMembers = new Map();
  const zoneNodes = [...clusters.entries()]
    .filter(([, cluster]) => cluster.members.length >= 2)
    .map(([zoneId, cluster]) => {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      cluster.members.forEach(id => {
        const tl = topLeft.get(id);
        minX = Math.min(minX, tl.x);
        minY = Math.min(minY, tl.y);
        maxX = Math.max(maxX, tl.x + NODE_W);
        maxY = Math.max(maxY, tl.y + NODE_H);
      });
      zoneMembers.set(zoneId, cluster.members);
      return {
        id: zoneId,
        type: 'zoneNode',
        position: { x: minX - ZONE_PADDING_X, y: minY - ZONE_PADDING_TOP },
        data: {
          nom: cluster.nom,
          level: cluster.level,
          width: (maxX - minX) + ZONE_PADDING_X * 2,
          height: (maxY - minY) + ZONE_PADDING_TOP + ZONE_PADDING_BOTTOM,
        },
        draggable: true,
        selectable: false,
        zIndex: -1,
      };
    });

  const entityNodes = [...bundle.nodeMap.values()]
    .filter(n => visibleIds.has(n.id))
    .map(n => ({
      id: n.id,
      type: 'legacyNode',
      position: topLeft.get(n.id),
      data: { ...n, isCenter: n.id === centerId, highlighted: highlightedIds?.has(n.id) ?? false },
    }));

  const nodes = [...zoneNodes, ...entityNodes];

  // Les ancrages (sourceHandle/targetHandle) ne sont pas figés ici : ils sont
  // recalculés dynamiquement (cf. `_withHandles`) à partir des positions
  // courantes des nœuds, y compris pendant/après un déplacement manuel.
  const edges = [];
  edgeGroups.forEach((byTarget, from) => {
    byTarget.forEach((types, to) => {
      const typeArr = [...types];
      const labels = typeArr.map(t => RELATION_LABELS[t] ?? t);
      const label = labels.length <= 2 ? labels.join(' / ') : `${labels[0]} +${labels.length - 1}`;
      const edgeColor = RELATION_COLORS[typeArr[0]] ?? T.sub;
      edges.push({
        id: `${from}->${to}`,
        source: from,
        target: to,
        label,
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
        style: { stroke: edgeColor, strokeOpacity: 0.75 },
        labelStyle: { fontSize: 10, fill: T.muted },
        labelBgStyle: { fill: T.white, fillOpacity: 0.9 },
      });
    });
  });

  return { nodes, edges, clusters: zoneMembers };
};

// Couleur des nœuds dans la mini-carte — reflète la sémantique entité/communauté
const _miniMapNodeColor = (node) => {
  const data = node.data ?? {};
  return data.kind === 'entity'
    ? (ENTITY_COLORS[data.type] ?? '#9e9e9e')
    : (COMMUNITY_COLORS[data.level] ?? '#bdbdbd');
};

// ── Canvas React Flow — recadre la vue quand le graphe sous-jacent change ─────
// `fitKey` ne change qu'au re-layout (nouveau bundle/centre), pas pendant un drag.
const LegacyKbCanvas = ({ nodes, edges, fitKey, onNodesChange, onNodeClick, onNodeDoubleClick, onPaneClick }) => {
  const { fitView } = useReactFlow();

  React.useEffect(() => {
    if (!nodes.length) return;
    const id = requestAnimationFrame(() => fitView({ padding: 0.15, duration: 300 }));
    return () => cancelAnimationFrame(id);
  }, [fitKey, fitView]);

  return (
    <ReactFlowCanvas
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodesChange={onNodesChange}
      onNodeClick={onNodeClick}
      onNodeDoubleClick={onNodeDoubleClick}
      onPaneClick={onPaneClick}
      nodesDraggable={true}
      nodesConnectable={false}
      fitView
    >
      <Background color={T.borderStrong} gap={20} />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={_miniMapNodeColor}
        maskColor="rgba(255,255,255,0.6)"
        style={{ background: T.panel, border: `1px solid ${T.border}` }}
      />
    </ReactFlowCanvas>
  );
};

// ── Mini-chat flottant — pilote le canvas via `graph_action` (highlight/impact_paths) ──
// Session dédiée (sessionStorage), indépendante du chat principal. Affiche un bouton
// "Détails" (requête Cypher + params) pour les réponses `impact_paths`.
const LegacyKbChat = ({ apiFetch, onGraphAction }) => {
  const [open, setOpen] = React.useState(false);
  const [messages, setMessages] = React.useState([]); // { role, content, queryInfo? }
  const [input, setInput] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [openDetails, setOpenDetails] = React.useState(new Set());

  const sessionIdRef = React.useRef(null);
  if (!sessionIdRef.current) {
    let sid = sessionStorage.getItem('nlaz-legacykb-session');
    if (!sid) { sid = _uid(); sessionStorage.setItem('nlaz-legacykb-session', sid); }
    sessionIdRef.current = sid;
  }

  const listRef = React.useRef(null);
  React.useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, loading]);

  const send = React.useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionIdRef.current, mode: 'standard' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.session_id && data.session_id !== sessionIdRef.current) {
        sessionIdRef.current = data.session_id;
        sessionStorage.setItem('nlaz-legacykb-session', data.session_id);
      }
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        queryInfo: data.graph_action?.query_info ?? null,
      }]);
      if (data.graph_action) onGraphAction(data.graph_action);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Erreur : ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, apiFetch, onGraphAction]);

  const toggleDetails = (i) => {
    setOpenDetails(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Assistant Legacy KB"
        style={{
          position: 'absolute', right: 20, bottom: 20, zIndex: 30,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 46, height: 46, borderRadius: '50%',
          border: 'none', background: T.azure, color: T.white,
          boxShadow: '0 4px 14px rgba(28,27,24,.22)', cursor: 'pointer',
        }}
      >
        <Ic.Chat s={20} />
      </button>
    );
  }

  return (
    <div style={{
      position: 'absolute', right: 20, bottom: 20, zIndex: 30,
      display: 'flex', flexDirection: 'column',
      width: 340, height: 440, maxHeight: 'calc(100% - 40px)',
      background: T.white, border: `1px solid ${T.border}`, borderRadius: T.radiusMd,
      boxShadow: '0 4px 18px rgba(28,27,24,.18)', fontFamily: T.font, overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: `1px solid ${T.border}`, flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: T.ink }}>Assistant Legacy KB</span>
        <button
          onClick={() => setOpen(false)}
          style={{ display: 'flex', border: 'none', background: 'transparent', color: T.muted, cursor: 'pointer', padding: 4, borderRadius: T.radiusSm }}
          title="Fermer"
        >
          <Ic.Close s={14} />
        </button>
      </div>

      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {messages.length === 0 && (
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.6 }}>
            Posez une question sur le graphe (ex. « montre-moi RE1570C et ses dépendances »,
            « qu'est-ce qui dépend de tel programme »…) — la réponse peut piloter le canvas
            (surlignage, analyse d'impact).
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '90%', padding: '7px 11px', borderRadius: T.radiusMd, fontSize: 12.5, lineHeight: 1.55,
              background: m.role === 'user' ? T.azureSoft : T.panel,
              color: T.ink,
            }}>
              {m.role === 'assistant'
                ? <MarkdownContent text={m.content} />
                : m.content}
            </div>
            {m.queryInfo && (
              <div style={{ marginTop: 4 }}>
                <button
                  onClick={() => toggleDetails(i)}
                  style={{ border: 'none', background: 'transparent', color: T.azure, fontFamily: T.font, fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}
                >
                  {openDetails.has(i) ? 'Masquer les détails' : 'Détails'}
                </button>
                {openDetails.has(i) && (
                  <div style={{
                    marginTop: 4, padding: 8, borderRadius: T.radiusSm,
                    background: T.panel2, border: `1px solid ${T.border}`,
                    fontFamily: T.mono, fontSize: 10.5, color: T.sub,
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxWidth: 280,
                  }}>
                    {m.queryInfo.cypher}
                    {'\n\n'}
                    {JSON.stringify(m.queryInfo.params, null, 2)}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {loading && <div style={{ fontSize: 12, color: T.muted }}>Réflexion…</div>}
      </div>

      <div style={{ display: 'flex', gap: 6, padding: 10, borderTop: `1px solid ${T.border}`, flexShrink: 0 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Votre question…"
          style={{
            flex: 1, border: `1px solid ${T.border}`, borderRadius: T.radiusPill,
            padding: '7px 12px', fontFamily: T.font, fontSize: 12.5, color: T.ink, outline: 'none',
          }}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
            border: 'none', background: T.azure, color: T.white,
            cursor: (loading || !input.trim()) ? 'default' : 'pointer',
            opacity: (loading || !input.trim()) ? 0.6 : 1,
          }}
          title="Envoyer"
        >
          <Ic.Up s={16} />
        </button>
      </div>
    </div>
  );
};

// ── Page principale ─────────────────────────────────────────────────────────
const LegacyKbPage = ({ apiFetch }) => {
  const apiFetchRef  = React.useRef(apiFetch);
  apiFetchRef.current = apiFetch;

  const [query,        setQuery]        = React.useState('');
  const [searchResults, setSearchResults] = React.useState([]);
  const [searching,    setSearching]    = React.useState(false);
  const [searchError,  setSearchError]  = React.useState(null);

  const [selectedTypes, setSelectedTypes] = React.useState(new Set());
  const [searchDescriptions, setSearchDescriptions] = React.useState(false);

  const [hierarchy,         setHierarchy]         = React.useState([]);
  const [expandedDomainIds, setExpandedDomainIds] = React.useState(new Set());
  const [showingDomains, setShowingDomains] = React.useState(false);
  const [domainsError, setDomainsError] = React.useState(null);

  const [stats,        setStats]        = React.useState(null);
  const [statsError,   setStatsError]   = React.useState(null);

  const [bundle,       setBundle]       = React.useState(null); // { nodeMap: Map, edgeList: [] }
  const [centerId,     setCenterId]     = React.useState(null);
  const [selectedId,   setSelectedId]   = React.useState(null);

  // ── Surlignage piloté par le mini-chat (legacykb_highlight/impact_paths) ──
  const [highlightedIds, setHighlightedIds] = React.useState(new Set());

  // ── Menu "Affichage" — types/niveaux de nœuds visibles dans le graphe ─────
  const [visibleKinds, setVisibleKinds] = React.useState(() => new Set(VISIBILITY_OPTIONS.map(o => o.key)));
  const [showDisplayMenu, setShowDisplayMenu] = React.useState(false);

  const toggleVisibleKind = React.useCallback((key) => {
    setVisibleKinds(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  // ── Stats (chargées une fois au montage) ─────────────────────────────────
  React.useEffect(() => {
    apiFetch(`${API_BASE}/legacykb/stats`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setStats)
      .catch(err => setStatsError(err.message));
  }, [apiFetch]);

  // ── Recherche ─────────────────────────────────────────────────────────────
  const runSearch = React.useCallback(async () => {
    const q = query.trim();
    if (!q) { setSearchResults([]); return; }
    setSearching(true);
    setSearchError(null);
    setShowingDomains(false);
    try {
      const params = new URLSearchParams({ q, limit: '30' });
      if (selectedTypes.size > 0) params.set('types', [...selectedTypes].join(','));
      if (searchDescriptions) params.set('descriptions', 'true');
      const res = await apiFetch(`${API_BASE}/legacykb/search?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSearchResults(data.items ?? []);
    } catch (err) {
      setSearchError(err.message);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [query, apiFetch, selectedTypes, searchDescriptions]);

  // Relance la recherche quand les filtres changent (si une requête est déjà saisie)
  React.useEffect(() => {
    if (query.trim()) runSearch();
  }, [selectedTypes, searchDescriptions]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleType = React.useCallback((type) => {
    setSelectedTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  }, []);

  // ── Parcourir par domaine fonctionnel (Community niveau 2) ────────────────
  const loadDomains = React.useCallback(async () => {
    if (showingDomains) { setShowingDomains(false); return; }
    setDomainsError(null);
    if (hierarchy.length > 0) { setShowingDomains(true); setSearchResults([]); return; }
    try {
      const res = await apiFetch(`${API_BASE}/legacykb/hierarchy`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setHierarchy(data.items ?? []);
      setShowingDomains(true);
      setSearchResults([]);
    } catch (err) {
      setDomainsError(err.message);
    }
  }, [apiFetch, hierarchy, showingDomains]);

  // ── Charge le voisinage d'un nœud et fusionne dans le bundle ──────────────
  const exploreNode = React.useCallback(async (nodeId) => {
    try {
      const res = await apiFetchRef.current(
        `${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}/neighbors`
      );
      if (!res.ok) return;
      const data = await res.json(); // { center, neighbors, edges }

      setBundle(prev => {
        const nodeMap = prev ? new Map(prev.nodeMap) : new Map();
        const edgeList = prev ? [...prev.edgeList] : [];
        const seenKeys = new Set(edgeList.map(e => `${e.from}|${e.to}|${e.type}`));

        nodeMap.set(data.center.id, data.center);
        data.neighbors.forEach(n => nodeMap.set(n.id, n));
        data.edges.forEach(e => {
          const k = `${e.from}|${e.to}|${e.type}`;
          if (!seenKeys.has(k)) { seenKeys.add(k); edgeList.push(e); }
        });
        return { nodeMap, edgeList };
      });
      setCenterId(data.center.id);
      setSelectedId(data.center.id);
    } catch (_) { /* exploration silencieuse si l'API est injoignable */ }
  }, []);

  // ── Charge toutes les entités d'une communauté dans le canvas ────────────
  const loadCommunitySubgraph = React.useCallback(async (nodeId) => {
    try {
      const res = await apiFetchRef.current(
        `${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}/subgraph`
      );
      if (!res.ok) return;
      const data = await res.json();

      setBundle(prev => {
        const nodeMap = prev ? new Map(prev.nodeMap) : new Map();
        const edgeList = prev ? [...prev.edgeList] : [];
        const seenKeys = new Set(edgeList.map(e => `${e.from}|${e.to}|${e.type}`));
        nodeMap.set(data.center.id, data.center);
        data.neighbors.forEach(n => nodeMap.set(n.id, n));
        data.edges.forEach(e => {
          const k = `${e.from}|${e.to}|${e.type}`;
          if (!seenKeys.has(k)) { seenKeys.add(k); edgeList.push(e); }
        });
        return { nodeMap, edgeList };
      });
      setCenterId(data.center.id);
      setSelectedId(data.center.id);
    } catch (_) {}
  }, []);

  // ── Sélection d'un résultat de recherche → démarre/étend l'exploration ────
  const handleResultClick = React.useCallback((item) => {
    exploreNode(item.id);
  }, [exploreNode]);

  // ── Réinitialise la vue puis la recentre sur ce nœud (et son voisinage) ───
  const recenterOnNode = React.useCallback(async (nodeId) => {
    try {
      const res = await apiFetchRef.current(
        `${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}/neighbors`
      );
      if (!res.ok) return;
      const data = await res.json(); // { center, neighbors, edges }

      const nodeMap = new Map();
      nodeMap.set(data.center.id, data.center);
      data.neighbors.forEach(n => nodeMap.set(n.id, n));

      positionsRef.current.clear();
      setBundle({ nodeMap, edgeList: data.edges });
      setCenterId(data.center.id);
      setSelectedId(data.center.id);
    } catch (_) { /* recentrage silencieux si l'API est injoignable */ }
  }, []);

  // ── Redispose la vue actuelle (sans la réinitialiser) en hiérarchie depuis ce nœud ──
  const relayoutOnNode = React.useCallback((nodeId) => {
    positionsRef.current.clear();
    setCenterId(nodeId);
    setSelectedId(nodeId);
  }, []);

  // ── Applique sur le canvas un `graph_action` renvoyé par le mini-chat ─────
  // "highlight" : étend l'exploration sur les nœuds désignés (réutilise
  // exploreNode/recenterOnNode/relayoutOnNode). "impact_paths" : le backend
  // fournit déjà le sous-graphe complet (nodes/edges) — appliqué directement,
  // sans requête supplémentaire. Dans les deux cas, met en évidence les nœuds
  // concernés via `highlightedIds`.
  const handleGraphAction = React.useCallback(async (action) => {
    if (!action) return;
    setHighlightedIds(new Set(action.node_ids));

    if (action.type === 'impact_paths') {
      if (!action.nodes || action.nodes.length === 0) return;
      const nodeMap = new Map();
      action.nodes.forEach(n => nodeMap.set(n.id, n));
      positionsRef.current.clear();
      setBundle({ nodeMap, edgeList: action.edges ?? [] });
      const center = action.nodes[0];
      setCenterId(center.id);
      setSelectedId(center.id);
      return;
    }

    const ids = action.node_ids;
    if (!ids || ids.length === 0) return;
    if (!bundle || bundle.nodeMap.size === 0) {
      await recenterOnNode(ids[0]);
      for (const id of ids.slice(1)) await exploreNode(id);
    } else {
      for (const id of ids) await exploreNode(id);
      relayoutOnNode(ids[0]);
    }
  }, [bundle, exploreNode, recenterOnNode, relayoutOnNode]);

  // ── Réinitialise la vue ────────────────────────────────────────────────
  const clearGraph = React.useCallback(() => {
    setBundle(null);
    setCenterId(null);
    setSelectedId(null);
    setContextMenu(null);
    setHighlightedIds(new Set());
    positionsRef.current.clear();
    setFlowNodes([]);
    setFlowEdges([]);
  }, []);

  // ── Retire un nœud de la vue, ainsi que les nœuds qui deviennent isolés ───
  // (plus aucune arête vers un nœud restant) suite à cette suppression.
  const [contextMenu, setContextMenu] = React.useState(null); // { nodeId, x, y }

  const removeNodeFromView = React.useCallback((nodeId) => {
    setContextMenu(null);
    if (!bundle) return;

    const nodeMap = new Map(bundle.nodeMap);
    nodeMap.delete(nodeId);

    const edgeList = bundle.edgeList.filter(e => e.from !== nodeId && e.to !== nodeId);

    const degree = new Map();
    edgeList.forEach(e => {
      degree.set(e.from, (degree.get(e.from) ?? 0) + 1);
      degree.set(e.to, (degree.get(e.to) ?? 0) + 1);
    });
    nodeMap.forEach((_, id) => {
      if ((degree.get(id) ?? 0) === 0) nodeMap.delete(id);
    });

    bundle.nodeMap.forEach((_, id) => {
      if (!nodeMap.has(id)) positionsRef.current.delete(id);
    });

    if (nodeMap.size === 0) {
      setBundle(null);
      setCenterId(null);
      setSelectedId(null);
    } else {
      setBundle({ nodeMap, edgeList });
      setCenterId(c => (c && nodeMap.has(c)) ? c : null);
      setSelectedId(s => (s && nodeMap.has(s)) ? s : null);
    }
  }, [bundle]);

  // ── Nœuds/arêtes React Flow dérivés du bundle (layout dagre) ──────────────
  // Les positions déplacées manuellement (positionsRef) sont conservées entre
  // les re-layouts déclenchés par l'exploration de nouveaux voisins.
  const positionsRef = React.useRef(new Map());
  const clustersRef = React.useRef(new Map()); // zoneId -> ids des membres (pour le drag de zone)
  const [flowNodes, setFlowNodes] = React.useState([]);
  const [flowEdges, setFlowEdges] = React.useState([]);
  const [layoutVersion, setLayoutVersion] = React.useState(0);

  React.useEffect(() => {
    const { nodes, edges, clusters } = _layout(bundle, centerId, positionsRef.current, visibleKinds, highlightedIds);
    clustersRef.current = clusters;
    setFlowNodes(nodes);
    setFlowEdges(edges);
    setLayoutVersion(v => v + 1);
  }, [bundle, centerId, visibleKinds, highlightedIds]);

  // Déplacer une zone translate tous ses membres de la même quantité —
  // permet de réorganiser le schéma sans perdre le regroupement visuel.
  const onNodesChange = React.useCallback((changes) => {
    setFlowNodes(prev => {
      let next = applyNodeChanges(changes, prev);
      changes.forEach(c => {
        if (c.type !== 'position' || !c.position) return;
        const members = clustersRef.current.get(c.id);
        if (!members) {
          positionsRef.current.set(c.id, c.position);
          return;
        }
        const before = prev.find(n => n.id === c.id);
        if (!before) return;
        const dx = c.position.x - before.position.x;
        const dy = c.position.y - before.position.y;
        if (!dx && !dy) return;
        const memberSet = new Set(members);
        next = next.map(n => {
          if (!memberSet.has(n.id)) return n;
          const np = { x: n.position.x + dx, y: n.position.y + dy };
          positionsRef.current.set(n.id, np);
          return { ...n, position: np };
        });
      });
      return next;
    });
  }, []);

  const nodeCount = flowNodes.length;
  const arcCount = flowEdges.length;

  // Ancrages recalculés à chaque rendu (positions courantes, y compris pendant
  // un drag) — cf. `_withHandles`.
  const flowEdgesAnchored = React.useMemo(
    () => _withHandles(flowEdges, flowNodes),
    [flowEdges, flowNodes]
  );

  // Une zone représente le nœud :Community sous-jacent (`zone:c|123` -> `c|123`)
  // — clic/double-clic s'y comportent comme sur ce nœud (panneau de détail,
  // menu contextuel, exploration).
  const _targetId = (node) => node.type === 'zoneNode' ? node.id.slice('zone:'.length) : node.id;

  // Le menu contextuel (et son overlay plein écran) ne s'ouvre qu'après un
  // court délai — si un double-clic survient avant, il est annulé et
  // remplacé par l'extension de la vue (sinon l'overlay du premier clic
  // empêcherait le navigateur de détecter le second clic sur le nœud).
  const clickTimerRef = React.useRef(null);

  const handleNodeClick = React.useCallback((evt, node) => {
    const id = _targetId(node);
    const { clientX, clientY } = evt;
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current);
    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;
      setSelectedId(id);
      setContextMenu({ nodeId: id, x: clientX, y: clientY });
    }, 250);
  }, []);
  const handleNodeDoubleClick = React.useCallback((_evt, node) => {
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setContextMenu(null);
    exploreNode(_targetId(node));
  }, [exploreNode]);
  const handlePaneClick = React.useCallback(() => {
    setSelectedId(null);
    setContextMenu(null);
  }, []);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
      {/* TopBar — recherche + stats */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 14, padding: '14px 22px',
        borderBottom: `1px solid ${T.border}`, background: T.white, fontFamily: T.font,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 260, maxWidth: 480 }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 8,
            height: 36, padding: '0 12px',
            borderRadius: T.radiusPill, border: `1px solid ${T.border}`, background: T.panel,
          }}>
            <Ic.Search s={14} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runSearch(); }}
              placeholder="Rechercher un programme, fichier, communauté…"
              style={{
                flex: 1, border: 'none', outline: 'none', background: 'transparent',
                fontFamily: T.font, fontSize: 13, color: T.ink,
              }}
            />
          </div>
          <button
            onClick={runSearch}
            disabled={searching}
            style={{
              height: 36, padding: '0 16px', borderRadius: T.radiusPill,
              border: 'none', background: T.azure, color: T.white,
              fontFamily: T.font, fontSize: 13, fontWeight: 600,
              cursor: searching ? 'default' : 'pointer', opacity: searching ? 0.6 : 1,
              whiteSpace: 'nowrap',
            }}
          >
            {searching ? 'Recherche…' : 'Rechercher'}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          {stats && !statsError && (
            <span style={{ fontSize: 12.5, color: T.muted, whiteSpace: 'nowrap' }}>
              {Object.values(stats.entities ?? {}).reduce((a, b) => a + b, 0)} entités ·{' '}
              {Object.values(stats.communities ?? {}).reduce((a, b) => a + b, 0)} communautés
            </span>
          )}
          {bundle && (
            <>
              <span style={{ fontSize: 12.5, color: T.muted, whiteSpace: 'nowrap' }}>
                {nodeCount} nœud{nodeCount > 1 ? 's' : ''} · {arcCount} arc{arcCount > 1 ? 's' : ''}
              </span>
              <button
                onClick={clearGraph}
                style={{
                  height: 32, padding: '0 14px', borderRadius: T.radiusPill,
                  border: `1px solid ${T.border}`, background: T.white, color: T.sub,
                  fontFamily: T.font, fontSize: 12.5, fontWeight: 500, cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                Réinitialiser
              </button>
            </>
          )}

          {highlightedIds.size > 0 && (
            <button
              onClick={() => setHighlightedIds(new Set())}
              style={{
                height: 32, padding: '0 14px', borderRadius: T.radiusPill,
                border: `1px solid ${T.border}`, background: T.white, color: T.sub,
                fontFamily: T.font, fontSize: 12.5, fontWeight: 500, cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Effacer le surlignage
            </button>
          )}

          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowDisplayMenu(v => !v)}
              title="Options d'affichage"
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 32, height: 32, borderRadius: T.radiusPill,
                border: `1px solid ${showDisplayMenu ? T.azureBorder : T.border}`,
                background: showDisplayMenu ? T.azureSoft : T.white,
                color: showDisplayMenu ? T.azureInk : T.sub,
                cursor: 'pointer', flexShrink: 0,
              }}
            >
              <Ic.Settings s={15} />
            </button>
            {showDisplayMenu && (
              <>
                <div onClick={() => setShowDisplayMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
                <div style={{
                  position: 'absolute', top: '100%', right: 0, marginTop: 6, zIndex: 41,
                  width: 220, padding: 6,
                  background: T.white, border: `1px solid ${T.border}`, borderRadius: T.radiusMd,
                  boxShadow: '0 4px 18px rgba(28,27,24,.14)',
                }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, color: T.muted, textTransform: 'uppercase',
                    letterSpacing: 0.4, padding: '6px 10px 4px',
                  }}>
                    Niveaux / types affichés
                  </div>
                  {VISIBILITY_OPTIONS.map(opt => (
                    <label
                      key={opt.key}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        padding: '6px 10px', borderRadius: T.radiusSm,
                        fontSize: 12.5, fontWeight: 500, color: T.ink, cursor: 'pointer',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = T.panel}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <input
                        type="checkbox"
                        checked={visibleKinds.has(opt.key)}
                        onChange={() => toggleVisibleKind(opt.key)}
                      />
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: opt.color, flexShrink: 0 }} />
                      {opt.label}
                    </label>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Filtres — type d'entité, recherche élargie, parcours par domaine */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        padding: '8px 22px', borderBottom: `1px solid ${T.border}`,
        background: T.railBg, fontFamily: T.font,
      }}>
        {stats && Object.keys(stats.entities ?? {}).map(type => {
          const active = selectedTypes.has(type);
          return (
            <button
              key={type}
              onClick={() => toggleType(type)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                fontSize: 11.5, fontWeight: 600, borderRadius: 999, padding: '3px 10px',
                border: `1px solid ${active ? T.azureBorder : T.border}`,
                background: active ? T.azureSoft : T.white,
                color: active ? T.azureInk : T.sub,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: ENTITY_COLORS[type] ?? '#9e9e9e', flexShrink: 0 }} />
              {ENTITY_TYPE_LABELS[type] ?? type}
            </button>
          );
        })}

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.sub, cursor: 'pointer', marginLeft: 4 }}>
          <input
            type="checkbox"
            checked={searchDescriptions}
            onChange={e => setSearchDescriptions(e.target.checked)}
          />
          Recherche élargie aux descriptions
        </label>

        <button
          onClick={loadDomains}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto',
            fontSize: 11.5, fontWeight: 600, borderRadius: 999, padding: '3px 10px',
            border: `1px solid ${showingDomains ? T.azureBorder : T.border}`,
            background: showingDomains ? T.azureSoft : T.white,
            color: showingDomains ? T.azureInk : T.sub,
            cursor: 'pointer', whiteSpace: 'nowrap',
          }}
        >
          Parcourir par domaine
        </button>
        {domainsError && (
          <span style={{ fontSize: 11.5, color: T.danger }}>Erreur : {domainsError}</span>
        )}
      </div>

      {/* Corps : résultats de recherche / canvas / panneau de détail */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Résultats de recherche / liste de domaines */}
        {(showingDomains ? hierarchy.length > 0 : searchResults.length > 0) && (
          <div style={{
            width: 280, flexShrink: 0, borderRight: `1px solid ${T.border}`,
            background: T.railBg, overflowY: 'auto', fontFamily: T.font,
          }}>
            {showingDomains ? (
              /* ── Hiérarchie L2 → L1 en accordéon ─────────────────────────── */
              hierarchy.map(domain => (
                <div key={domain.id}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '8px 10px 8px 12px',
                    borderBottom: `1px solid ${T.border}`,
                    background: selectedId === domain.id ? T.azureSoft : 'transparent',
                  }}>
                    <button
                      onClick={() => setExpandedDomainIds(prev => {
                        const next = new Set(prev);
                        if (next.has(domain.id)) next.delete(domain.id); else next.add(domain.id);
                        return next;
                      })}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        flex: 1, minWidth: 0, textAlign: 'left',
                        background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                      }}
                    >
                      <span style={{ fontSize: 11, color: T.muted, width: 10, flexShrink: 0, userSelect: 'none' }}>
                        {expandedDomainIds.has(domain.id) ? '▾' : '▸'}
                      </span>
                      <span style={{ width: 9, height: 9, borderRadius: 2, background: COMMUNITY_COLORS[2] ?? '#bdbdbd', flexShrink: 0 }} />
                      <span style={{ fontSize: 12.5, fontWeight: 600, color: T.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                        {domain.nom}
                      </span>
                      <span style={{ fontSize: 10.5, color: T.muted, flexShrink: 0, marginLeft: 4 }}>
                        {domain.subdomains.length}
                      </span>
                    </button>
                    <button
                      onClick={() => loadCommunitySubgraph(domain.id)}
                      title="Charger ce domaine dans le canvas"
                      style={{
                        flexShrink: 0, height: 22, padding: '0 8px',
                        borderRadius: T.radiusPill,
                        border: `1px solid ${T.azureBorder}`,
                        background: T.azureSoft, color: T.azureInk,
                        fontSize: 11, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
                      }}
                    >
                      Charger
                    </button>
                  </div>
                  {expandedDomainIds.has(domain.id) && domain.subdomains.map(sub => (
                    <div
                      key={sub.id}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 4,
                        padding: '6px 10px 6px 30px',
                        borderBottom: `1px solid ${T.border}`,
                        background: selectedId === sub.id ? T.azureSoft : 'transparent',
                      }}
                      onMouseEnter={e => { if (selectedId !== sub.id) e.currentTarget.style.background = T.panel; }}
                      onMouseLeave={e => { if (selectedId !== sub.id) e.currentTarget.style.background = 'transparent'; }}
                    >
                      <button
                        onClick={() => handleResultClick(sub)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          flex: 1, minWidth: 0, textAlign: 'left',
                          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                        }}
                      >
                        <span style={{ width: 7, height: 7, borderRadius: 1, background: COMMUNITY_COLORS[1] ?? '#bdbdbd', flexShrink: 0 }} />
                        <span style={{ fontSize: 12, color: T.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                          {sub.nom}
                        </span>
                        <span style={{ fontSize: 10.5, color: T.muted, flexShrink: 0, marginLeft: 4 }}>
                          {sub.entity_count}
                        </span>
                      </button>
                      <button
                        onClick={() => loadCommunitySubgraph(sub.id)}
                        title="Charger ce sous-domaine dans le canvas"
                        style={{
                          flexShrink: 0, height: 20, padding: '0 7px',
                          borderRadius: T.radiusPill,
                          border: `1px solid ${T.border}`,
                          background: T.white, color: T.sub,
                          fontSize: 10.5, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
                        }}
                      >
                        Charger
                      </button>
                    </div>
                  ))}
                </div>
              ))
            ) : (
              /* ── Résultats de recherche ────────────────────────────────────── */
              searchResults.map(item => (
                <button
                  key={item.id}
                  onClick={() => handleResultClick(item)}
                  style={{
                    display: 'flex', flexDirection: 'column', gap: 2,
                    width: '100%', textAlign: 'left', padding: '10px 14px',
                    border: 'none', borderBottom: `1px solid ${T.border}`,
                    background: selectedId === item.id ? T.azureSoft : 'transparent',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={e => { if (selectedId !== item.id) e.currentTarget.style.background = T.panel; }}
                  onMouseLeave={e => { if (selectedId !== item.id) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: T.ink }}>
                    <span style={{
                      width: 9, height: 9, borderRadius: item.kind === 'community' ? 2 : '50%', flexShrink: 0,
                      background: item.kind === 'entity' ? (ENTITY_COLORS[item.type] ?? '#9e9e9e') : (COMMUNITY_COLORS[item.level] ?? '#bdbdbd'),
                    }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.nom}</span>
                  </span>
                  <span style={{ fontSize: 11, color: T.muted }}>
                    {item.kind === 'entity'
                      ? (ENTITY_TYPE_LABELS[item.type] ?? item.type)
                      : (COMMUNITY_LEVEL_LABELS[item.level] ?? `Communauté niveau ${item.level}`)}
                    {item.kind === 'community' && item.subdomains != null
                      ? ` · ${item.subdomains} sous-domaine${item.subdomains === 1 ? '' : 's'}`
                      : ''}
                  </span>
                </button>
              ))
            )}
          </div>
        )}

        {/* Canvas */}
        <div style={{ flex: 1, position: 'relative', background: T.white, minHeight: 0 }}>
          {bundle ? (
            <ReactFlowProvider>
              <LegacyKbCanvas
                nodes={flowNodes}
                edges={flowEdgesAnchored}
                fitKey={layoutVersion}
                onNodesChange={onNodesChange}
                onNodeClick={handleNodeClick}
                onNodeDoubleClick={handleNodeDoubleClick}
                onPaneClick={handlePaneClick}
              />
            </ReactFlowProvider>
          ) : (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24,
              fontFamily: T.font,
            }}>
              <span style={{ fontSize: 13, color: T.ink, fontWeight: 500 }}>
                Legacy KB — graphe brut GraphRAG
              </span>
              <span style={{ fontSize: 12, color: T.muted, maxWidth: 380, textAlign: 'center', lineHeight: 1.6 }}>
                Recherchez un programme, un fichier ou une communauté, puis cliquez sur un
                résultat pour afficher son voisinage. Double-clic sur un nœud pour étendre
                l'exploration.
              </span>
              {statsError && (
                <span style={{ fontSize: 12, color: T.danger, marginTop: 6 }}>
                  Impossible de charger les statistiques : {statsError}
                </span>
              )}
              {searchError && (
                <span style={{ fontSize: 12, color: T.danger, marginTop: 6 }}>
                  Erreur de recherche : {searchError}
                </span>
              )}
            </div>
          )}

          {contextMenu && (
            <NodeContextMenu
              x={contextMenu.x}
              y={contextMenu.y}
              onRecenter={() => { recenterOnNode(contextMenu.nodeId); setContextMenu(null); }}
              onRecenterLayout={() => { relayoutOnNode(contextMenu.nodeId); setContextMenu(null); }}
              onRemove={() => removeNodeFromView(contextMenu.nodeId)}
              onClose={() => setContextMenu(null)}
            />
          )}

          <LegacyKbChat apiFetch={apiFetch} onGraphAction={handleGraphAction} />
        </div>

        {selectedId && (
          <NodeDetailPanel
            key={selectedId}
            nodeId={selectedId}
            apiFetch={apiFetch}
            onNavigate={exploreNode}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
};

Object.assign(window, { LegacyKbPage });
