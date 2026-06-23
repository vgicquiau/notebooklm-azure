// src/LegacyKbPage.jsx — Vue "Legacy KB" : exploration du graphe GraphRAG brut (neo4j-legacykb)
// Props: apiFetch(url, options) — wrapper _apiFetch (injecte X-API-Key), fourni par App
//
// Lecture seule, via api/routers/legacykb.py (connexion directe à l'instance Neo4j
// neo4j-legacykb, distincte du graphe ADG-M, retiré). Recherche par nom/titre, puis
// exploration progressive du voisinage par double-clic. Rendu avec React Flow (xyflow,
// window.ReactFlow) ; layout force-directed via d3-force (window.d3).

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
  useInternalNode,
  getStraightPath,
  BaseEdge,
} = window.ReactFlow;

const {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceX,
  forceY,
} = window.d3;

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

// Nœuds carrés — format uniforme, ratio 1:1.
const NODE_W = 90;
const NODE_H = 90;

// Labels abrégés pour la pastille de type (badge compact dans le nœud carré).
const ENTITY_TYPE_SHORT = {
  Program: 'PRG', BatchJob: 'JOB', Copybook: 'CPY',
  GenericFile: 'FIC', 'External/Doc': 'EXT',
};
const COMMUNITY_LEVEL_SHORT = { 2: 'DOM', 1: 'SDOM' };

// ── Nœud custom — carré 90×90, badge de type abrégé + nom sur 2 lignes ────────
const LegacyNode = ({ data }) => {
  const isEntity = data.kind === 'entity';
  const color = isEntity
    ? (ENTITY_COLORS[data.type] ?? '#9e9e9e')
    : (COMMUNITY_COLORS[data.level] ?? '#bdbdbd');
  const shortLabel = isEntity
    ? (ENTITY_TYPE_SHORT[data.type] ?? data.type.slice(0, 3).toUpperCase())
    : (COMMUNITY_LEVEL_SHORT[data.level] ?? `N${data.level}`);

  const handleStyle = { background: 'transparent', border: 'none', width: 1, height: 1, opacity: 0 };

  return (
    <div
      onMouseDown={() => data.onFreeze?.(data.id)}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 5,
        width: NODE_W, height: NODE_H, boxSizing: 'border-box', padding: '8px',
        borderRadius: T.radiusSm,
        border: data.isCenter ? `2px solid ${T.white}` : 'none',
        background: color,
        fontFamily: T.font, color: T.white, textAlign: 'center',
        boxShadow: data.highlighted
          ? '0 2px 6px rgba(28,27,24,0.25), 0 0 0 3px rgba(251,140,0,0.7)'
          : '0 2px 6px rgba(28,27,24,0.25)',
      }}
    >
      {/* Un seul handle source/target par nœud — le point de connexion réel sur le
          pourtour est calculé géométriquement par `FloatingEdge`, pas par xyflow. */}
      <Handle type="target" position={Position.Top} style={handleStyle} />
      <Handle type="source" position={Position.Top} style={handleStyle} />
      <span style={{
        flexShrink: 0,
        padding: '2px 7px', borderRadius: 999,
        background: T.white,
        fontSize: 9, fontWeight: 700, color, letterSpacing: 0.5,
        maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {shortLabel}
      </span>
      <span style={{
        fontSize: 11, fontWeight: 600, width: '100%', lineHeight: 1.35,
        overflow: 'hidden',
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        textShadow: '0 1px 2px rgba(0,0,0,0.25)',
      }}>
        {data.nom}
      </span>
    </div>
  );
};

const NODE_TYPES = { legacyNode: LegacyNode };

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

// ── Connexions flottantes (style Neo4j Bloom/Browser) ─────────────────────────
// Point d'intersection entre le segment reliant les deux centres et le pourtour
// d'un carré `size`×`size` centré sur `from` et regardant vers `to` — c'est ce qui
// donne l'impression qu'une arête peut toucher n'importe quel point du contour
// d'un nœud (pas seulement 4 points fixes), comme dans Neo4j Bloom/Browser.
// Géométrie standard : on raisonne dans le repère du carré (demi-côté `h`), on
// clippe le point à l'intersection avec le bord le plus proche selon le rapport
// entre la composante dominante du vecteur direction et `h`.
const _squareBorderPoint = (from, to, size) => {
  const h = size / 2;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (dx === 0 && dy === 0) return { x: from.x, y: from.y };
  // Facteur d'échelle pour ramener le point le plus loin du carré exactement sur
  // son bord (la plus petite des deux échelles qui touchent un bord vertical ou
  // horizontal — équivalent à l'intersection rayon/carré depuis le centre).
  const scale = h / Math.max(Math.abs(dx), Math.abs(dy));
  return { x: from.x + dx * scale, y: from.y + dy * scale };
};

// Composant d'arête custom — calcule ses points de départ/arrivée par géométrie
// (intersection avec le carré de chaque nœud) plutôt que par un handle fixe.
// `useInternalNode` lit la position/dimension à jour de chaque nœud à chaque
// rendu (y compris pendant un tick de simulation ou un drag), donc le tracé suit
// fluidement le pourtour entier sans logique d'ancrage par côté.
const FloatingEdge = ({ id, source, target, label, style, markerEnd, labelStyle, labelBgStyle }) => {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode) return null;

  const sourceCenter = {
    x: sourceNode.internals.positionAbsolute.x + NODE_W / 2,
    y: sourceNode.internals.positionAbsolute.y + NODE_H / 2,
  };
  const targetCenter = {
    x: targetNode.internals.positionAbsolute.x + NODE_W / 2,
    y: targetNode.internals.positionAbsolute.y + NODE_H / 2,
  };
  const sourcePoint = _squareBorderPoint(sourceCenter, targetCenter, NODE_W);
  const targetPoint = _squareBorderPoint(targetCenter, sourceCenter, NODE_W);

  const [path, labelX, labelY] = getStraightPath({
    sourceX: sourcePoint.x, sourceY: sourcePoint.y,
    targetX: targetPoint.x, targetY: targetPoint.y,
  });

  return (
    <BaseEdge
      id={id} path={path} markerEnd={markerEnd} style={style}
      label={label} labelX={labelX} labelY={labelY}
      labelStyle={labelStyle} labelBgStyle={labelBgStyle}
    />
  );
};

const EDGE_TYPES = { floating: FloatingEdge };

// ── Prépare la topologie + l'amorçage du layout force-directed (d3-force) pour le
//    bundle courant — ne calcule aucune position finale ici (cf. simulation dans le
//    composant) : seulement les nœuds/liens de simulation et un point de départ par
//    entité, pour que `forceManyBody`/`forceLink` convergent vite et proprement.
// `positions` (Map id → {x,y} coin haut-gauche) permet de conserver les positions
// déplacées manuellement par l'utilisateur lors d'un re-layout (nouveaux voisins) —
// appliquées ici comme `fx`/`fy` (position figée) sur le nœud de simulation.
// `visibleKinds` (Set de clés `_nodeKindKey`) filtre les types/niveaux affichés
// (menu "Affichage") — un nœud absent de cet ensemble est entièrement exclu du
// schéma (lui et ses arêtes).
const _prepareSimulation = (bundle, centerId, positions, visibleKinds) => {
  if (!bundle) return null;

  const filteredNodeMap = new Map(
    [...bundle.nodeMap].filter(([, n]) => !visibleKinds || visibleKinds.has(_nodeKindKey(n)))
  );
  const visibleIds = new Set(filteredNodeMap.keys());
  const allEdges = bundle.edgeList.filter(e => filteredNodeMap.has(e.from) && filteredNodeMap.has(e.to));

  // Les arêtes parallèles entre une même paire de nœuds (plusieurs types de
  // relation) sont fusionnées en une seule, pour réduire le nombre de flux
  // affichés à l'écran. Map imbriquée (from -> to -> types) pour éviter de
  // construire une clé composite à partir d'identifiants contenant `|`.
  const edgeGroups = new Map(); // from -> Map(to -> Set<type>)
  allEdges.forEach(e => {
    if (e.from === e.to) return;
    if (!edgeGroups.has(e.from)) edgeGroups.set(e.from, new Map());
    const byTarget = edgeGroups.get(e.from);
    if (!byTarget.has(e.to)) byTarget.set(e.to, new Set());
    byTarget.get(e.to).add(e.type);
  });

  // ── Liens de simulation ────────────────────────────────────────────────────
  // Toutes les arêtes du schéma servent de ressort d'attraction (entités comme
  // communautés, traitées uniformément — pas de regroupement par zone).
  const simLinkKeys = new Set();
  const simLinks = [];
  edgeGroups.forEach((byTarget, from) => {
    byTarget.forEach((_types, to) => {
      const key = from < to ? `${from}|${to}` : `${to}|${from}`;
      if (simLinkKeys.has(key)) return;
      simLinkKeys.add(key);
      simLinks.push({ source: from, target: to });
    });
  });

  // ── Amorçage concentrique par distance BFS depuis `centerId` ─────────────────
  // Place chaque nœud sur un cercle dont le rayon dépend de sa distance de hop au
  // centre — angle reparti par incrément d'angle d'or (évite les alignements
  // radiaux). Ce n'est qu'un point de départ : la simulation relaxe ensuite
  // librement cet amorçage selon les forces (liens/répulsion).
  const bfsDepth = new Map();
  if (centerId) {
    const adjacency = new Map();
    const addAdj = (a, b) => {
      if (a === b) return;
      if (!adjacency.has(a)) adjacency.set(a, new Set());
      adjacency.get(a).add(b);
    };
    simLinks.forEach(({ source, target }) => { addAdj(source, target); addAdj(target, source); });
    if (adjacency.has(centerId) || visibleIds.has(centerId)) {
      bfsDepth.set(centerId, 0);
      const queue = [centerId];
      while (queue.length) {
        const cur = queue.shift();
        adjacency.get(cur)?.forEach(nb => {
          if (!bfsDepth.has(nb)) {
            bfsDepth.set(nb, bfsDepth.get(cur) + 1);
            queue.push(nb);
          }
        });
      }
    }
  }

  // ── Nœuds de simulation (un par nœud visible, entité ou communauté) ──────────
  // Priorité de l'amorçage : position sauvegardée (figée via fx/fy) > centre épinglé
  // (fx/fy à l'origine) > cercle concentrique par distance BFS > dispersion aléatoire
  // légère (composantes non atteintes depuis le centre, ou pas de centre actif —
  // évite que tous les nœuds démarrent superposés en (0,0), ce qui empêcherait
  // `forceManyBody` de les séparer efficacement).
  const GOLDEN_ANGLE = 2.399963229728653; // ~137.5° — répartition régulière sans alignement
  const RING_SPACING = NODE_W * 2.4;
  let ringIdx = 0;
  const simNodes = [...bundle.nodeMap.values()]
    .filter(n => visibleIds.has(n.id))
    .map(n => {
      const node = { id: n.id };
      const saved = positions?.get(n.id); // {x,y} coin haut-gauche sauvegardé
      if (saved) {
        node.x = saved.x + NODE_W / 2;
        node.y = saved.y + NODE_H / 2;
        node.fx = node.x;
        node.fy = node.y;
      } else if (n.id === centerId) {
        node.x = 0; node.y = 0;
        node.fx = 0; node.fy = 0;
      } else if (bfsDepth.has(n.id)) {
        const depth = bfsDepth.get(n.id);
        const angle = ringIdx * GOLDEN_ANGLE;
        ringIdx += 1;
        node.x = Math.cos(angle) * depth * RING_SPACING;
        node.y = Math.sin(angle) * depth * RING_SPACING;
      } else {
        node.x = (Math.random() - 0.5) * NODE_W * 4;
        node.y = (Math.random() - 0.5) * NODE_H * 4;
      }
      return node;
    });

  return { simNodes, simLinks, edgeGroups, visibleIds };
};

// ── Position (coin haut-gauche) de chaque nœud à partir de l'état courant de la
//    simulation — appelé à chaque tick pour dériver le rendu React Flow.
const _topLeftFromSimNodes = (simNodes) => {
  const topLeft = new Map();
  simNodes.forEach(n => topLeft.set(n.id, { x: n.x - NODE_W / 2, y: n.y - NODE_H / 2 }));
  return topLeft;
};

const _buildGraphNodes = (topLeft, bundle, visibleIds, centerId, highlightedIds) =>
  [...bundle.nodeMap.values()]
    .filter(n => visibleIds.has(n.id))
    .map(n => ({
      id: n.id,
      type: 'legacyNode',
      position: topLeft.get(n.id) ?? { x: 0, y: 0 },
      data: { ...n, isCenter: n.id === centerId, highlighted: highlightedIds?.has(n.id) ?? false },
    }));

// Le point de connexion sur le pourtour de chaque nœud n'est pas figé ici : il est
// recalculé géométriquement à chaque rendu par `FloatingEdge` (cf. ci-dessus). Les
// arêtes elles-mêmes ne dépendent d'aucune position — calculées une seule fois.
const _buildEdges = (edgeGroups) => {
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
        type: 'floating',
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
        style: { stroke: edgeColor, strokeOpacity: 0.75 },
        labelStyle: { fontSize: 10, fill: T.muted },
        labelBgStyle: { fill: T.white, fillOpacity: 0.9 },
      });
    });
  });
  return edges;
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
const LegacyKbCanvas = ({
  nodes, edges, fitKey, onNodesChange, onNodeClick, onNodeDoubleClick, onPaneClick,
  onNodeDragStart, onNodeDrag, onNodeDragStop,
}) => {
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
      edgeTypes={EDGE_TYPES}
      onNodesChange={onNodesChange}
      onNodeClick={onNodeClick}
      onNodeDoubleClick={onNodeDoubleClick}
      onPaneClick={onPaneClick}
      onNodeDragStart={onNodeDragStart}
      onNodeDrag={onNodeDrag}
      onNodeDragStop={onNodeDragStop}
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

  // ── Nœuds/arêtes React Flow dérivés du bundle (layout force-directed) ────────
  // Les positions déplacées manuellement (positionsRef) sont conservées entre les
  // re-layouts déclenchés par l'exploration de nouveaux voisins (appliquées comme
  // positions figées — fx/fy — sur le nœud de simulation correspondant).
  const positionsRef = React.useRef(new Map());
  // Instance d3-force courante — exposée hors de l'effet pour que les callbacks de
  // drag (`onNodeDrag*`, définis plus bas) puissent relancer la simulation et fixer
  // fx/fy du nœud déplacé (physique live, cf. piste B).
  const simulationRef = React.useRef(null);
  const [flowNodes, setFlowNodes] = React.useState([]);
  const [flowEdges, setFlowEdges] = React.useState([]);
  const [layoutVersion, setLayoutVersion] = React.useState(0);

  // Toujours à jour pour les callbacks de simulation (tick/end), sans figer
  // `highlightedIds` au moment de la création de l'effet ci-dessous.
  const highlightedIdsRef = React.useRef(highlightedIds);
  highlightedIdsRef.current = highlightedIds;

  // Fige un nœud à sa position courante dans la simulation — appelé dès l'appui du
  // pointeur (`onMouseDown` natif dans `LegacyNode`, injecté via `data.onFreeze`
  // ci-dessous), *avant même* que React Flow ne détermine si l'interaction est un
  // simple clic ou un drag. Sans ça, tant que la simulation tourne, le nœud continue
  // de bouger sous le curseur pendant tout l'intervalle appui→relâchement d'un clic
  // (`onNodeDragStart` de React Flow ne suffit pas : il ne se déclenche qu'une fois
  // un mouvement réel détecté, pas sur un appui immobile) — le clic "rate" alors
  // (relâché sur le fond du canvas une fois le nœud déjà parti). `handleNodeClick`
  // libère ce gel dès qu'un simple clic est confirmé ; sinon il devient la position
  // figée du drag (comportement déjà existant).
  const freezeNode = React.useCallback((id) => {
    const simNode = simulationRef.current?.nodes().find(n => n.id === id);
    if (simNode) { simNode.fx = simNode.x; simNode.fy = simNode.y; }
  }, []);

  // (Re)lance une simulation de forces à chaque changement de topologie affichée
  // (nouveau bundle, recentrage, filtres affichage) — *pas* sur `highlightedIds` seul
  // (cf. effet séparé plus bas), pour qu'un simple surlignage depuis le mini-chat ou
  // le bouton "Effacer" ne fasse pas repartir l'animation physique depuis zéro.
  React.useEffect(() => {
    const prep = _prepareSimulation(bundle, centerId, positionsRef.current, visibleKinds);
    if (!prep) {
      setFlowNodes([]);
      setFlowEdges([]);
      return;
    }

    // Les arêtes ne dépendent d'aucune position — calculées une seule fois, pas à
    // chaque tick (cf. `_buildEdges`).
    setFlowEdges(_buildEdges(prep.edgeGroups));

    const renderFromTopLeft = (topLeft) => {
      const nodes = _buildGraphNodes(topLeft, bundle, prep.visibleIds, centerId, highlightedIdsRef.current);
      setFlowNodes(nodes.map(n => ({ ...n, data: { ...n.data, onFreeze: freezeNode } })));
    };

    const simulation = forceSimulation(prep.simNodes)
      .force('link', forceLink(prep.simLinks).id(d => d.id).distance(NODE_W * 1.8).strength(0.3))
      .force('charge', forceManyBody().strength(-260))
      .force('collide', forceCollide(NODE_W * 0.62))
      .force('x', forceX(0).strength(0.02))
      .force('y', forceY(0).strength(0.02));
    simulationRef.current = simulation;

    renderFromTopLeft(_topLeftFromSimNodes(prep.simNodes)); // amorçage immédiat, avant le 1er tick
    setLayoutVersion(v => v + 1); // fitView sur la dispersion initiale

    simulation.on('tick', () => {
      renderFromTopLeft(_topLeftFromSimNodes(prep.simNodes));
    });

    simulation.on('end', () => {
      setLayoutVersion(v => v + 1); // fitView final, une fois la disposition stabilisée
    });

    return () => {
      simulationRef.current = null;
      simulation.stop();
    };
  }, [bundle, centerId, visibleKinds]);

  // ── Physique live pendant le drag (style Neo4j Bloom) ─────────────────────────
  // Sans ça, déplacer un nœud à la main le réécrit instantanément sans relancer la
  // simulation — les voisins ne réagissent pas. Pattern standard d3-force-drag,
  // adapté aux callbacks de drag de React Flow (on ne pilote pas le drag lui-même,
  // juste fx/fy du nœud de simulation correspondant à la position courante).
  //
  // `onNodeDragStart` fige aussi le nœud dès l'appui du pointeur (pas seulement
  // pendant un déplacement réel) : tant que la simulation tourne, un nœud continue
  // de bouger sous le curseur pendant tout l'intervalle appui→relâchement d'un
  // simple clic, ce qui fait fréquemment "rater" le clic (relâché sur le fond du
  // canvas plutôt que sur le nœud, une fois celui-ci déjà parti). `handleNodeClick`
  // libère ce gel dès qu'il est confirmé qu'il s'agissait bien d'un simple clic
  // (pas d'un drag) — sinon le gel devient la position figée du drag, comportement
  // déjà existant.
  const onNodeDragStart = React.useCallback((_evt, node) => {
    const simNode = simulationRef.current?.nodes().find(n => n.id === node.id);
    if (simNode) {
      simNode.fx = node.position.x + NODE_W / 2;
      simNode.fy = node.position.y + NODE_H / 2;
    }
    simulationRef.current?.alphaTarget(0.3).restart();
  }, []);
  const onNodeDrag = React.useCallback((_evt, node) => {
    const simNode = simulationRef.current?.nodes().find(n => n.id === node.id);
    if (!simNode) return;
    simNode.fx = node.position.x + NODE_W / 2;
    simNode.fy = node.position.y + NODE_H / 2;
  }, []);
  const onNodeDragStop = React.useCallback(() => {
    simulationRef.current?.alphaTarget(0);
  }, []);

  // Patch léger du surlignage (anneau doré) sans relancer la simulation physique —
  // ne touche que `data.highlighted` sur les nœuds déjà affichés.
  React.useEffect(() => {
    setFlowNodes(prev => prev.map(n => ({ ...n, data: { ...n.data, highlighted: highlightedIds.has(n.id) } })));
  }, [highlightedIds]);

  const onNodesChange = React.useCallback((changes) => {
    setFlowNodes(prev => {
      const next = applyNodeChanges(changes, prev);
      changes.forEach(c => {
        if (c.type === 'position' && c.position) positionsRef.current.set(c.id, c.position);
      });
      return next;
    });
  }, []);

  const nodeCount = flowNodes.length;
  const arcCount = flowEdges.length;

  // Le menu contextuel (et son overlay plein écran) ne s'ouvre qu'après un
  // court délai — si un double-clic survient avant, il est annulé et
  // remplacé par l'extension de la vue (sinon l'overlay du premier clic
  // empêcherait le navigateur de détecter le second clic sur le nœud).
  const clickTimerRef = React.useRef(null);

  const handleNodeClick = React.useCallback((evt, node) => {
    const id = node.id;
    const { clientX, clientY } = evt;
    // Simple clic confirmé (pas un drag, sinon onNodeClick n'aurait pas été
    // appelé) — libère le gel posé par `onNodeDragStart` pour que le nœud
    // reprenne sa participation normale à la simulation.
    const simNode = simulationRef.current?.nodes().find(n => n.id === id);
    if (simNode) { simNode.fx = null; simNode.fy = null; }
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
    exploreNode(node.id);
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
                edges={flowEdges}
                fitKey={layoutVersion}
                onNodesChange={onNodesChange}
                onNodeClick={handleNodeClick}
                onNodeDoubleClick={handleNodeDoubleClick}
                onPaneClick={handlePaneClick}
                onNodeDragStart={onNodeDragStart}
                onNodeDrag={onNodeDrag}
                onNodeDragStop={onNodeDragStop}
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
